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
from pandora.security_pb2 import LEVEL2, PairingEventAnswer, SecureResponse, SecurityLevel, WaitSecurityResponse
from typing import Callable, Coroutine, Optional, Tuple

ALL_ROLES = (HCI_CENTRAL_ROLE, HCI_PERIPHERAL_ROLE)
ALL_IO_CAPABILITIES = (
    None,
    PairingDelegate.DISPLAY_OUTPUT_ONLY,
    PairingDelegate.DISPLAY_OUTPUT_AND_YES_NO_INPUT,
    PairingDelegate.KEYBOARD_INPUT_ONLY,
    PairingDelegate.NO_OUTPUT_NO_INPUT,
    PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT,
)


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

    @avatar.asynchronous
    async def setup_test(self) -> None:  # pytype: disable=wrong-arg-types
        await asyncio.gather(self.dut.reset(), self.ref.reset())

    @avatar.parameterized(*itertools.product(ALL_IO_CAPABILITIES, ALL_ROLES))  # type: ignore[misc]
    @avatar.asynchronous
    async def test_success_initiate_connection_initiate_pairing(
        self,
        ref_io_capability: Optional[PairingDelegate.IoCapability],
        ref_role: Optional[int],
    ) -> None:
        # Override REF IO capability if supported.
        set_io_capability(self.ref, ref_io_capability)

        # Connection/pairing task.
        async def connect_and_pair() -> Tuple[SecureResponse, WaitSecurityResponse]:
            dut_ref, ref_dut = await make_classic_connection(self.dut, self.ref)
            if ref_role is not None:
                await role_switch(self.ref, ref_dut, ref_role)
            return await authenticate(self.dut, dut_ref, self.ref, ref_dut, LEVEL2)

        # Handle pairing.
        initiator_pairing, acceptor_pairing = await handle_pairing(
            self.dut,
            self.ref,
            connect_and_pair,
        )

        # Assert success.
        assert_equal(initiator_pairing.result_variant(), 'success')
        assert_equal(acceptor_pairing.result_variant(), 'success')

    @avatar.parameterized(*itertools.product(ALL_IO_CAPABILITIES, ALL_ROLES))  # type: ignore[misc]
    @avatar.asynchronous
    async def test_success_initiate_connection_accept_pairing(
        self,
        ref_io_capability: Optional[PairingDelegate.IoCapability],
        ref_role: Optional[int],
    ) -> None:
        if not isinstance(self.dut, BumblePandoraDevice):
            raise signals.TestSkip('TODO: Fix rootcanal when both AOSP and Bumble trigger the auth.')

        # Override REF IO capability if supported.
        set_io_capability(self.ref, ref_io_capability)

        # Connection/pairing task.
        async def connect_and_pair() -> Tuple[SecureResponse, WaitSecurityResponse]:
            dut_ref, ref_dut = await make_classic_connection(self.dut, self.ref)
            if ref_role is not None:
                await role_switch(self.ref, ref_dut, ref_role)
            return await authenticate(self.ref, ref_dut, self.dut, dut_ref, LEVEL2)

        # Handle pairing.
        initiator_pairing, acceptor_pairing = await handle_pairing(
            self.dut,
            self.ref,
            connect_and_pair,
        )

        # Assert success.
        assert_equal(initiator_pairing.result_variant(), 'success')
        assert_equal(acceptor_pairing.result_variant(), 'success')

    @avatar.parameterized(*itertools.product(ALL_IO_CAPABILITIES, ALL_ROLES))  # type: ignore[misc]
    @avatar.asynchronous
    async def test_success_accept_connection_initiate_pairing(
        self,
        ref_io_capability: Optional[PairingDelegate.IoCapability],
        ref_role: Optional[int],
    ) -> None:
        # Override REF IO capability if supported.
        set_io_capability(self.ref, ref_io_capability)

        # Connection/pairing task.
        async def connect_and_pair() -> Tuple[SecureResponse, WaitSecurityResponse]:
            ref_dut, dut_ref = await make_classic_connection(self.ref, self.dut)
            if ref_role is not None:
                await role_switch(self.ref, ref_dut, ref_role)
            return await authenticate(self.dut, dut_ref, self.ref, ref_dut, LEVEL2)

        # Handle pairing.
        initiator_pairing, acceptor_pairing = await handle_pairing(
            self.dut,
            self.ref,
            connect_and_pair,
        )

        # Assert success.
        assert_equal(initiator_pairing.result_variant(), 'success')
        assert_equal(acceptor_pairing.result_variant(), 'success')

    @avatar.parameterized(*itertools.product(ALL_IO_CAPABILITIES, ALL_ROLES))  # type: ignore[misc]
    @avatar.asynchronous
    async def test_success_accept_connection_accept_pairing(
        self,
        ref_io_capability: Optional[PairingDelegate.IoCapability],
        ref_role: Optional[int],
    ) -> None:
        # Override REF IO capability if supported.
        set_io_capability(self.ref, ref_io_capability)

        # Connection/pairing task.
        async def connect_and_pair() -> Tuple[SecureResponse, WaitSecurityResponse]:
            ref_dut, dut_ref = await make_classic_connection(self.ref, self.dut)
            if ref_role is not None:
                await role_switch(self.ref, ref_dut, ref_role)
            return await authenticate(self.ref, ref_dut, self.dut, dut_ref, LEVEL2)

        # Handle pairing.
        initiator_pairing, acceptor_pairing = await handle_pairing(
            self.dut,
            self.ref,
            connect_and_pair,
        )

        # Assert success.
        assert_equal(initiator_pairing.result_variant(), 'success')
        assert_equal(acceptor_pairing.result_variant(), 'success')


