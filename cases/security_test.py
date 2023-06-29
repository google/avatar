# Copyright 2023 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import avatar
import itertools
import logging

from avatar import BumblePandoraDevice, PandoraDevice, PandoraDevices
from bumble.hci import HCI_CENTRAL_ROLE, HCI_PERIPHERAL_ROLE
from bumble.pairing import PairingDelegate
from mobly import base_test, signals, test_runner
from mobly.asserts import assert_equal  # type: ignore
from mobly.asserts import assert_in  # type: ignore
from mobly.asserts import assert_is_not_none  # type: ignore
from mobly.asserts import fail  # type: ignore
from pandora.host_pb2 import Connection
from pandora.security_pb2 import LEVEL2, PairingEventAnswer, SecureResponse, WaitSecurityResponse
from typing import Any, Literal, Optional, Tuple, Union


class SecurityTest(base_test.BaseTestClass):  # type: ignore[misc]
    '''
    This class aim to test SSP (Secure Simple Pairing) on Classic
    Bluetooth devices.
    '''

    devices: Optional[PandoraDevices] = None

    # pandora devices.
    dut: PandoraDevice
    ref: PandoraDevice

    @avatar.asynchronous
    async def setup_class(self) -> None:
        self.devices = PandoraDevices(self)
        self.dut, self.ref, *_ = self.devices

        # Enable BR/EDR mode and SSP for Bumble devices.
        for device in self.devices:
            if isinstance(device, BumblePandoraDevice):
                device.config.setdefault('classic_enabled', True)
                device.config.setdefault('classic_ssp_enabled', True)
                device.config.setdefault(
                    'server',
                    {
                        'io_capability': 'display_output_and_yes_no_input',
                    },
                )

        await asyncio.gather(self.dut.reset(), self.ref.reset())

    def teardown_class(self) -> None:
        if self.devices:
            self.devices.stop_all()

    @avatar.parameterized(
        *itertools.product(
            ('outgoing_connection', 'incoming_connection'),
            ('outgoing_pairing', 'incoming_pairing'),
            (
                'accept',
                'reject',
                'rejected',
                'disconnect',
                'disconnected',
            ),
            (
                'against_default_io_cap',
                'against_no_output_no_input',
                'against_keyboard_only',
                'against_display_only',
                'against_display_yes_no',
            ),
            ('against_central', 'against_peripheral'),
        )
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_ssp(
        self,
        connect: Union[Literal['outgoing_connection'], Literal['incoming_connection']],
        pair: Union[Literal['outgoing_pairing'], Literal['incoming_pairing']],
        variant: Union[
            Literal['accept'],
            Literal['reject'],
            Literal['rejected'],
            Literal['disconnect'],
            Literal['disconnected'],
        ],
        ref_io_capability: Union[
            Literal['against_default_io_cap'],
            Literal['against_no_output_no_input'],
            Literal['against_keyboard_only'],
            Literal['against_display_only'],
            Literal['against_display_yes_no'],
        ],
        ref_role: Union[
            Literal['against_central'],
            Literal['against_peripheral'],
        ],
    ) -> None:
        if self.dut.name == 'android' and connect == 'outgoing_connection' and pair == 'incoming_pairing':
            # TODO: do not skip when doing physical tests.
            raise signals.TestSkip(
                'TODO: Fix rootcanal when both side trigger authentication:\n'
                + 'Android always trigger auth for outgoing connections.'
            )

        if self.dut.name == 'android' and 'disconnect' in variant:
            raise signals.TestSkip(
                'TODO: Fix AOSP pandora server for this variant:\n'
                + '- Looks like `Disconnect`  never complete.\n'
                + '- When disconnected the `Secure/WaitSecurity` never returns.'
            )

        if (
            self.dut.name == 'android'
            and ref_io_capability == 'against_keyboard_only'
            and variant == 'rejected'
            and (connect == 'incoming_connection' or pair == 'outgoing_pairing')
        ):
            raise signals.TestSkip(
                'TODO: Fix AOSP stack for this variant:\n'
                + 'Android does not seems to react correctly against pairing reject from KEYBOARD_ONLY devices.'
            )

        if self.dut.name == 'android' and pair == 'outgoing_pairing' and ref_role == 'against_central':
            raise signals.TestSkip(
                'TODO: Fix PandoraSecurity server for android:\n'
                + 'report the encryption state the with the bonding state'
            )

        if self.ref.name == 'android':
            raise signals.TestSkip(
                'TODO: (add bug number) Fix core stack:\n'
                + 'BOND_BONDED event is triggered before the encryption changed'
            )

        if isinstance(self.ref, BumblePandoraDevice) and ref_io_capability == 'against_default_io_cap':
            raise signals.TestSkip('Skip default IO cap for Bumble REF.')

        if not isinstance(self.ref, BumblePandoraDevice) and ref_io_capability != 'against_default_io_cap':
            raise signals.TestSkip('Unable to override IO capability on non Bumble device.')

        # Factory reset both DUT and REF devices.
        await asyncio.gather(self.dut.reset(), self.ref.reset())

        # Override REF IO capability if supported.
        if isinstance(self.ref, BumblePandoraDevice):
            io_capability = {
                'against_no_output_no_input': PairingDelegate.IoCapability.NO_OUTPUT_NO_INPUT,
                'against_keyboard_only': PairingDelegate.IoCapability.KEYBOARD_INPUT_ONLY,
                'against_display_only': PairingDelegate.IoCapability.DISPLAY_OUTPUT_ONLY,
                'against_display_yes_no': PairingDelegate.IoCapability.DISPLAY_OUTPUT_AND_YES_NO_INPUT,
            }[ref_io_capability]
            self.ref.server_config.io_capability = io_capability

        # Pandora connection tokens
        ref_dut, dut_ref = None, None

        # Connection/pairing task.
        async def connect_and_pair() -> Tuple[SecureResponse, WaitSecurityResponse]:
            nonlocal ref_dut
            nonlocal dut_ref

            # Make classic connection task.
            async def bredr_connect(
                initiator: PandoraDevice, acceptor: PandoraDevice
            ) -> Tuple[Connection, Connection]:
                init_res, wait_res = await asyncio.gather(
                    initiator.aio.host.Connect(address=acceptor.address),
                    acceptor.aio.host.WaitConnection(address=initiator.address),
                )
                assert_equal(init_res.result_variant(), 'connection')
                assert_equal(wait_res.result_variant(), 'connection')
                assert init_res.connection is not None and wait_res.connection is not None
                return init_res.connection, wait_res.connection

            # Make classic connection.
            if connect == 'incoming_connection':
                ref_dut, dut_ref = await bredr_connect(self.ref, self.dut)
            else:
                dut_ref, ref_dut = await bredr_connect(self.dut, self.ref)

            # Role switch.
            if isinstance(self.ref, BumblePandoraDevice):
                ref_dut_raw = self.ref.device.lookup_connection(int.from_bytes(ref_dut.cookie.value, 'big'))
                if ref_dut_raw is not None:
                    role = {
                        'against_central': HCI_CENTRAL_ROLE,
                        'against_peripheral': HCI_PERIPHERAL_ROLE,
                    }[ref_role]

                    if ref_dut_raw.role != role:
                        self.ref.log.info(
                            f"Role switch to: {'`CENTRAL`' if role == HCI_CENTRAL_ROLE else '`PERIPHERAL`'}"
                        )
                        await ref_dut_raw.switch_role(role)

            # Pairing.
            if pair == 'incoming_pairing':
                return await asyncio.gather(
                    self.ref.aio.security.Secure(connection=ref_dut, classic=LEVEL2),
                    self.dut.aio.security.WaitSecurity(connection=dut_ref, classic=LEVEL2),
                )

            return await asyncio.gather(
                self.dut.aio.security.Secure(connection=dut_ref, classic=LEVEL2),
                self.ref.aio.security.WaitSecurity(connection=ref_dut, classic=LEVEL2),
            )

        # Listen for pairing event on bot DUT and REF.
        dut_pairing, ref_pairing = self.dut.aio.security.OnPairing(), self.ref.aio.security.OnPairing()

        # Start connection/pairing.
        connect_and_pair_task = asyncio.create_task(connect_and_pair())

        shall_pass = variant == 'accept'
        try:
            dut_pairing_fut = asyncio.create_task(anext(dut_pairing))
            ref_pairing_fut = asyncio.create_task(anext(ref_pairing))

            def on_done(_: Any) -> None:
                if not dut_pairing_fut.done():
                    dut_pairing_fut.cancel()
                if not ref_pairing_fut.done():
                    ref_pairing_fut.cancel()

            connect_and_pair_task.add_done_callback(on_done)

            ref_ev = await asyncio.wait_for(ref_pairing_fut, timeout=5.0)
            self.ref.log.info(f'REF pairing event: {ref_ev.method_variant()}')

            dut_ev_answer, ref_ev_answer = None, None
            if not connect_and_pair_task.done():
                dut_ev = await asyncio.wait_for(dut_pairing_fut, timeout=15.0)
                self.dut.log.info(f'DUT pairing event: {dut_ev.method_variant()}')

                if dut_ev.method_variant() in ('numeric_comparison', 'just_works'):
                    assert_in(ref_ev.method_variant(), ('numeric_comparison', 'just_works'))

                    confirm = True
                    if (
                        dut_ev.method_variant() == 'numeric_comparison'
                        and ref_ev.method_variant() == 'numeric_comparison'
                    ):
                        confirm = ref_ev.numeric_comparison == dut_ev.numeric_comparison

                    dut_ev_answer = PairingEventAnswer(event=dut_ev, confirm=False if variant == 'reject' else confirm)
                    ref_ev_answer = PairingEventAnswer(
                        event=ref_ev, confirm=False if variant == 'rejected' else confirm
                    )

                elif dut_ev.method_variant() == 'passkey_entry_notification':
                    assert_equal(ref_ev.method_variant(), 'passkey_entry_request')
                    assert_is_not_none(dut_ev.passkey_entry_notification)
                    assert dut_ev.passkey_entry_notification is not None

                    if variant == 'reject':
                        # DUT cannot reject, pairing shall pass.
                        shall_pass = True

                    ref_ev_answer = PairingEventAnswer(
                        event=ref_ev,
                        passkey=None if variant == 'rejected' else dut_ev.passkey_entry_notification,
                    )

                elif dut_ev.method_variant() == 'passkey_entry_request':
                    assert_equal(ref_ev.method_variant(), 'passkey_entry_notification')
                    assert_is_not_none(ref_ev.passkey_entry_notification)

                    if variant == 'rejected':
                        # REF cannot reject, pairing shall pass.
                        shall_pass = True

                    assert ref_ev.passkey_entry_notification is not None
                    dut_ev_answer = PairingEventAnswer(
                        event=dut_ev,
                        passkey=None if variant == 'reject' else ref_ev.passkey_entry_notification,
                    )

                else:
                    fail("")

                if variant == 'disconnect':
                    # Disconnect:
                    # - REF respond to pairing event if any.
                    # - DUT trigger disconnect.
                    if ref_ev_answer is not None:
                        ref_pairing.send_nowait(ref_ev_answer)
                    assert dut_ref is not None
                    await self.dut.aio.host.Disconnect(connection=dut_ref)

                elif variant == 'disconnected':
                    # Disconnected:
                    # - DUT respond to pairing event if any.
                    # - REF trigger disconnect.
                    if dut_ev_answer is not None:
                        dut_pairing.send_nowait(dut_ev_answer)
                    assert ref_dut is not None
                    await self.ref.aio.host.Disconnect(connection=ref_dut)

                else:
                    # Otherwise:
                    # - REF respond to pairing event if any.
                    # - DUT respond to pairing event if any.
                    if ref_ev_answer is not None:
                        ref_pairing.send_nowait(ref_ev_answer)
                    if dut_ev_answer is not None:
                        dut_pairing.send_nowait(dut_ev_answer)

        except (asyncio.CancelledError, asyncio.TimeoutError):
            logging.error('Pairing timed-out or has been canceled.')

        except AssertionError:
            logging.exception('Pairing failed.')
            if not connect_and_pair_task.done():
                connect_and_pair_task.cancel()

        finally:
            try:
                (secure, wait_security) = await asyncio.wait_for(connect_and_pair_task, 15.0)
                logging.info(f'Pairing result: {secure.result_variant()}/{wait_security.result_variant()}')

                if shall_pass:
                    assert_equal(secure.result_variant(), 'success')
                    assert_equal(wait_security.result_variant(), 'success')
                else:
                    assert_in(
                        secure.result_variant(),
                        ('connection_died', 'pairing_failure', 'authentication_failure', 'not_reached'),
                    )
                    assert_in(
                        wait_security.result_variant(),
                        ('connection_died', 'pairing_failure', 'authentication_failure', 'not_reached'),
                    )

            finally:
                dut_pairing.cancel()
                ref_pairing.cancel()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()  # type: ignore
