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
import enum
import grpc
import itertools
import logging
import random

from avatar import BumblePandoraDevice
from avatar import PandoraDevice
from avatar import PandoraDevices
from mobly import base_test
from mobly import test_runner
from mobly.asserts import assert_equal  # type: ignore
from mobly.asserts import assert_false  # type: ignore
from mobly.asserts import assert_is_not_none  # type: ignore
from mobly.asserts import assert_true  # type: ignore
from mobly.asserts import explicit_pass  # type: ignore
from pandora.host_pb2 import PUBLIC
from pandora.host_pb2 import RANDOM
from pandora.host_pb2 import Connection
from pandora.host_pb2 import DataTypes
from pandora.host_pb2 import OwnAddressType
from typing import Any, Dict, Literal, Optional, Union


class AdvertisingEventProperties(enum.IntEnum):
    ADV_IND = 0x13
    ADV_DIRECT_IND = 0x15
    ADV_SCAN_IND = 0x12
    ADV_NONCONN_IND = 0x10

    CONNECTABLE = 0x01
    SCANNABLE = 0x02
    DIRECTED = 0x04
    LEGACY = 0x10
    ANONYMOUS = 0x20


class LeHostTest(base_test.BaseTestClass):  # type: ignore[misc]
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

    @avatar.parameterized(
        *itertools.product(
            ('connectable', 'non_connectable'),
            ('scannable', 'non_scannable'),
            ('directed', 'undirected'),
            (0, 31),
        )
    )  # type: ignore[misc]
    def test_scan(
        self,
        connectable: Union[Literal['connectable'], Literal['non_connectable']],
        scannable: Union[Literal['scannable'], Literal['non_scannable']],
        directed: Union[Literal['directed'], Literal['undirected']],
        data_len: int,
    ) -> None:
        '''
        Advertise from the REF device with the specified legacy advertising
        event properties. Use the manufacturer specific data to pad the advertising data to the
        desired length. The scan response data must always be provided when
        scannable but it is defaulted.
        '''
        man_specific_data_length = max(0, data_len - 5)  # Flags (3) + LV (2)
        man_specific_data = bytes([random.randint(1, 255) for _ in range(man_specific_data_length)])
        data = DataTypes(manufacturer_specific_data=man_specific_data) if data_len > 0 else None

        is_connectable = True if connectable == 'connectable' else False
        scan_response_data = DataTypes() if scannable == 'scannable' else None
        target = self.dut.address if directed == 'directed' else None

        advertise = self.ref.host.Advertise(
            legacy=True,
            connectable=is_connectable,
            data=data,  # type: ignore[arg-type]
            scan_response_data=scan_response_data,  # type: ignore[arg-type]
            public=target,
            own_address_type=PUBLIC,
        )

        scan = self.dut.host.Scan(legacy=False, passive=False, timeout=5.0)
        report = next((x for x in scan if x.public == self.ref.address))
        try:
            report = next((x for x in scan if x.public == self.ref.address))

            # TODO: scannable is not set by the android server
            # TODO: direct_address is not set by the android server
            assert_true(report.legacy, msg='expected legacy advertising report')
            assert_equal(report.connectable, is_connectable or directed == 'directed')
            assert_equal(
                report.data.manufacturer_specific_data, man_specific_data if directed == 'undirected' else b''
            )
            assert_false(report.truncated, msg='expected non-truncated advertising report')
        except grpc.aio.AioRpcError as e:
            if (
                e.code() == grpc.StatusCode.DEADLINE_EXCEEDED
                and scannable == 'non_scannable'
                and directed == 'undirected'
            ):
                explicit_pass('')
            raise e
        finally:
            scan.cancel()
            advertise.cancel()

    @avatar.parameterized(
        (dict(incomplete_service_class_uuids16=["183A", "181F"]),),
        (dict(incomplete_service_class_uuids32=["FFFF183A", "FFFF181F"]),),
        (dict(incomplete_service_class_uuids128=["FFFF181F-FFFF-1000-8000-00805F9B34FB"]),),
        (dict(shortened_local_name="avatar"),),
        (dict(complete_local_name="avatar_the_last_test_blender"),),
        (dict(tx_power_level=20),),
        (dict(class_of_device=0x40680),),
        (dict(peripheral_connection_interval_min=0x0006, peripheral_connection_interval_max=0x0C80),),
        (dict(service_solicitation_uuids16=["183A", "181F"]),),
        (dict(service_solicitation_uuids32=["FFFF183A", "FFFF181F"]),),
        (dict(service_solicitation_uuids128=["FFFF183A-FFFF-1000-8000-00805F9B34FB"]),),
        (dict(service_data_uuid16={"183A": bytes([1, 2, 3, 4])}),),
        (dict(service_data_uuid32={"FFFF183A": bytes([1, 2, 3, 4])}),),
        (dict(service_data_uuid128={"FFFF181F-FFFF-1000-8000-00805F9B34FB": bytes([1, 2, 3, 4])}),),
        (dict(appearance=0x0591),),
        (dict(advertising_interval=0x1000),),
        (dict(uri="https://www.google.com"),),
        (dict(le_supported_features=bytes([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x10, 0x9F])),),
        (dict(manufacturer_specific_data=bytes([0, 1, 2, 3, 4])),),
    )  # type: ignore[misc]
    def test_scan_response_data(self, data: Dict[str, Any]) -> None:
        '''
        Advertise from the REF device with the specified advertising data.
        Validate that the REF generates the correct advertising data,
        and that the dut presents the correct advertising data in the scan
        result.
        '''
        advertise = self.ref.host.Advertise(
            legacy=True,
            connectable=True,
            data=DataTypes(**data),
            own_address_type=PUBLIC,
        )

        scan = self.dut.host.Scan(legacy=False, passive=False)
        report = next((x for x in scan if x.public == self.ref.address))

        scan.cancel()
        advertise.cancel()

        assert_true(report.legacy, msg='expected legacy advertising report')
        assert_equal(report.connectable, True)
        for key, value in data.items():
            assert_equal(getattr(report.data, key), value)  # type: ignore[misc]
        assert_false(report.truncated, msg='expected non-truncated advertising report')

    @avatar.parameterized(
        (RANDOM,),
        (PUBLIC,),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_connect(self, ref_address_type: OwnAddressType) -> None:
        advertise = self.ref.aio.host.Advertise(
            legacy=True,
            connectable=True,
            own_address_type=ref_address_type,
            data=DataTypes(manufacturer_specific_data=b'pause cafe'),
        )

        scan = self.dut.aio.host.Scan(own_address_type=RANDOM)
        ref = await anext((x async for x in scan if x.data.manufacturer_specific_data == b'pause cafe'))
        scan.cancel()

        ref_dut_res, dut_ref_res = await asyncio.gather(
            anext(aiter(advertise)),
            self.dut.aio.host.ConnectLE(**ref.address_asdict(), own_address_type=RANDOM),
        )
        assert_equal(dut_ref_res.result_variant(), 'connection')
        dut_ref, ref_dut = dut_ref_res.connection, ref_dut_res.connection
        assert_is_not_none(dut_ref)
        assert dut_ref
        advertise.cancel()
        assert_true(await self.is_connected(self.ref, ref_dut), "")

    @avatar.parameterized(
        (RANDOM,),
        (PUBLIC,),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_disconnect(self, ref_address_type: OwnAddressType) -> None:
        advertise = self.ref.aio.host.Advertise(
            legacy=True,
            connectable=True,
            own_address_type=ref_address_type,
            data=DataTypes(manufacturer_specific_data=b'pause cafe'),
        )

        scan = self.dut.aio.host.Scan(own_address_type=RANDOM)
        ref = await anext((x async for x in scan if x.data.manufacturer_specific_data == b'pause cafe'))
        scan.cancel()

        ref_dut_res, dut_ref_res = await asyncio.gather(
            anext(aiter(advertise)),
            self.dut.aio.host.ConnectLE(**ref.address_asdict(), own_address_type=RANDOM),
        )
        assert_equal(dut_ref_res.result_variant(), 'connection')
        dut_ref, ref_dut = dut_ref_res.connection, ref_dut_res.connection
        assert_is_not_none(dut_ref)
        assert dut_ref
        advertise.cancel()
        assert_true(await self.is_connected(self.ref, ref_dut), "")
        await self.dut.aio.host.Disconnect(connection=dut_ref)
        assert_false(await self.is_connected(self.ref, ref_dut), "")

    async def is_connected(self, device: PandoraDevice, connection: Connection) -> bool:
        try:
            await device.aio.host.WaitDisconnection(connection=connection, timeout=5)
            return False
        except grpc.RpcError as e:
            assert_equal(e.code(), grpc.StatusCode.DEADLINE_EXCEEDED)  # type: ignore
            return True


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()  # type: ignore
