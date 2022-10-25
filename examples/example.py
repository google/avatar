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

import logging

from mobly import test_runner, base_test, asserts
from grpc import RpcError

from avatar.utils import Address, into_synchronous
from avatar.controllers import pandora_device


class ExampleTest(base_test.BaseTestClass):
    def setup_class(self):
        self.pandora_devices = self.register_controller(pandora_device)
        self.dut = self.pandora_devices[0]
        self.ref = self.pandora_devices[1]

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
    async def test_classic_connect(self):
        dut_address = self.dut.address
        self.dut.log.info(f'Address: {dut_address}')
        try:
            connection = (await self.ref.host.Connect(address=dut_address)).connection
            await self.ref.host.Disconnect(connection=connection)
        except RpcError as error:
            self.dut.log.error(error)
            asserts.assert_true(False, 'gRPC Error')


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()
