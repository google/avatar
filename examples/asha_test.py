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

from avatar import PandoraDevices
from avatar.aio import asynchronous
from avatar.pandora_client import BumblePandoraClient, PandoraClient
from bumble.gatt import GATT_ASHA_SERVICE
from mobly import base_test, test_runner
from mobly.asserts import assert_equal  # type: ignore
from mobly.asserts import assert_in  # type: ignore
from pandora.host_grpc import DataTypes


class ASHATest(base_test.BaseTestClass):  # type: ignore[misc]
    ASHA_UUID = GATT_ASHA_SERVICE.to_hex_str()

    dut: PandoraClient
    ref: BumblePandoraClient

    def setup_class(self) -> None:
        dut, ref = PandoraDevices(self)
        assert isinstance(ref, BumblePandoraClient)
        self.dut, self.ref = dut, ref

    @asynchronous
    async def setup_test(self) -> None:
        async def reset(device: PandoraClient) -> None:
            await device.aio.host.FactoryReset()
            device.address = (await device.aio.host.ReadLocalAddress(wait_for_ready=True)).address  # type: ignore[assignment]

        await asyncio.gather(reset(self.dut), reset(self.ref))

    def test_ASHA_advertising(self) -> None:
        complete_local_name = 'Bumble'
        protocol_version = 0x01
        capability = 0x00
        hisyncid = [0x01, 0x02, 0x03, 0x04, 0x5, 0x6, 0x7, 0x8]
        truncated_hisyncid = hisyncid[:4]

        self.ref.asha.Register(capability=capability, hisyncid=hisyncid)

        self.ref.host.StartAdvertising(
            legacy=True,
            data=DataTypes(
                complete_local_name=complete_local_name, incomplete_service_class_uuids16=[ASHATest.ASHA_UUID]
            ),
        )
        peers = self.dut.host.Scan()

        scan_result = next((x for x in peers if x.data.complete_local_name == complete_local_name))
        logging.debug(f"scan_response.data: {scan_result}")
        assert_in(ASHATest.ASHA_UUID, scan_result.data.service_data_uuid16)
        assert_equal(type(scan_result.data.complete_local_name), str)
        expected_advertisement_data = (
            "{:02x}".format(protocol_version)
            + "{:02x}".format(capability)
            + "".join([("{:02x}".format(x)) for x in truncated_hisyncid])
        )
        assert_equal(expected_advertisement_data, (scan_result.data.service_data_uuid16[ASHATest.ASHA_UUID]).hex())

    def test_ASHA_scan_response(self) -> None:
        complete_local_name = 'Bumble'
        protocol_version = 0x01
        capability = 0x00
        hisyncid = [0x01, 0x02, 0x03, 0x04, 0x5, 0x6, 0x7, 0x8]
        truncated_hisyncid = hisyncid[:4]

        self.ref.asha.Register(capability=capability, hisyncid=hisyncid)

        self.ref.host.StartAdvertising(
            legacy=True,
            scan_response_data=DataTypes(
                complete_local_name=complete_local_name, incomplete_service_class_uuids16=[ASHATest.ASHA_UUID]
            ),
        )
        peers = self.dut.host.Scan()

        scan_response = next((x for x in peers if x.data.complete_local_name == complete_local_name))
        logging.debug(f"scan_response.data: {scan_response}")
        assert_in(ASHATest.ASHA_UUID, scan_response.data.service_data_uuid16)
        expected_advertisement_data = (
            "{:02x}".format(protocol_version)
            + "{:02x}".format(capability)
            + "".join([("{:02x}".format(x)) for x in truncated_hisyncid])
        )
        assert_equal(expected_advertisement_data, (scan_response.data.service_data_uuid16[ASHATest.ASHA_UUID]).hex())


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()  # type: ignore
