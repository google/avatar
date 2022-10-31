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
import logging

from mobly import test_runner, base_test, signals

from avatar.utils import Address, into_synchronous
from avatar.controllers import pandora_device
from pandora.host_pb2 import (
    DataTypes, AddressType,
    DiscoverabilityMode
)


class ExampleTest(base_test.BaseTestClass):
    def setup_class(self):
        self.pandora_devices = self.register_controller(pandora_device)
        self.dut: pandora_device.PandoraDevice = self.pandora_devices[0]
        self.ref: pandora_device.PandoraDevice = self.pandora_devices[1]

    @into_synchronous()
    async def setup_test(self):
        await self.dut.host.SoftReset()
        await self.ref.host.SoftReset()

    @into_synchronous()
    async def test_print_addresses(self):
        dut_address = self.dut.address
        self.dut.log.info(f'Address: {dut_address}')
        ref_address = self.ref.address
        self.ref.log.info(f'Address: {ref_address}')

    @into_synchronous()
    async def test_get_remote_name(self):
        dut_name = (await self.ref.host.GetRemoteName(address=self.dut.address)).name
        self.ref.log.info(f'DUT remote name: {dut_name}')
        ref_name = (await self.dut.host.GetRemoteName(address=self.ref.address)).name
        self.dut.log.info(f'REF remote name: {ref_name}')

    @into_synchronous()
    async def test_classic_connect(self):
        dut_address = self.dut.address
        self.dut.log.info(f'Address: {dut_address}')
        connection = (await self.ref.host.Connect(address=dut_address)).connection
        dut_name = (await self.ref.host.GetRemoteName(connection=connection)).name
        self.ref.log.info(f'Connected with: "{dut_name}" {dut_address}')
        await self.ref.host.Disconnect(connection=connection)

    @into_synchronous()
    async def test_le_connect(self):
        await self.dut.host.StartAdvertising(
            own_address_type=AddressType.PUBLIC,
            data=DataTypes(include_complete_local_name=True),
            scan_response_data=DataTypes(include_complete_local_name=True),
            is_connectable=True
        )

        res = None
        async for res in self.ref.host.StartScanning():
            if Address(res.address) == self.dut.address:
                logging.info(f"Scan result: '{res.data.complete_local_name}' {Address(res.address)}")
                await self.ref.host.StopScanning()
                break

        # we scanned the DUT device, try connect
        assert Address(res.address) == self.dut.address
        connection = (await self.ref.host.ConnectLE(address=res.address)).connection
        await self.ref.host.Disconnect(connection=connection)

    @into_synchronous()
    async def test_not_discoverable(self):
        await self.dut.host.SetDiscoverabilityMode(mode=DiscoverabilityMode.NOT_DISCOVERABLE)

        async def stop_after(delay):
            await asyncio.sleep(delay)
            await self.ref.host.StopInquiry()

        asyncio.create_task(stop_after(3.0))

        # We mut not see our DUT device
        async for res in self.ref.host.StartInquiry():
            assert Address(res.address) != self.dut.address

    @into_synchronous()
    async def test_discoverable(self):
        await self.dut.host.SetDiscoverabilityMode(mode=DiscoverabilityMode.DISCOVERABLE_LIMITED)

        async def fail_after(delay):
            await asyncio.sleep(delay)
            raise signals.TestFailure

        fail = asyncio.create_task(fail_after(3.0))

        # We mut not see our DUT device
        async for res in self.ref.host.StartInquiry():
            if Address(res.address) == self.dut.address:
                fail.cancel()
                await self.ref.host.StopInquiry()

        await self.dut.host.SetDiscoverabilityMode(mode=DiscoverabilityMode.DISCOVERABLE_GENERAL)

        fail = asyncio.create_task(fail_after(3.0))

        # We mut not see our DUT device
        async for res in self.ref.host.StartInquiry():
            if Address(res.address) == self.dut.address:
                fail.cancel()
                await self.ref.host.StopInquiry()

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()
