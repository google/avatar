# Copyright 2022 Google LLC
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
import grpc
import logging

from avatar import BumblePandoraDevice, PandoraDevice, PandoraDevices
from bumble.pairing import PairingDelegate
from concurrent import futures
from contextlib import suppress
from mobly import base_test, signals, test_runner
from mobly.asserts import assert_equal  # type: ignore
from mobly.asserts import assert_in  # type: ignore
from mobly.asserts import assert_is_none  # type: ignore
from mobly.asserts import assert_is_not_none  # type: ignore
from mobly.asserts import explicit_pass, fail  # type: ignore
from pandora.host_pb2 import (
    DISCOVERABLE_GENERAL,
    DISCOVERABLE_LIMITED,
    NOT_DISCOVERABLE,
    PUBLIC,
    RANDOM,
    DataTypes,
    DiscoverabilityMode,
    OwnAddressType,
)
from pandora.security_pb2 import LE_LEVEL3, LEVEL2, PairingEventAnswer
from typing import NoReturn, Optional


class ExampleTest(base_test.BaseTestClass):  # type: ignore[misc]
    devices: Optional[PandoraDevices] = None

    # pandora devices.
    dut: PandoraDevice
    ref: PandoraDevice

    def setup_class(self) -> None:
        self.devices = PandoraDevices(self)
        self.dut, self.ref, *_ = self.devices

        # Enable BR/EDR mode for Bumble devices.
        for device in self.devices:
            if isinstance(device, BumblePandoraDevice):
                device.config.setdefault('classic_enabled', True)

    def teardown_class(self) -> None:
        if self.devices:
            self.devices.stop_all()

    @avatar.asynchronous
    async def setup_test(self) -> None:  # pytype: disable=wrong-arg-types
        await asyncio.gather(self.dut.reset(), self.ref.reset())

    def test_print_addresses(self) -> None:
        dut_address = self.dut.address
        self.dut.log.info(f'Address: {dut_address}')
        ref_address = self.ref.address
        self.ref.log.info(f'Address: {ref_address}')

    def test_classic_connect(self) -> None:
        dut_address = self.dut.address
        self.dut.log.info(f'Address: {dut_address}')
        connection = self.ref.host.Connect(address=dut_address).connection
        assert_is_not_none(connection)
        assert connection
        self.ref.log.info(f'Connected with: {dut_address}')
        self.ref.host.Disconnect(connection=connection)

    # Using this decorator allow us to write one `test_le_connect`, and
    # run it multiple time with different parameters.
    # Here we check that no matter the address type we use for both sides
    # the connection still complete.
    @avatar.parameterized(
        (RANDOM, RANDOM),
        (RANDOM, PUBLIC),
    )  # type: ignore[misc]
    def test_le_connect(self, dut_address_type: OwnAddressType, ref_address_type: OwnAddressType) -> None:
        if not isinstance(self.ref, BumblePandoraDevice):
            raise signals.TestSkip('Test require Bumble as reference device')

        advertisement = self.ref.host.Advertise(legacy=True, connectable=True, own_address_type=ref_address_type)
        scan = self.dut.host.Scan(own_address_type=dut_address_type)
        if ref_address_type == PUBLIC:
            scan_response = next((x for x in scan if x.public == self.ref.address))
            dut_ref = self.dut.host.ConnectLE(
                public=scan_response.public,
                own_address_type=dut_address_type,
            ).connection
        else:
            scan_response = next((x for x in scan if x.random == self.ref.random_address))
            dut_ref = self.dut.host.ConnectLE(
                random=scan_response.random,
                own_address_type=dut_address_type,
            ).connection
        scan.cancel()
        _ = next(advertisement).connection
        advertisement.cancel()
        assert dut_ref
        self.dut.host.Disconnect(connection=dut_ref)

    @avatar.rpc_except(
        {
            # This test should reach the `Inquiry` timeout.
            grpc.StatusCode.DEADLINE_EXCEEDED: lambda e: explicit_pass(e.details()),
        }
    )
    def test_not_discoverable(self) -> None:
        self.dut.host.SetDiscoverabilityMode(mode=NOT_DISCOVERABLE)
        inquiry = self.ref.host.Inquiry(timeout=3.0)
        try:
            assert_is_none(next((x for x in inquiry if x.address == self.dut.address), None))
        finally:
            inquiry.cancel()

    @avatar.parameterized(
        (DISCOVERABLE_LIMITED,),
        (DISCOVERABLE_GENERAL,),
    )  # type: ignore[misc]
    def test_discoverable(self, mode: DiscoverabilityMode) -> None:
        self.dut.host.SetDiscoverabilityMode(mode=mode)
        inquiry = self.ref.host.Inquiry(timeout=15.0)
        try:
            assert_is_not_none(next((x for x in inquiry if x.address == self.dut.address), None))
        finally:
            inquiry.cancel()

    @avatar.asynchronous
    async def test_wait_connection(self) -> None:  # pytype: disable=wrong-arg-types
        dut_ref_co = self.dut.aio.host.WaitConnection(address=self.ref.address)
        ref_dut = await self.ref.aio.host.Connect(address=self.dut.address)
        dut_ref = await dut_ref_co
        assert_is_not_none(ref_dut.connection)
        assert_is_not_none(dut_ref.connection)
        assert ref_dut.connection
        await self.ref.aio.host.Disconnect(connection=ref_dut.connection)

    def test_scan_response_data(self) -> None:
        advertisement = self.dut.host.Advertise(
            legacy=True,
            data=DataTypes(
                complete_service_class_uuids16=['FDF0'],
            ),
            scan_response_data=DataTypes(
                include_class_of_device=True,
            ),
        )

        scan = self.ref.host.Scan()
        scan_response = next((x for x in scan if x.public == self.dut.address))

        scan.cancel()
        advertisement.cancel()

        assert_equal(type(scan_response.data.class_of_device), int)
        assert_equal(type(scan_response.data.complete_service_class_uuids16[0]), str)

    async def handle_pairing_events(self) -> NoReturn:
        ref_pairing_stream = self.ref.aio.security.OnPairing()
        dut_pairing_stream = self.dut.aio.security.OnPairing()

        try:
            while True:
                ref_pairing_event, dut_pairing_event = await asyncio.gather(
                    anext(ref_pairing_stream),  # pytype: disable=name-error
                    anext(dut_pairing_stream),  # pytype: disable=name-error
                )

                if dut_pairing_event.method_variant() in ('numeric_comparison', 'just_works'):
                    assert_in(ref_pairing_event.method_variant(), ('numeric_comparison', 'just_works'))
                    dut_pairing_stream.send_nowait(
                        PairingEventAnswer(
                            event=dut_pairing_event,
                            confirm=True,
                        )
                    )
                    ref_pairing_stream.send_nowait(
                        PairingEventAnswer(
                            event=ref_pairing_event,
                            confirm=True,
                        )
                    )
                elif dut_pairing_event.method_variant() == 'passkey_entry_notification':
                    assert_equal(ref_pairing_event.method_variant(), 'passkey_entry_request')
                    ref_pairing_stream.send_nowait(
                        PairingEventAnswer(
                            event=ref_pairing_event,
                            passkey=dut_pairing_event.passkey_entry_notification,
                        )
                    )
                elif dut_pairing_event.method_variant() == 'passkey_entry_request':
                    assert_equal(ref_pairing_event.method_variant(), 'passkey_entry_notification')
                    dut_pairing_stream.send_nowait(
                        PairingEventAnswer(
                            event=dut_pairing_event,
                            passkey=ref_pairing_event.passkey_entry_notification,
                        )
                    )
                else:
                    fail("unreachable")

        finally:
            ref_pairing_stream.cancel()
            dut_pairing_stream.cancel()

    @avatar.parameterized(
        (PairingDelegate.NO_OUTPUT_NO_INPUT,),
        (PairingDelegate.KEYBOARD_INPUT_ONLY,),
        (PairingDelegate.DISPLAY_OUTPUT_ONLY,),
        (PairingDelegate.DISPLAY_OUTPUT_AND_YES_NO_INPUT,),
        (PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT,),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_classic_pairing(
        self, ref_io_capability: PairingDelegate.IoCapability
    ) -> None:  # pytype: disable=wrong-arg-types
        if not isinstance(self.ref, BumblePandoraDevice):
            raise signals.TestSkip('Test require Bumble as reference device(s)')

        # override reference device IO capability
        self.ref.server_config.io_capability = ref_io_capability

        pairing = asyncio.create_task(self.handle_pairing_events())
        (dut_ref_res, ref_dut_res) = await asyncio.gather(
            self.dut.aio.host.WaitConnection(address=self.ref.address),
            self.ref.aio.host.Connect(address=self.dut.address),
        )

        assert_equal(ref_dut_res.result_variant(), 'connection')
        assert_equal(dut_ref_res.result_variant(), 'connection')
        ref_dut = ref_dut_res.connection
        dut_ref = dut_ref_res.connection
        assert_is_not_none(ref_dut)
        assert_is_not_none(dut_ref)
        assert ref_dut and dut_ref

        (secure, wait_security) = await asyncio.gather(
            self.ref.aio.security.Secure(connection=ref_dut, classic=LEVEL2),
            self.dut.aio.security.WaitSecurity(connection=dut_ref, classic=LEVEL2),
        )

        pairing.cancel()
        with suppress(asyncio.CancelledError, futures.CancelledError):
            await pairing

        assert_equal(secure.result_variant(), 'success')
        assert_equal(wait_security.result_variant(), 'success')

        await asyncio.gather(
            self.dut.aio.host.Disconnect(connection=dut_ref),
            self.ref.aio.host.WaitDisconnection(connection=ref_dut),
        )

    @avatar.parameterized(
        (RANDOM, RANDOM, PairingDelegate.NO_OUTPUT_NO_INPUT),
        (RANDOM, RANDOM, PairingDelegate.KEYBOARD_INPUT_ONLY),
        (RANDOM, RANDOM, PairingDelegate.DISPLAY_OUTPUT_ONLY),
        (RANDOM, RANDOM, PairingDelegate.DISPLAY_OUTPUT_AND_YES_NO_INPUT),
        (RANDOM, RANDOM, PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT),
        (RANDOM, PUBLIC, PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_le_pairing(  # pytype: disable=wrong-arg-types
        self,
        dut_address_type: OwnAddressType,
        ref_address_type: OwnAddressType,
        ref_io_capability: PairingDelegate.IoCapability,
    ) -> None:
        if not isinstance(self.ref, BumblePandoraDevice):
            raise signals.TestSkip('Test require Bumble as reference device(s)')

        # override reference device IO capability
        self.ref.server_config.io_capability = ref_io_capability

        advertisement = self.dut.aio.host.Advertise(
            legacy=True,
            connectable=True,
            own_address_type=dut_address_type,
            data=DataTypes(manufacturer_specific_data=b'pause cafe'),
        )

        scan = self.ref.aio.host.Scan(own_address_type=ref_address_type)
        dut = await anext(
            (x async for x in scan if b'pause cafe' in x.data.manufacturer_specific_data)
        )  # pytype: disable=name-error
        scan.cancel()

        pairing = asyncio.create_task(self.handle_pairing_events())
        (ref_dut_res, dut_ref_res) = await asyncio.gather(
            self.ref.aio.host.ConnectLE(own_address_type=ref_address_type, **dut.address_asdict()),
            anext(aiter(advertisement)),  # pytype: disable=name-error
        )

        advertisement.cancel()
        ref_dut, dut_ref = ref_dut_res.connection, dut_ref_res.connection
        assert_is_not_none(ref_dut)
        assert ref_dut

        (secure, wait_security) = await asyncio.gather(
            self.ref.aio.security.Secure(connection=ref_dut, le=LE_LEVEL3),
            self.dut.aio.security.WaitSecurity(connection=dut_ref, le=LE_LEVEL3),
        )

        pairing.cancel()
        with suppress(asyncio.CancelledError, futures.CancelledError):
            await pairing

        assert_equal(secure.result_variant(), 'success')
        assert_equal(wait_security.result_variant(), 'success')

        await asyncio.gather(
            self.dut.aio.host.Disconnect(connection=dut_ref),
            self.ref.aio.host.WaitDisconnection(connection=ref_dut),
        )


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()  # type: ignore
