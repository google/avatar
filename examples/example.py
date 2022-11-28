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

import avatar
import asyncio
import logging
import grpc

from concurrent import futures
from contextlib import suppress

from mobly import test_runner, base_test

from bumble.smp import PairingDelegate

from avatar.utils import Address, AsyncQueue
from avatar.controllers import pandora_device
from pandora.host_pb2 import (
    DiscoverabilityMode, DataTypes, OwnAddressType
)
from pandora.security_pb2 import (
    PairingEventAnswer, SecurityLevel, LESecurityLevel
)


class ExampleTest(base_test.BaseTestClass):
    def setup_class(self):
        self.pandora_devices = self.register_controller(pandora_device)
        self.dut: pandora_device.PandoraDevice = self.pandora_devices[0]
        self.ref: pandora_device.BumblePandoraDevice = self.pandora_devices[1]

    @avatar.asynchronous
    async def setup_test(self):
        async def reset(device: pandora_device.PandoraDevice):
            await device.host.FactoryReset()
            device.address = (await device.host.ReadLocalAddress(wait_for_ready=True)).address

        await asyncio.gather(reset(self.dut), reset(self.ref))

    def test_print_addresses(self):
        dut_address = self.dut.address
        self.dut.log.info(f'Address: {dut_address}')
        ref_address = self.ref.address
        self.ref.log.info(f'Address: {ref_address}')

    def test_get_remote_name(self):
        dut_name = self.ref.host.GetRemoteName(address=self.dut.address).name
        self.ref.log.info(f'DUT remote name: {dut_name}')
        ref_name = self.dut.host.GetRemoteName(address=self.ref.address).name
        self.dut.log.info(f'REF remote name: {ref_name}')

    def test_classic_connect(self):
        dut_address = self.dut.address
        self.dut.log.info(f'Address: {dut_address}')
        connection = self.ref.host.Connect(address=dut_address).connection
        dut_name = self.ref.host.GetRemoteName(connection=connection).name
        self.ref.log.info(f'Connected with: "{dut_name}" {dut_address}')
        self.ref.host.Disconnect(connection=connection)

    # Using this decorator allow us to write one `test_le_connect`, and
    # run it multiple time with different parameters.
    # Here we check that no matter the address type we use for both sides
    # the connection still complete.
    @avatar.parameterized([
        (OwnAddressType.PUBLIC, OwnAddressType.PUBLIC),
        (OwnAddressType.PUBLIC, OwnAddressType.RANDOM),
        (OwnAddressType.RANDOM, OwnAddressType.RANDOM),
        (OwnAddressType.RANDOM, OwnAddressType.PUBLIC),
    ])
    def test_le_connect(self, dut_address_type: OwnAddressType, ref_address_type: OwnAddressType):
        self.ref.host.StartAdvertising(legacy=True, connectable=True, own_address_type=ref_address_type)
        peers = self.dut.host.Scan(own_address_type=dut_address_type)
        if ref_address_type == OwnAddressType.PUBLIC:
            scan_response = next((x for x in peers if x.public == self.ref.address))
            connection = self.dut.host.ConnectLE(public=scan_response.public, own_address_type=dut_address_type).connection
        else:
            scan_response = next((x for x in peers if x.random == Address(self.ref.device.random_address)))
            connection = self.dut.host.ConnectLE(random=scan_response.random, own_address_type=dut_address_type).connection
        self.dut.host.Disconnect(connection=connection)

    def test_not_discoverable(self):
        self.dut.host.SetDiscoverabilityMode(mode=DiscoverabilityMode.NOT_DISCOVERABLE)
        peers = self.ref.host.Inquiry(timeout=3.0)
        try:
            assert not next((x for x in peers if x.address == self.dut.address), None)
        except grpc.RpcError as e:
            assert e.code() == grpc.StatusCode.DEADLINE_EXCEEDED

    @avatar.parameterized([
        (DiscoverabilityMode.DISCOVERABLE_LIMITED, ),
        (DiscoverabilityMode.DISCOVERABLE_GENERAL, ),
    ])
    def test_discoverable(self, mode):
        self.dut.host.SetDiscoverabilityMode(mode=mode)
        peers = self.ref.host.Inquiry(timeout=15.0)
        assert next((x for x in peers if x.address == self.dut.address), None)

    @avatar.asynchronous
    async def test_wait_connection(self):
        dut_ref = self.dut.host.WaitConnection(address=self.ref.address)
        ref_dut = await self.ref.host.Connect(address=self.dut.address)
        dut_ref = await dut_ref
        assert ref_dut.connection and dut_ref.connection

    @avatar.asynchronous
    async def test_wait_any_connection(self):
        dut_ref = self.dut.host.WaitConnection()
        ref_dut = await self.ref.host.Connect(address=self.dut.address)
        dut_ref = await dut_ref
        assert ref_dut.connection and dut_ref.connection

    def test_scan_response_data(self):
        self.dut.host.StartAdvertising(
            legacy=True,
            data=DataTypes(
                include_shortened_local_name=True,
                tx_power_level=42,
                incomplete_service_class_uuids16=['FDF0']
            ),
            scan_response_data=DataTypes(include_complete_local_name=True, include_class_of_device=True)
        )

        peers = self.ref.host.Scan()
        scan_response = next((x for x in peers if x.public == self.dut.address))
        assert type(scan_response.data.complete_local_name) == str
        assert type(scan_response.data.shortened_local_name) == str
        assert type(scan_response.data.class_of_device) == int
        assert type(scan_response.data.incomplete_service_class_uuids16[0]) == str
        assert scan_response.data.tx_power_level == 42

    @avatar.parameterized([
        (PairingDelegate.NO_OUTPUT_NO_INPUT, ),
        (PairingDelegate.KEYBOARD_INPUT_ONLY, ),
        (PairingDelegate.DISPLAY_OUTPUT_ONLY, ),
        (PairingDelegate.DISPLAY_OUTPUT_AND_YES_NO_INPUT, ),
        (PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT, ),
    ])
    @avatar.asynchronous
    async def test_classic_pairing(self, ref_io_capability):
        # override reference device IO capability
        self.ref.device.io_capability = ref_io_capability

        await self.ref.security_storage.DeleteBond(public=self.dut.address)

        async def handle_pairing_events():
            on_ref_pairing = self.ref.security.OnPairing((ref_answer_queue := AsyncQueue()))
            on_dut_pairing = self.dut.security.OnPairing((dut_answer_queue := AsyncQueue()))

            try:
                while True:
                    dut_pairing_event = await anext(aiter(on_dut_pairing))
                    ref_pairing_event = await anext(aiter(on_ref_pairing))

                    if dut_pairing_event.WhichOneof('method') in ('numeric_comparison', 'just_works'):
                        assert ref_pairing_event.WhichOneof('method') in ('numeric_comparison', 'just_works')
                        dut_answer_queue.put_nowait(PairingEventAnswer(
                            event=dut_pairing_event,
                            confirm=True,
                        ))
                        ref_answer_queue.put_nowait(PairingEventAnswer(
                            event=ref_pairing_event,
                            confirm=True,
                        ))
                    elif dut_pairing_event.WhichOneof('method') == 'passkey_entry_notification':
                        assert ref_pairing_event.WhichOneof('method') == 'passkey_entry_request'
                        ref_answer_queue.put_nowait(PairingEventAnswer(
                            event=ref_pairing_event,
                            passkey=dut_pairing_event.passkey_entry_notification,
                        ))
                    elif dut_pairing_event.WhichOneof('method') == 'passkey_entry_request':
                        assert ref_pairing_event.WhichOneof('method') == 'passkey_entry_notification'
                        dut_answer_queue.put_nowait(PairingEventAnswer(
                            event=dut_pairing_event,
                            passkey=ref_pairing_event.passkey_entry_notification,
                        ))
                    else:
                        assert False

            finally:
                on_ref_pairing.cancel()
                on_dut_pairing.cancel()

        pairing = asyncio.create_task(handle_pairing_events())
        ref_dut = (await self.ref.host.Connect(address=self.dut.address)).connection
        dut_ref = (await self.dut.host.WaitConnection(address=self.ref.address)).connection

        await asyncio.gather(
            self.ref.security.Secure(connection=ref_dut, classic=SecurityLevel.LEVEL2),
            self.dut.security.WaitSecurity(connection=dut_ref, classic=SecurityLevel.LEVEL2)
        )

        pairing.cancel()
        with suppress(asyncio.CancelledError, futures.CancelledError):
            await pairing

        await asyncio.gather(
            self.dut.host.Disconnect(connection=dut_ref),
            self.ref.host.WaitDisconnection(connection=ref_dut)
        )

    @avatar.parameterized([
        (OwnAddressType.PUBLIC, OwnAddressType.PUBLIC, PairingDelegate.NO_OUTPUT_NO_INPUT),
        (OwnAddressType.PUBLIC, OwnAddressType.PUBLIC, PairingDelegate.KEYBOARD_INPUT_ONLY),
        (OwnAddressType.PUBLIC, OwnAddressType.PUBLIC, PairingDelegate.DISPLAY_OUTPUT_ONLY),
        (OwnAddressType.PUBLIC, OwnAddressType.PUBLIC, PairingDelegate.DISPLAY_OUTPUT_AND_YES_NO_INPUT),
        (OwnAddressType.PUBLIC, OwnAddressType.PUBLIC, PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT),
        (OwnAddressType.PUBLIC, OwnAddressType.RANDOM, PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT),
        (OwnAddressType.RANDOM, OwnAddressType.RANDOM, PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT),
        (OwnAddressType.RANDOM, OwnAddressType.PUBLIC, PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT),
    ])
    @avatar.asynchronous
    async def test_le_pairing(self,
        dut_address_type: OwnAddressType,
        ref_address_type: OwnAddressType,
        ref_io_capability
    ):
        # override reference device IO capability
        self.ref.device.io_capability = ref_io_capability

        if ref_address_type in (OwnAddressType.PUBLIC, OwnAddressType.RESOLVABLE_OR_PUBLIC):
            ref_address = {'public': self.ref.address}
        else:
            ref_address = {'random': Address(self.ref.device.random_address)}

        await self.dut.security_storage.DeleteBond(**ref_address)
        await self.dut.host.StartAdvertising(legacy=True, connectable=True, own_address_type=dut_address_type)

        dut = await anext(aiter(self.ref.host.Scan(own_address_type=ref_address_type)))
        if dut_address_type in (OwnAddressType.PUBLIC, OwnAddressType.RESOLVABLE_OR_PUBLIC):
            dut_address = {'public': Address(dut.public)}
        else:
            dut_address = {'random': Address(dut.random)}

        async def handle_pairing_events():
            on_ref_pairing = self.ref.security.OnPairing((ref_answer_queue := AsyncQueue()))
            on_dut_pairing = self.dut.security.OnPairing((dut_answer_queue := AsyncQueue()))

            try:
                while True:
                    dut_pairing_event = await anext(aiter(on_dut_pairing))
                    ref_pairing_event = await anext(aiter(on_ref_pairing))

                    if dut_pairing_event.WhichOneof('method') in ('numeric_comparison', 'just_works'):
                        assert ref_pairing_event.WhichOneof('method') in ('numeric_comparison', 'just_works')
                        dut_answer_queue.put_nowait(PairingEventAnswer(
                            event=dut_pairing_event,
                            confirm=True,
                        ))
                        ref_answer_queue.put_nowait(PairingEventAnswer(
                            event=ref_pairing_event,
                            confirm=True,
                        ))
                    elif dut_pairing_event.WhichOneof('method') == 'passkey_entry_notification':
                        assert ref_pairing_event.WhichOneof('method') == 'passkey_entry_request'
                        ref_answer_queue.put_nowait(PairingEventAnswer(
                            event=ref_pairing_event,
                            passkey=dut_pairing_event.passkey_entry_notification,
                        ))
                    elif dut_pairing_event.WhichOneof('method') == 'passkey_entry_request':
                        assert ref_pairing_event.WhichOneof('method') == 'passkey_entry_notification'
                        dut_answer_queue.put_nowait(PairingEventAnswer(
                            event=dut_pairing_event,
                            passkey=ref_pairing_event.passkey_entry_notification,
                        ))
                    else:
                        assert False

            finally:
                on_ref_pairing.cancel()
                on_dut_pairing.cancel()

        pairing = asyncio.create_task(handle_pairing_events())
        ref_dut = (await self.ref.host.ConnectLE(own_address_type=ref_address_type, **dut_address)).connection
        dut_ref = (await self.dut.host.WaitLEConnection(**ref_address)).connection

        await asyncio.gather(
            self.ref.security.Secure(connection=ref_dut, le=LESecurityLevel.LE_LEVEL4),
            self.dut.security.WaitSecurity(connection=dut_ref, le=LESecurityLevel.LE_LEVEL4)
        )

        pairing.cancel()
        with suppress(asyncio.CancelledError, futures.CancelledError):
            await pairing

        await asyncio.gather(
            self.dut.host.Disconnect(connection=dut_ref),
            self.ref.host.WaitDisconnection(connection=ref_dut)
        )


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()
