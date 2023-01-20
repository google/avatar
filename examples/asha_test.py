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

from mobly import test_runner, base_test
from bumble.gatt import GATT_ASHA_SERVICE

from avatar.utils import Address
from avatar.pandora_client import PandoraClient
from avatar.pandora_device_util import PandoraDeviceUtil
from pandora.host_pb2 import (
    DiscoverabilityMode, DataTypes, OwnAddressType, Connection,
    ConnectabilityMode, OwnAddressType
)


class ASHATest(base_test.BaseTestClass):
    ASHA_UUID = GATT_ASHA_SERVICE.to_hex_str()

    def setup_class(self):
        self.pandora_util = PandoraDeviceUtil(self)
        self.dut, self.ref = self.pandora_util.get_pandora_devices()

    def teardown_class(self):
        self.pandora_util.cleanup()

    @avatar.asynchronous
    async def setup_test(self):
        async def reset(device: PandoraClient):
            await device.host.FactoryReset()
            device.address = (await device.host.ReadLocalAddress(wait_for_ready=True)).address

        await asyncio.gather(reset(self.dut), reset(self.ref))

    def test_ASHA_advertising(self):
        complete_local_name = 'Bumble'
        protocol_version = 0x01
        capability = 0x00
        hisyncid = [0x01, 0x02, 0x03, 0x04, 0x5, 0x6, 0x7, 0x8]
        truncated_hisyncid = hisyncid[:4]

        self.ref.asha.Register(capability=capability,
                               hisyncid=hisyncid)

        self.ref.host.StartAdvertising(
            legacy=True,
            data=DataTypes(
                complete_local_name=complete_local_name,
                incomplete_service_class_uuids16=[ASHATest.ASHA_UUID]
            )
        )
        peers = self.dut.host.Scan()

        scan_result = next((x for x in peers if
                              x.data.complete_local_name == complete_local_name))
        logging.debug(f"scan_response.data: {scan_result}")
        assert ASHATest.ASHA_UUID in scan_result.data.service_data_uuid16
        assert type(scan_result.data.complete_local_name) == str
        expected_advertisement_data = "{:02x}".format(protocol_version) + \
                                      "{:02x}".format(capability) + \
                                      "".join([("{:02x}".format(x)) for x in
                                               truncated_hisyncid])
        assert expected_advertisement_data == \
               (scan_result.data.service_data_uuid16[ASHATest.ASHA_UUID]).hex()

    def test_ASHA_scan_response(self):
        complete_local_name = 'Bumble'
        protocol_version = 0x01
        capability = 0x00
        hisyncid = [0x01, 0x02, 0x03, 0x04, 0x5, 0x6, 0x7, 0x8]
        truncated_hisyncid = hisyncid[:4]

        self.ref.asha.Register(capability=capability,
                               hisyncid=hisyncid)

        self.ref.host.StartAdvertising(
            legacy=True,
            scan_response_data=DataTypes(
                complete_local_name=complete_local_name,
                incomplete_service_class_uuids16=[ASHATest.ASHA_UUID]
            ),
        )
        peers = self.dut.host.Scan()

        scan_response = next((x for x in peers if
                              x.data.complete_local_name == complete_local_name))
        logging.debug(f"scan_response.data: {scan_response}")
        assert ASHATest.ASHA_UUID in scan_response.data.service_data_uuid16
        expected_advertisement_data = "{:02x}".format(protocol_version) + \
                                      "{:02x}".format(capability) + \
                                      "".join([("{:02x}".format(x)) for x in
                                               truncated_hisyncid])
        assert expected_advertisement_data == \
               (scan_response.data.service_data_uuid16[ASHATest.ASHA_UUID]).hex()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()
