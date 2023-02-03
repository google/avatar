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
import grpc
import logging

from avatar import PandoraDevices, parameterized
from avatar.aio import AsyncQueue, asynchronous
from avatar.pandora_client import Address, BumblePandoraClient, PandoraClient
from bumble.smp import PairingDelegate
from concurrent import futures
from contextlib import suppress
from mobly import base_test, test_runner
from mobly.asserts import assert_equal  # type: ignore
from mobly.asserts import assert_in  # type: ignore
from mobly.asserts import assert_is_none  # type: ignore
from mobly.asserts import assert_is_not_none  # type: ignore
from mobly.asserts import fail  # type: ignore
from pandora.host_grpc import ConnectLERequestDict, DataTypes, DiscoverabilityMode, OwnAddressType
from pandora.security_grpc import DeleteBondRequestDict, LESecurityLevel, PairingEventAnswer, SecurityLevel
from typing import NoReturn, Optional


class ExampleTest(base_test.BaseTestClass):  # type: ignore[misc]
    devices: Optional[PandoraDevices] = None

    # pandora devices.
    dut: PandoraClient
    ref: BumblePandoraClient

    def setup_class(self) -> None:
        self.devices = PandoraDevices(self)
        dut, ref = self.devices
        assert isinstance(ref, BumblePandoraClient)
        self.dut, self.ref = dut, ref

    def teardown_class(self) -> None:
        if self.devices:
            self.devices.stop_all()

    @asynchronous
    async def setup_test(self) -> None:
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
        assert connection
        dut_name = self.ref.host.GetRemoteName(connection=connection).name
        self.ref.log.info(f'Connected with: "{dut_name}" {dut_address}')
        self.ref.host.Disconnect(connection=connection)

    # Using this decorator allow us to write one `test_le_connect`, and
    # run it multiple time with different parameters.
    # Here we check that no matter the address type we use for both sides
    # the connection still complete.
    @parameterized(
        (OwnAddressType.RANDOM, OwnAddressType.RANDOM),
        (OwnAddressType.RANDOM, OwnAddressType.PUBLIC),
    )  # type: ignore[misc]
    def test_le_connect(self, dut_address_type: OwnAddressType, ref_address_type: OwnAddressType) -> None:
        self.ref.host.StartAdvertising(legacy=True, connectable=True, own_address_type=ref_address_type)
        peers = self.dut.host.Scan(own_address_type=dut_address_type)
        if ref_address_type == OwnAddressType.PUBLIC:
            scan_response = next((x for x in peers if x.public == self.ref.address))
            dut_ref = self.dut.host.ConnectLE(
                public=scan_response.public,
                own_address_type=dut_address_type,
            ).connection
        else:
            scan_response = next((x for x in peers if x.random == self.ref.random_address))
            dut_ref = self.dut.host.ConnectLE(
                random=scan_response.random,
                own_address_type=dut_address_type,
            ).connection
        peers.cancel()
        assert dut_ref
        self.dut.host.Disconnect(connection=dut_ref)

    def test_not_discoverable(self) -> None:
        self.dut.host.SetDiscoverabilityMode(mode=DiscoverabilityMode.NOT_DISCOVERABLE)
        peers = self.ref.host.Inquiry(timeout=3.0)
        try:
            assert_is_none(next((x for x in peers if x.address == self.dut.address), None))
        except grpc.RpcError as e:
            # No peers found; StartInquiry times out
            assert_equal(e.code(), grpc.StatusCode.DEADLINE_EXCEEDED)  # type: ignore
        finally:
            peers.cancel()

    @parameterized(
        (DiscoverabilityMode.DISCOVERABLE_LIMITED,),
        (DiscoverabilityMode.DISCOVERABLE_GENERAL,),
    )  # type: ignore[misc]
    def test_discoverable(self, mode: DiscoverabilityMode) -> None:
        self.dut.host.SetDiscoverabilityMode(mode=mode)
        peers = self.ref.host.Inquiry(timeout=15.0)
        try:
            assert_is_not_none(next((x for x in peers if x.address == self.dut.address), None))
        finally:
            peers.cancel()

    @asynchronous
    async def test_wait_connection(self) -> None:
        dut_ref_co = self.dut.aio.host.WaitConnection(address=self.ref.address)
        ref_dut = await self.ref.aio.host.Connect(address=self.dut.address)
        dut_ref = await dut_ref_co
        assert_is_not_none(ref_dut.connection)
        assert_is_not_none(dut_ref.connection)
        assert ref_dut.connection
        await self.ref.aio.host.Disconnect(connection=ref_dut.connection)

    @asynchronous
    async def test_wait_any_connection(self) -> None:
        dut_ref_co = self.dut.aio.host.WaitConnection()
        ref_dut = await self.ref.aio.host.Connect(address=self.dut.address)
        dut_ref = await dut_ref_co
        assert_is_not_none(ref_dut.connection)
        assert_is_not_none(dut_ref.connection)
        assert ref_dut.connection
        await self.ref.aio.host.Disconnect(connection=ref_dut.connection)

    def test_scan_response_data(self) -> None:
        self.dut.host.StartAdvertising(
            legacy=True,
            data=DataTypes(
                complete_service_class_uuids16=['FDF0'],
            ),
            scan_response_data=DataTypes(
                include_class_of_device=True,
            ),
        )

        peers = self.ref.host.Scan()
        scan_response = next((x for x in peers if x.public == self.dut.address))
        peers.cancel()

        assert_equal(type(scan_response.data.class_of_device), int)
        assert_equal(type(scan_response.data.complete_service_class_uuids16[0]), str)

    async def handle_pairing_events(self) -> NoReturn:
        ref_answer_queue: AsyncQueue[PairingEventAnswer] = AsyncQueue()
        dut_answer_queue: AsyncQueue[PairingEventAnswer] = AsyncQueue()

        on_ref_pairing = self.ref.aio.security.OnPairing(ref_answer_queue)
        on_dut_pairing = self.dut.aio.security.OnPairing(dut_answer_queue)

        try:
            on_ref_pairing_events = aiter(on_ref_pairing)
            on_dut_pairing_events = aiter(on_dut_pairing)

            while True:
                ref_pairing_event, dut_pairing_event = await asyncio.gather(
                    anext(on_ref_pairing_events),
                    anext(on_dut_pairing_events),
                )

                if dut_pairing_event.WhichOneof('method') in ('numeric_comparison', 'just_works'):
                    assert_in(ref_pairing_event.WhichOneof('method'), ('numeric_comparison', 'just_works'))
                    dut_answer_queue.put_nowait(
                        PairingEventAnswer(
                            event=dut_pairing_event,
                            confirm=True,
                        )
                    )
                    ref_answer_queue.put_nowait(
                        PairingEventAnswer(
                            event=ref_pairing_event,
                            confirm=True,
                        )
                    )
                elif dut_pairing_event.WhichOneof('method') == 'passkey_entry_notification':
                    assert_equal(ref_pairing_event.WhichOneof('method'), 'passkey_entry_request')
                    ref_answer_queue.put_nowait(
                        PairingEventAnswer(
                            event=ref_pairing_event,
                            passkey=dut_pairing_event.passkey_entry_notification,
                        )
                    )
                elif dut_pairing_event.WhichOneof('method') == 'passkey_entry_request':
                    assert_equal(ref_pairing_event.WhichOneof('method'), 'passkey_entry_notification')
                    dut_answer_queue.put_nowait(
                        PairingEventAnswer(
                            event=dut_pairing_event,
                            passkey=ref_pairing_event.passkey_entry_notification,
                        )
                    )
                else:
                    fail("unreachable")

        finally:
            on_ref_pairing.cancel()
            on_dut_pairing.cancel()

    @parameterized(
        (PairingDelegate.NO_OUTPUT_NO_INPUT,),
        (PairingDelegate.KEYBOARD_INPUT_ONLY,),
        (PairingDelegate.DISPLAY_OUTPUT_ONLY,),
        (PairingDelegate.DISPLAY_OUTPUT_AND_YES_NO_INPUT,),
        (PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT,),
    )  # type: ignore[misc]
    @asynchronous
    async def test_classic_pairing(self, ref_io_capability: int) -> None:
        # override reference device IO capability
        setattr(self.ref.device, 'io_capability', ref_io_capability)

        await self.ref.aio.security_storage.DeleteBond(public=self.dut.address)

        pairing = asyncio.create_task(self.handle_pairing_events())
        (dut_ref_res, ref_dut_res) = await asyncio.gather(
            self.dut.aio.host.WaitConnection(address=self.ref.address),
            self.ref.aio.host.Connect(address=self.dut.address),
        )

        assert_equal(ref_dut_res.WhichOneof('result'), 'connection')
        assert_equal(dut_ref_res.WhichOneof('result'), 'connection')
        ref_dut = ref_dut_res.connection
        dut_ref = dut_ref_res.connection
        assert ref_dut and dut_ref

        (secure, wait_security) = await asyncio.gather(
            self.ref.aio.security.Secure(connection=ref_dut, classic=SecurityLevel.LEVEL2),
            self.dut.aio.security.WaitSecurity(connection=dut_ref, classic=SecurityLevel.LEVEL2),
        )

        pairing.cancel()
        with suppress(asyncio.CancelledError, futures.CancelledError):
            await pairing

        assert_equal(secure.WhichOneof('result'), 'success')
        assert_equal(wait_security.WhichOneof('result'), 'success')

        await asyncio.gather(
            self.dut.aio.host.Disconnect(connection=dut_ref),
            self.ref.aio.host.WaitDisconnection(connection=ref_dut),
        )

    @parameterized(
        (OwnAddressType.RANDOM, OwnAddressType.RANDOM, PairingDelegate.NO_OUTPUT_NO_INPUT),
        (OwnAddressType.RANDOM, OwnAddressType.RANDOM, PairingDelegate.KEYBOARD_INPUT_ONLY),
        (OwnAddressType.RANDOM, OwnAddressType.RANDOM, PairingDelegate.DISPLAY_OUTPUT_ONLY),
        (OwnAddressType.RANDOM, OwnAddressType.RANDOM, PairingDelegate.DISPLAY_OUTPUT_AND_YES_NO_INPUT),
        (OwnAddressType.RANDOM, OwnAddressType.RANDOM, PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT),
        (OwnAddressType.RANDOM, OwnAddressType.PUBLIC, PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT),
    )  # type: ignore[misc]
    @asynchronous
    async def test_le_pairing(
        self, dut_address_type: OwnAddressType, ref_address_type: OwnAddressType, ref_io_capability: int
    ) -> None:
        # override reference device IO capability
        setattr(self.ref.device, 'io_capability', ref_io_capability)

        ref_address: DeleteBondRequestDict
        if ref_address_type in (OwnAddressType.PUBLIC, OwnAddressType.RESOLVABLE_OR_PUBLIC):
            ref_address = {'public': self.ref.address}
        else:
            ref_address = {'random': self.ref.random_address}

        await self.dut.aio.security_storage.DeleteBond(**ref_address)
        await self.dut.aio.host.StartAdvertising(
            legacy=True,
            connectable=True,
            own_address_type=dut_address_type,
            data=DataTypes(manufacturer_specific_data=b'pause cafe'),
        )

        dut = None
        peers = self.ref.aio.host.Scan(own_address_type=ref_address_type)
        async for peer in aiter(peers):
            if b'pause cafe' in peer.data.manufacturer_specific_data:
                dut = peer
                break
        peers.cancel()
        assert_is_not_none(dut)
        assert dut
        assert dut.address_variant
        assert dut.address

        ref_dut_req = ConnectLERequestDict(own_address_type=ref_address_type)
        ref_dut_req[dut.address_variant] = Address(dut.address)

        pairing = asyncio.create_task(self.handle_pairing_events())
        (dut_ref_res, ref_dut_res) = await asyncio.gather(
            self.dut.aio.host.WaitLEConnection(**ref_address),
            self.ref.aio.host.ConnectLE(**ref_dut_req),
        )

        assert_equal(ref_dut_res.result_variant, 'connection')
        assert_equal(dut_ref_res.result_variant, 'connection')
        ref_dut = ref_dut_res.connection
        dut_ref = dut_ref_res.connection
        assert ref_dut and dut_ref

        (secure, wait_security) = await asyncio.gather(
            self.ref.aio.security.Secure(connection=ref_dut, le=LESecurityLevel.LE_LEVEL3),
            self.dut.aio.security.WaitSecurity(connection=dut_ref, le=LESecurityLevel.LE_LEVEL3),
        )

        pairing.cancel()
        with suppress(asyncio.CancelledError, futures.CancelledError):
            await pairing

        assert_equal(secure.WhichOneof('result'), 'success')
        assert_equal(wait_security.WhichOneof('result'), 'success')

        await asyncio.gather(
            self.dut.aio.host.Disconnect(connection=dut_ref),
            self.ref.aio.host.WaitDisconnection(connection=ref_dut),
        )


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()  # type: ignore