def set_io_capability(device: PandoraDevice, io_capability: Optional[PairingDelegate.IoCapability]) -> None:
    if io_capability is None:
        return
    if isinstance(device, BumblePandoraDevice):
        # Override Bumble reference device default IO capability.
        device.server_config.io_capability = io_capability
    else:
        raise signals.TestSkip('Unable to override IO capability on non Bumble device.')


# Connection task.
async def make_classic_connection(initiator: PandoraDevice, acceptor: PandoraDevice) -> Tuple[Connection, Connection]:
    '''Connect two device and returns both connection tokens.'''

    (connect, wait_connection) = await asyncio.gather(
        initiator.aio.host.Connect(address=acceptor.address),
        acceptor.aio.host.WaitConnection(address=initiator.address),
    )

    # Assert connection are successful.
    assert_equal(connect.result_variant(), 'connection')
    assert_equal(wait_connection.result_variant(), 'connection')
    assert_is_not_none(connect.connection)
    assert_is_not_none(wait_connection.connection)
    assert connect.connection and wait_connection.connection

    # Returns connections.
    return connect.connection, wait_connection.connection


# Pairing task.
async def authenticate(
    initiator: PandoraDevice,
    initiator_connection: Connection,
    acceptor: PandoraDevice,
    acceptor_connection: Connection,
    security_level: SecurityLevel,
) -> Tuple[SecureResponse, WaitSecurityResponse]:
    '''Pair two device and returns both pairing responses.'''

    return await asyncio.gather(
        initiator.aio.security.Secure(connection=initiator_connection, classic=security_level),
        acceptor.aio.security.WaitSecurity(connection=acceptor_connection, classic=security_level),
    )


# Role switch task.
async def role_switch(
    device: PandoraDevice,
    connection: Connection,
    role: int,
) -> None:
    '''Switch role if supported.'''

    if not isinstance(device, BumblePandoraDevice):
        return

    connection_handle = int.from_bytes(connection.cookie.value, 'big')
    bumble_connection = device.device.lookup_connection(connection_handle)
    assert_is_not_none(bumble_connection)
    assert bumble_connection

    if bumble_connection.role != role:
        device.log.info(f"Role switch to: {'`CENTRAL`' if role == HCI_CENTRAL_ROLE else '`PERIPHERAL`'}")
        await bumble_connection.switch_role(role)


# Handle pairing events task.
async def handle_pairing(
    dut: PandoraDevice,
    ref: PandoraDevice,
    connect_and_pair: Callable[[], Coroutine[None, None, Tuple[SecureResponse, WaitSecurityResponse]]],
    confirm: Callable[[bool], bool] = lambda x: x,
    passkey: Callable[[int], int] = lambda x: x,
) -> Tuple[SecureResponse, WaitSecurityResponse]:

    # Listen for pairing event on bot DUT and REF.
    dut_pairing, ref_pairing = dut.aio.security.OnPairing(), ref.aio.security.OnPairing()

    # Start connection/pairing.
    connect_and_pair_task = asyncio.create_task(connect_and_pair())

    try:
        dut_ev = await asyncio.wait_for(anext(dut_pairing), timeout=25.0)
        dut.log.info(f'DUT pairing event: {dut_ev.method_variant()}')

        ref_ev = await asyncio.wait_for(anext(ref_pairing), timeout=3.0)
        ref.log.info(f'REF pairing event: {ref_ev.method_variant()}')

        if dut_ev.method_variant() in ('numeric_comparison', 'just_works'):
            assert_in(ref_ev.method_variant(), ('numeric_comparison', 'just_works'))
            confirm_res = True
            if dut_ev.method_variant() == 'numeric_comparison' and ref_ev.method_variant() == 'numeric_comparison':
                confirm_res = ref_ev.numeric_comparison == dut_ev.numeric_comparison
            confirm_res = confirm(confirm_res)
            dut_pairing.send_nowait(PairingEventAnswer(event=dut_ev, confirm=confirm_res))
            ref_pairing.send_nowait(PairingEventAnswer(event=ref_ev, confirm=confirm_res))

        elif dut_ev.method_variant() == 'passkey_entry_notification':
            assert_equal(ref_ev.method_variant(), 'passkey_entry_request')
            assert_is_not_none(dut_ev.passkey_entry_notification)
            assert dut_ev.passkey_entry_notification is not None
            passkey_res = passkey(dut_ev.passkey_entry_notification)
            ref_pairing.send_nowait(PairingEventAnswer(event=ref_ev, passkey=passkey_res))

        elif dut_ev.method_variant() == 'passkey_entry_request':
            assert_equal(ref_ev.method_variant(), 'passkey_entry_notification')
            assert_is_not_none(ref_ev.passkey_entry_notification)
            assert ref_ev.passkey_entry_notification is not None
            passkey_res = passkey(ref_ev.passkey_entry_notification)
            dut_pairing.send_nowait(PairingEventAnswer(event=dut_ev, passkey=passkey_res))

        else:
            fail("")

    except (asyncio.CancelledError, asyncio.TimeoutError):
        logging.exception('Pairing timed-out.')

    finally:

        try:
            (secure, wait_security) = await asyncio.wait_for(connect_and_pair_task, 15.0)
            logging.info(f'Pairing result: {secure.result_variant()}/{wait_security.result_variant()}')
            return secure, wait_security

        finally:
            dut_pairing.cancel()
            ref_pairing.cancel()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()  # type: ignore
