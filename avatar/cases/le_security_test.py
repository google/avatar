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

from avatar import BumblePandoraDevice
from avatar import PandoraDevice
from avatar import PandoraDevices
from avatar import pandora
from bumble.pairing import PairingConfig
from bumble.pairing import PairingDelegate
from mobly import base_test
from mobly import signals
from mobly import test_runner
from mobly.asserts import assert_equal  # type: ignore
from mobly.asserts import assert_in  # type: ignore
from mobly.asserts import assert_is_not_none  # type: ignore
from mobly.asserts import fail  # type: ignore
from pandora.host_pb2 import PUBLIC
from pandora.host_pb2 import RANDOM
from pandora.host_pb2 import Connection
from pandora.host_pb2 import DataTypes
from pandora.host_pb2 import OwnAddressType
from pandora.security_pb2 import LE_LEVEL3
from pandora.security_pb2 import LEVEL2
from pandora.security_pb2 import PairingEventAnswer
from pandora.security_pb2 import SecureResponse
from pandora.security_pb2 import WaitSecurityResponse
from typing import Any, Literal, Optional, Tuple, Union


class LeSecurityTest(base_test.BaseTestClass):  # type: ignore[misc]
    '''
    This class aim to test LE Pairing on LE
    Bluetooth devices.
    '''

    devices: Optional[PandoraDevices] = None

    # pandora devices.
    dut: PandoraDevice
    ref: PandoraDevice

    def setup_class(self) -> None:
        self.devices = PandoraDevices(self)
        self.dut, self.ref, *_ = self.devices

        # Enable BR/EDR for Bumble devices.
        for device in self.devices:
            if isinstance(device, BumblePandoraDevice):
                device.config.setdefault('classic_enabled', True)

    def teardown_class(self) -> None:
        if self.devices:
            self.devices.stop_all()

    @avatar.parameterized(
        *itertools.product(
            ('outgoing_connection', 'incoming_connection'),
            ('outgoing_pairing', 'incoming_pairing'),
            ('against_random', 'against_public'),
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
                'against_both_display_and_keyboard',
            ),
            (
                'ltk_irk_csrk',
                'ltk_irk_csrk_lk',
            ),
        )
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_le_pairing(
        self,
        connect: Union[Literal['outgoing_connection'], Literal['incoming_connection']],
        pair: Union[Literal['outgoing_pairing'], Literal['incoming_pairing']],
        ref_address_type_name: Union[Literal['against_random'], Literal['against_public']],
        variant: Union[
            Literal['accept'],
            Literal['accept_ctkd'],
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
            Literal['against_both_display_and_keyboard'],
        ],
        key_distribution: Union[
            Literal['ltk_irk_csrk'],
            Literal['ltk_irk_csrk_lk'],
        ],
    ) -> None:
        if self.dut.name == 'android' and connect == 'outgoing_connection' and pair == 'incoming_pairing':
            # TODO: do not skip when doing physical tests.
            raise signals.TestSkip('TODO: Yet to implement the test cases:\n')

        if self.dut.name == 'android' and connect == 'incoming_connection' and pair == 'outgoing_pairing':
            # TODO: do not skip when doing physical tests.
            raise signals.TestSkip('TODO: Yet to implement the test cases:\n')

        if self.dut.name == 'android' and 'disconnect' in variant:
            raise signals.TestSkip(
                'TODO: Fix AOSP pandora server for this variant:\n'
                + '- Looks like `Disconnect`  never complete.\n'
                + '- When disconnected the `Secure/WaitSecurity` never returns.'
            )

        if self.dut.name == 'android' and 'reject' in variant:
            raise signals.TestSkip('TODO: Currently these scnearios are not working. Working on them.')

        if self.ref.name == 'android' and ref_address_type_name == 'against_public':
            raise signals.TestSkip('Android does not support PUBLIC address type.')

        if isinstance(self.ref, BumblePandoraDevice) and ref_io_capability == 'against_default_io_cap':
            raise signals.TestSkip('Skip default IO cap for Bumble REF.')

        if not isinstance(self.ref, BumblePandoraDevice) and ref_io_capability != 'against_default_io_cap':
            raise signals.TestSkip('Unable to override IO capability on non Bumble device.')

        if 'lk' in key_distribution and ref_io_capability == 'against_no_output_no_input':
            raise signals.TestSkip('CTKD requires Security Level 4')

        # Factory reset both DUT and REF devices.
        await asyncio.gather(self.dut.reset(), self.ref.reset())

        # Override REF IO capability if supported.
        if isinstance(self.ref, BumblePandoraDevice):
            io_capability = {
                'against_no_output_no_input': PairingDelegate.IoCapability.NO_OUTPUT_NO_INPUT,
                'against_keyboard_only': PairingDelegate.IoCapability.KEYBOARD_INPUT_ONLY,
                'against_display_only': PairingDelegate.IoCapability.DISPLAY_OUTPUT_ONLY,
                'against_display_yes_no': PairingDelegate.IoCapability.DISPLAY_OUTPUT_AND_YES_NO_INPUT,
                'against_both_display_and_keyboard': PairingDelegate.IoCapability.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT,
            }[ref_io_capability]
            self.ref.server_config.io_capability = io_capability
            bumble_key_distribution = sum(
                {
                    'ltk': PairingDelegate.KeyDistribution.DISTRIBUTE_ENCRYPTION_KEY,
                    'irk': PairingDelegate.KeyDistribution.DISTRIBUTE_IDENTITY_KEY,
                    'csrk': PairingDelegate.KeyDistribution.DISTRIBUTE_SIGNING_KEY,
                    'lk': PairingDelegate.KeyDistribution.DISTRIBUTE_LINK_KEY,
                }[x]
                for x in key_distribution.split('_')
            )
            assert bumble_key_distribution
            self.ref.server_config.smp_local_initiator_key_distribution = bumble_key_distribution
            self.ref.server_config.smp_local_responder_key_distribution = bumble_key_distribution
            self.ref.server_config.identity_address_type = PairingConfig.AddressType.PUBLIC

        if isinstance(self.dut, BumblePandoraDevice):
            ALL_KEYS = (
                PairingDelegate.KeyDistribution.DISTRIBUTE_ENCRYPTION_KEY
                | PairingDelegate.KeyDistribution.DISTRIBUTE_IDENTITY_KEY
                | PairingDelegate.KeyDistribution.DISTRIBUTE_SIGNING_KEY
                | PairingDelegate.KeyDistribution.DISTRIBUTE_LINK_KEY
            )
            self.dut.server_config.smp_local_initiator_key_distribution = ALL_KEYS
            self.dut.server_config.smp_local_responder_key_distribution = ALL_KEYS
            self.dut.server_config.identity_address_type = PairingConfig.AddressType.PUBLIC

        dut_address_type = RANDOM
        ref_address_type = {
            'against_random': RANDOM,
            'against_public': PUBLIC,
        }[ref_address_type_name]

        # Pandora connection tokens
        ref_dut, dut_ref = None, None

        # Connection/pairing task.
        async def connect_and_pair() -> Tuple[SecureResponse, WaitSecurityResponse]:
            nonlocal ref_dut
            nonlocal dut_ref

            # Make LE connection task.
            async def connect_le(
                initiator: PandoraDevice,
                acceptor: PandoraDevice,
                initiator_addr_type: OwnAddressType,
                acceptor_addr_type: OwnAddressType,
            ) -> Tuple[Connection, Connection]:
                # Acceptor - Advertise
                advertisement = acceptor.aio.host.Advertise(
                    legacy=True,
                    connectable=True,
                    own_address_type=acceptor_addr_type,
                    data=DataTypes(manufacturer_specific_data=b'pause cafe'),
                )

                # Initiator - Scan and fetch the address
                scan = initiator.aio.host.Scan(own_address_type=initiator_addr_type)
                acceptor_scan = await anext(
                    (x async for x in scan if b'pause cafe' in x.data.manufacturer_specific_data)
                )  # pytype: disable=name-error
                scan.cancel()

                # Initiator - LE connect
                return await pandora.connect_le(initiator, advertisement, acceptor_scan, initiator_addr_type)

            # Make LE connection.
            if connect == 'incoming_connection':
                # DUT is acceptor
                ref_dut, dut_ref = await connect_le(self.ref, self.dut, ref_address_type, dut_address_type)
            else:
                # DUT is initiator
                dut_ref, ref_dut = await connect_le(self.dut, self.ref, dut_address_type, ref_address_type)

            # Pairing.

            if pair == 'incoming_pairing':
                return await asyncio.gather(
                    self.ref.aio.security.Secure(connection=ref_dut, le=LE_LEVEL3),
                    self.dut.aio.security.WaitSecurity(connection=dut_ref, le=LE_LEVEL3),
                )
            # Outgoing pairing
            return await asyncio.gather(
                self.dut.aio.security.Secure(connection=dut_ref, le=LE_LEVEL3),
                self.ref.aio.security.WaitSecurity(connection=ref_dut, le=LE_LEVEL3),
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
                    if 'lk' in key_distribution:
                        # Make a Classic connection
                        if self.dut.name == 'android':
                            # Android IOP: Android automatically trigger a BR/EDR connection request
                            # in this case.
                            ref_dut_classic_res = await self.ref.aio.host.WaitConnection(self.dut.address)
                            assert_is_not_none(ref_dut_classic_res.connection)
                            assert ref_dut_classic_res.connection
                            ref_dut_classic = ref_dut_classic_res.connection
                        else:
                            ref_dut_classic, _ = await pandora.connect(self.ref, self.dut)
                        # Try to encrypt Classic connection
                        ref_dut_secure = await self.ref.aio.security.Secure(ref_dut_classic, classic=LEVEL2)
                        assert_equal(ref_dut_secure.result_variant(), 'success')
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
