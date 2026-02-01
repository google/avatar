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
import enum
import grpc
import logging
import numpy as np

from avatar import BumblePandoraDevice
from avatar import PandoraDevice
from avatar import PandoraDevices
from avatar import asynchronous
from bumble.gatt import GATT_ASHA_SERVICE
from bumble.pairing import PairingDelegate
from bumble.profiles.asha_service import AshaService as AshaGattService
from mobly import base_test
from mobly import signals
from mobly import test_runner
from mobly.asserts import assert_equal  # type: ignore
from mobly.asserts import assert_false  # type: ignore
from mobly.asserts import assert_in  # type: ignore
from mobly.asserts import assert_is_not_none  # type: ignore
from mobly.asserts import assert_not_equal  # type: ignore
from mobly.asserts import assert_true  # type: ignore
from pandora._utils import AioStream
from pandora.asha_pb2 import PlaybackAudioRequest
from pandora.host_pb2 import PUBLIC
from pandora.host_pb2 import RANDOM
from pandora.host_pb2 import AdvertiseResponse
from pandora.host_pb2 import Connection
from pandora.host_pb2 import DataTypes
from pandora.host_pb2 import OwnAddressType
from pandora.host_pb2 import ScanningResponse
from pandora.security_pb2 import LE_LEVEL3
from typing import AsyncIterator, ByteString, List, Optional, Tuple

ASHA_UUID = GATT_ASHA_SERVICE.to_hex_str('-')
HISYCNID: List[int] = [0x01, 0x02, 0x03, 0x04, 0x5, 0x6, 0x7, 0x8]
COMPLETE_LOCAL_NAME: str = "Bumble"
AUDIO_SIGNAL_AMPLITUDE = 0.8
AUDIO_SIGNAL_SAMPLING_RATE = 44100
SINE_FREQUENCY = 440
SINE_DURATION = 0.1


class Ear(enum.IntEnum):
    """Reference devices type"""

    LEFT = 0
    RIGHT = 1


class AshaTest(base_test.BaseTestClass):  # type: ignore[misc]
    devices: Optional[PandoraDevices] = None

    # pandora devices.
    dut: PandoraDevice
    ref_left: BumblePandoraDevice
    ref_right: BumblePandoraDevice

    def setup_class(self) -> None:
        self.devices = PandoraDevices(self)
        self.dut, ref_left, ref_right, *_ = self.devices

        if isinstance(self.dut, BumblePandoraDevice):
            raise signals.TestAbortClass('DUT Bumble does not support Asha source')
        if not isinstance(ref_left, BumblePandoraDevice):
            raise signals.TestAbortClass('Test require Bumble as reference device(s)')
        if not isinstance(ref_right, BumblePandoraDevice):
            raise signals.TestAbortClass('Test require Bumble as reference device(s)')

        self.ref_left, self.ref_right = ref_left, ref_right

    def teardown_class(self) -> None:
        if self.devices:
            self.devices.stop_all()

    @avatar.asynchronous
    async def setup_test(self) -> None:
        await asyncio.gather(self.dut.reset(), self.ref_left.reset(), self.ref_right.reset())

        # ASHA hearing aid's IO capability is NO_OUTPUT_NO_INPUT
        self.ref_left.server_config.io_capability = PairingDelegate.NO_OUTPUT_NO_INPUT
        self.ref_right.server_config.io_capability = PairingDelegate.NO_OUTPUT_NO_INPUT

    async def ref_advertise_asha(
        self, ref_device: PandoraDevice, ref_address_type: OwnAddressType, ear: Ear
    ) -> AioStream[AdvertiseResponse]:
        """
        Ref device starts to advertise with service data in advertisement data.
        :return: Ref device's advertise stream
        """
        # Ref starts advertising with ASHA service data
        await ref_device.aio.asha.Register(capability=ear, hisyncid=HISYCNID)
        return ref_device.aio.host.Advertise(
            legacy=True,
            connectable=True,
            own_address_type=ref_address_type,
            data=DataTypes(
                complete_local_name=COMPLETE_LOCAL_NAME,
                incomplete_service_class_uuids16=[ASHA_UUID],
            ),
        )

    async def dut_scan_for_asha(self, dut_address_type: OwnAddressType, ear: Ear) -> ScanningResponse:
        """
        DUT starts to scan for the Ref device.
        :return: ScanningResponse for ASHA
        """
        dut_scan = self.dut.aio.host.Scan(own_address_type=dut_address_type)
        expected_advertisement_data = self.get_expected_advertisement_data(ear)
        ref = await anext(
            (
                x
                async for x in dut_scan
                if (
                    ASHA_UUID in x.data.incomplete_service_class_uuids16
                    and expected_advertisement_data == (x.data.service_data_uuid16[ASHA_UUID]).hex()
                )
            )
        )
        dut_scan.cancel()
        return ref

    async def dut_connect_to_ref(
        self, advertisement: AioStream[AdvertiseResponse], ref: ScanningResponse, dut_address_type: OwnAddressType
    ) -> Tuple[Connection, Connection]:
        """
        Helper method for Dut connects to Ref
        :return: a Tuple (DUT to REF connection, REF to DUT connection)
        """
        (dut_ref_res, ref_dut_res) = await asyncio.gather(
            self.dut.aio.host.ConnectLE(own_address_type=dut_address_type, **ref.address_asdict()),
            anext(aiter(advertisement)),  # pytype: disable=name-error
        )
        assert_equal(dut_ref_res.result_variant(), 'connection')
        dut_ref, ref_dut = dut_ref_res.connection, ref_dut_res.connection
        assert_is_not_none(dut_ref)
        assert dut_ref
        return dut_ref, ref_dut

    async def is_device_connected(self, device: PandoraDevice, connection: Connection, timeout: float) -> bool:
        try:
            await device.aio.host.WaitDisconnection(connection=connection, timeout=timeout)
            return False
        except grpc.RpcError as e:
            assert_equal(e.code(), grpc.StatusCode.DEADLINE_EXCEEDED)  # type: ignore
            return True

    def get_expected_advertisement_data(self, ear: Ear) -> str:
        protocol_version = 0x01
        truncated_hisyncid = HISYCNID[:4]
        return (
            "{:02x}".format(protocol_version)
            + "{:02x}".format(ear)
            + "".join([("{:02x}".format(x)) for x in truncated_hisyncid])
        )

    def get_le_psm_future(self, ref_device: BumblePandoraDevice) -> asyncio.Future[int]:
        asha_service = next((x for x in ref_device.device.gatt_server.attributes if isinstance(x, AshaGattService)))
        le_psm_future = asyncio.get_running_loop().create_future()

        def le_psm_handler(connection: Connection, data: int) -> None:
            le_psm_future.set_result(data)

        asha_service.on('le_psm_out', le_psm_handler)
        return le_psm_future

    def get_read_only_properties_future(self, ref_device: BumblePandoraDevice) -> asyncio.Future[bytes]:
        asha_service = next((x for x in ref_device.device.gatt_server.attributes if isinstance(x, AshaGattService)))
        read_only_properties_future = asyncio.get_running_loop().create_future()

        def read_only_properties_handler(connection: Connection, data: bytes) -> None:
            read_only_properties_future.set_result(data)

        asha_service.on('read_only_properties', read_only_properties_handler)
        return read_only_properties_future

    def get_start_future(self, ref_device: BumblePandoraDevice) -> asyncio.Future[dict[str, int]]:
        asha_service = next((x for x in ref_device.device.gatt_server.attributes if isinstance(x, AshaGattService)))
        start_future = asyncio.get_running_loop().create_future()

        def start_command_handler(connection: Connection, data: dict[str, int]) -> None:
            start_future.set_result(data)

        asha_service.on('start', start_command_handler)
        return start_future

    def get_stop_future(self, ref_device: BumblePandoraDevice) -> asyncio.Future[Connection]:
        asha_service = next((x for x in ref_device.device.gatt_server.attributes if isinstance(x, AshaGattService)))
        stop_future = asyncio.get_running_loop().create_future()

        def stop_command_handler(connection: Connection) -> None:
            stop_future.set_result(connection)

        asha_service.on('stop', stop_command_handler)
        return stop_future

    async def get_audio_data(self, ref_device: PandoraDevice, connection: Connection, timeout: int) -> ByteString:
        audio_data = bytearray()
        try:
            captured_data = ref_device.aio.asha.CaptureAudio(connection=connection, timeout=timeout)
            async for data in captured_data:
                audio_data.extend(data.data)

        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                pass
            else:
                raise

        return audio_data

    async def generate_sine(self, connection: Connection) -> AsyncIterator[PlaybackAudioRequest]:
        # generate sine wave audio
        sine = AUDIO_SIGNAL_AMPLITUDE * np.sin(
            2
            * np.pi
            * np.arange(AUDIO_SIGNAL_SAMPLING_RATE * SINE_DURATION)
            * (SINE_FREQUENCY / AUDIO_SIGNAL_SAMPLING_RATE)
        )
        s16le = (sine * 32767).astype('<i2')

        # Interleaved audio.
        stereo = np.zeros(s16le.size * 2, dtype=sine.dtype)
        stereo[0::2] = s16le

        # Send 4 second of audio.
        for _ in range(0, int(4 / SINE_DURATION)):
            yield PlaybackAudioRequest(connection=connection, data=stereo.tobytes())

    @avatar.parameterized(
        (RANDOM, Ear.LEFT),
        (RANDOM, Ear.RIGHT),
    )  # type: ignore[misc]
    @asynchronous
    async def test_advertising_advertisement_data(
        self,
        ref_address_type: OwnAddressType,
        ear: Ear,
    ) -> None:
        """
        Ref starts ASHA advertisements with service data in advertisement data.
        DUT starts a service discovery.
        Verify Ref is correctly discovered by DUT as a hearing aid device.
        """
        advertisement = await self.ref_advertise_asha(self.ref_left, ref_address_type, ear)

        # DUT starts a service discovery
        scan_result = await self.dut_scan_for_asha(dut_address_type=RANDOM, ear=ear)
        advertisement.cancel()

        # Verify Ref is correctly discovered by DUT as a hearing aid device
        assert_in(ASHA_UUID, scan_result.data.service_data_uuid16)
        assert_equal(type(scan_result.data.complete_local_name), str)
        expected_advertisement_data = self.get_expected_advertisement_data(ear)
        assert_equal(
            expected_advertisement_data,
            (scan_result.data.service_data_uuid16[ASHA_UUID]).hex(),
        )

    @asynchronous
    async def test_advertising_scan_response(self) -> None:
        """
        Ref starts ASHA advertisements with service data in scan response data.
        DUT starts a service discovery.
        Verify Ref is correctly discovered by DUT as a hearing aid device.
        """
        await self.ref_left.aio.asha.Register(capability=Ear.LEFT, hisyncid=HISYCNID)

        # advertise with ASHA service data in scan response
        advertisement = self.ref_left.aio.host.Advertise(
            legacy=True,
            scan_response_data=DataTypes(
                complete_local_name=COMPLETE_LOCAL_NAME,
                complete_service_class_uuids16=[ASHA_UUID],
            ),
        )

        scan_result = await self.dut_scan_for_asha(dut_address_type=RANDOM, ear=Ear.LEFT)
        advertisement.cancel()

        # Verify Ref is correctly discovered by DUT as a hearing aid device.
        assert_in(ASHA_UUID, scan_result.data.service_data_uuid16)
        expected_advertisement_data = self.get_expected_advertisement_data(Ear.LEFT)
        assert_equal(
            expected_advertisement_data,
            (scan_result.data.service_data_uuid16[ASHA_UUID]).hex(),
        )

    @avatar.parameterized(
        (RANDOM, PUBLIC),
        (RANDOM, RANDOM),
    )  # type: ignore[misc]
    @asynchronous
    async def test_pairing(
        self,
        dut_address_type: OwnAddressType,
        ref_address_type: OwnAddressType,
    ) -> None:
        """
        DUT discovers Ref.
        DUT initiates connection to Ref.
        Verify that DUT and Ref are bonded and connected.
        """
        advertisement = await self.ref_advertise_asha(
            ref_device=self.ref_left, ref_address_type=ref_address_type, ear=Ear.LEFT
        )

        ref = await self.dut_scan_for_asha(dut_address_type=dut_address_type, ear=Ear.LEFT)

        # DUT initiates connection to Ref.
        dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, dut_address_type)
        advertisement.cancel()

        # DUT starts pairing with the Ref.
        (secure, wait_security) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref, le=LE_LEVEL3),
            self.ref_left.aio.security.WaitSecurity(connection=ref_dut, le=LE_LEVEL3),
        )

        assert_equal(secure.result_variant(), 'success')
        assert_equal(wait_security.result_variant(), 'success')

    @avatar.parameterized(
        (RANDOM, PUBLIC),
        (RANDOM, RANDOM),
    )  # type: ignore[misc]
    @asynchronous
    async def test_pairing_dual_device(
        self,
        dut_address_type: OwnAddressType,
        ref_address_type: OwnAddressType,
    ) -> None:
        """
        DUT discovers Ref.
        DUT initiates connection to Ref.
        Verify that DUT and Ref are bonded and connected.
        """

        async def ref_device_connect(ref_device: BumblePandoraDevice, ear: Ear) -> Tuple[Connection, Connection]:
            advertisement = await self.ref_advertise_asha(
                ref_device=ref_device, ref_address_type=ref_address_type, ear=ear
            )
            ref = await self.dut_scan_for_asha(dut_address_type=dut_address_type, ear=ear)
            # DUT initiates connection to ref_device.
            dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, dut_address_type)
            advertisement.cancel()

            return dut_ref, ref_dut

        ((dut_ref_left, ref_left_dut), (dut_ref_right, ref_right_dut)) = await asyncio.gather(
            ref_device_connect(self.ref_left, Ear.LEFT), ref_device_connect(self.ref_right, Ear.RIGHT)
        )

        # DUT starts pairing with the ref_left
        (secure_left, wait_security_left) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref_left, le=LE_LEVEL3),
            self.ref_left.aio.security.WaitSecurity(connection=ref_left_dut, le=LE_LEVEL3),
        )

        assert_equal(secure_left.result_variant(), 'success')
        assert_equal(wait_security_left.result_variant(), 'success')

        # DUT starts pairing with the ref_right
        (secure_right, wait_security_right) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref_right, le=LE_LEVEL3),
            self.ref_right.aio.security.WaitSecurity(connection=ref_right_dut, le=LE_LEVEL3),
        )

        assert_equal(secure_right.result_variant(), 'success')
        assert_equal(wait_security_right.result_variant(), 'success')

        await asyncio.gather(
            self.ref_left.aio.host.Disconnect(connection=ref_left_dut),
            self.dut.aio.host.WaitDisconnection(connection=dut_ref_left),
        )
        await asyncio.gather(
            self.ref_right.aio.host.Disconnect(connection=ref_right_dut),
            self.dut.aio.host.WaitDisconnection(connection=dut_ref_right),
        )

    @avatar.parameterized(
        (RANDOM, PUBLIC),
        (RANDOM, RANDOM),
    )  # type: ignore[misc]
    @asynchronous
    async def test_unbonding(
        self,
        dut_address_type: OwnAddressType,
        ref_address_type: OwnAddressType,
    ) -> None:
        """
        DUT removes bond with Ref.
        Verify that DUT and Ref are disconnected and unbonded.
        """

        advertisement = await self.ref_advertise_asha(
            ref_device=self.ref_left, ref_address_type=ref_address_type, ear=Ear.LEFT
        )
        ref = await self.dut_scan_for_asha(dut_address_type=dut_address_type, ear=Ear.LEFT)

        dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, dut_address_type)

        secure = await self.dut.aio.security.Secure(connection=dut_ref, le=LE_LEVEL3)
        assert_equal(secure.WhichOneof("result"), "success")

        # disconnect & delete the bond
        await self.ref_left.aio.host.Disconnect(ref_dut)
        await self.dut.aio.security_storage.DeleteBond(random=self.ref_left.random_address)

        # DUT connect to REF again
        dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, dut_address_type)
        advertisement.cancel()

        secure = await self.ref_left.aio.security.Secure(connection=ref_dut, le=LE_LEVEL3)
        assert_equal(secure.WhichOneof("result"), "success")

    @avatar.parameterized(
        (RANDOM, RANDOM),
        (RANDOM, PUBLIC),
    )  # type: ignore[misc]
    @asynchronous
    async def test_connection(self, dut_address_type: OwnAddressType, ref_address_type: OwnAddressType) -> None:
        """
        DUT discovers Ref.
        DUT initiates connection to Ref.
        Verify that DUT and Ref are connected.
        """
        advertisement = await self.ref_advertise_asha(
            ref_device=self.ref_left, ref_address_type=ref_address_type, ear=Ear.LEFT
        )
        ref = await self.dut_scan_for_asha(dut_address_type=dut_address_type, ear=Ear.LEFT)

        _, _ = await self.dut_connect_to_ref(advertisement, ref, dut_address_type)
        advertisement.cancel()

    @avatar.parameterized(
        (RANDOM, RANDOM),
        (RANDOM, PUBLIC),
    )  # type: ignore[misc]
    @asynchronous
    async def test_disconnect_initiator(
        self,
        dut_address_type: OwnAddressType,
        ref_address_type: OwnAddressType,
    ) -> None:
        """
        DUT initiates disconnection to Ref.
        Verify that DUT and Ref are disconnected.
        """
        advertisement = await self.ref_advertise_asha(
            ref_device=self.ref_left, ref_address_type=ref_address_type, ear=Ear.LEFT
        )
        ref = await self.dut_scan_for_asha(dut_address_type=dut_address_type, ear=Ear.LEFT)

        dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, dut_address_type)
        advertisement.cancel()

        await self.dut.aio.host.Disconnect(connection=dut_ref)
        assert_false(await self.is_device_connected(self.ref_left, ref_dut, 5), "Should be disconnected")

    @avatar.parameterized(
        (RANDOM, RANDOM),
        (RANDOM, PUBLIC),
    )  # type: ignore[misc]
    @asynchronous
    async def test_disconnect_initiator_dual_device(
        self,
        dut_address_type: OwnAddressType,
        ref_address_type: OwnAddressType,
    ) -> None:
        """
        DUT initiates disconnection to Ref.
        Verify that DUT and Ref are disconnected.
        """

        async def ref_device_connect(ref_device: BumblePandoraDevice, ear: Ear) -> Tuple[Connection, Connection]:
            advertisement = await self.ref_advertise_asha(
                ref_device=ref_device, ref_address_type=ref_address_type, ear=ear
            )
            ref = await self.dut_scan_for_asha(dut_address_type=dut_address_type, ear=ear)
            # DUT initiates connection to ref_device.
            dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, dut_address_type)
            advertisement.cancel()

            return dut_ref, ref_dut

        ((dut_ref_left, ref_left_dut), (dut_ref_right, ref_right_dut)) = await asyncio.gather(
            ref_device_connect(self.ref_left, Ear.LEFT), ref_device_connect(self.ref_right, Ear.RIGHT)
        )

        # Disconnect from DUT
        await asyncio.gather(
            self.dut.aio.host.Disconnect(connection=dut_ref_left),
            self.dut.aio.host.Disconnect(connection=dut_ref_right),
        )

        # Verify the Refs are disconnected
        assert_false(await self.is_device_connected(self.ref_left, ref_left_dut, 5), "Should be disconnected")
        assert_false(await self.is_device_connected(self.ref_right, ref_right_dut, 5), "Should be disconnected")

    @avatar.parameterized(
        (RANDOM, RANDOM),
        (RANDOM, PUBLIC),
    )  # type: ignore[misc]
    @asynchronous
    async def test_disconnect_acceptor(
        self,
        dut_address_type: OwnAddressType,
        ref_address_type: OwnAddressType,
    ) -> None:
        """
        Ref initiates disconnection to DUT (typically when put back in its box).
        Verify that Ref is disconnected.
        """
        advertisement = await self.ref_advertise_asha(
            ref_device=self.ref_left, ref_address_type=ref_address_type, ear=Ear.LEFT
        )
        ref = await self.dut_scan_for_asha(dut_address_type=dut_address_type, ear=Ear.LEFT)

        dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, dut_address_type)
        advertisement.cancel()

        await self.ref_left.aio.host.Disconnect(connection=ref_dut)
        assert_false(await self.is_device_connected(self.dut, dut_ref, 5), "Should be disconnected")

    @avatar.parameterized(
        (RANDOM, RANDOM, 0),
        (RANDOM, RANDOM, 0.5),
        (RANDOM, RANDOM, 1),
        (RANDOM, RANDOM, 5),
    )  # type: ignore[misc]
    @asynchronous
    async def test_reconnection(
        self,
        dut_address_type: OwnAddressType,
        ref_address_type: OwnAddressType,
        reconnection_gap: float,
    ) -> None:
        """
        DUT initiates disconnection to the Ref.
        Verify that DUT and Ref are disconnected.
        DUT reconnects to Ref after various certain time.
        Verify that DUT and Ref are connected.
        """

        async def connect_and_disconnect() -> None:
            advertisement = await self.ref_advertise_asha(
                ref_device=self.ref_left, ref_address_type=ref_address_type, ear=Ear.LEFT
            )
            ref = await self.dut_scan_for_asha(dut_address_type=dut_address_type, ear=Ear.LEFT)
            dut_ref, _ = await self.dut_connect_to_ref(advertisement, ref, dut_address_type)
            advertisement.cancel()
            await self.dut.aio.host.Disconnect(connection=dut_ref)

        await connect_and_disconnect()
        # simulating reconnect interval
        await asyncio.sleep(reconnection_gap)
        await connect_and_disconnect()

    @avatar.parameterized(
        (RANDOM, RANDOM),
        (RANDOM, PUBLIC),
    )  # type: ignore[misc]
    @asynchronous
    async def test_auto_connection(
        self,
        dut_address_type: OwnAddressType,
        ref_address_type: OwnAddressType,
    ) -> None:
        """
        Ref initiates disconnection to DUT.
        Ref starts sending ASHA advertisements.
        Verify that DUT auto-connects to Ref.
        """
        advertisement = await self.ref_advertise_asha(
            ref_device=self.ref_left, ref_address_type=ref_address_type, ear=Ear.LEFT
        )
        ref = await self.dut_scan_for_asha(dut_address_type=dut_address_type, ear=Ear.LEFT)

        # manually connect and not cancel advertisement
        dut_ref_res, ref_dut_res = await asyncio.gather(
            self.dut.aio.host.ConnectLE(own_address_type=dut_address_type, **ref.address_asdict()),
            anext(aiter(advertisement)),  # pytype: disable=name-error
        )
        assert_equal(dut_ref_res.result_variant(), 'connection')
        dut_ref, ref_dut = dut_ref_res.connection, ref_dut_res.connection
        assert_is_not_none(dut_ref)
        assert dut_ref

        # Pairing
        (secure, wait_security) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref, le=LE_LEVEL3),
            self.ref_left.aio.security.WaitSecurity(connection=ref_dut, le=LE_LEVEL3),
        )
        assert_equal(secure.result_variant(), 'success')
        assert_equal(wait_security.result_variant(), 'success')

        await self.ref_left.aio.host.Disconnect(connection=ref_dut)

        ref_dut = (await anext(aiter(advertisement))).connection
        advertisement.cancel()

    @avatar.parameterized(
        (RANDOM, RANDOM, Ear.LEFT),
        (RANDOM, PUBLIC, Ear.RIGHT),
    )  # type: ignore[misc]
    @asynchronous
    async def test_disconnect_acceptor_dual_device(
        self,
        dut_address_type: OwnAddressType,
        ref_address_type: OwnAddressType,
        disconnect_device: Ear,
    ) -> None:
        """
        Prerequisites: DUT and Ref are connected and bonded.
        Description:
           1. One peripheral of Ref initiates disconnection to DUT.
           2. Verify that it is disconnected and that the other peripheral is still connected.
        """

        advertisement_left = await self.ref_advertise_asha(
            ref_device=self.ref_left, ref_address_type=ref_address_type, ear=Ear.LEFT
        )
        ref_left = await self.dut_scan_for_asha(dut_address_type=dut_address_type, ear=Ear.LEFT)
        _, ref_left_dut = await self.dut_connect_to_ref(
            advertisement=advertisement_left, ref=ref_left, dut_address_type=dut_address_type
        )
        advertisement_left.cancel()

        advertisement_right = await self.ref_advertise_asha(
            ref_device=self.ref_right, ref_address_type=ref_address_type, ear=Ear.RIGHT
        )
        ref_right = await self.dut_scan_for_asha(dut_address_type=dut_address_type, ear=Ear.RIGHT)
        _, ref_right_dut = await self.dut_connect_to_ref(
            advertisement=advertisement_right, ref=ref_right, dut_address_type=dut_address_type
        )
        advertisement_right.cancel()

        if disconnect_device == Ear.LEFT:
            await self.ref_left.aio.host.Disconnect(connection=ref_left_dut)
            assert_true(await self.is_device_connected(self.ref_right, ref_right_dut, 5), "Should be disconnected")
            assert_false(await self.is_device_connected(self.ref_left, ref_left_dut, 5), "Should be disconnected")
        else:
            await self.ref_right.aio.host.Disconnect(connection=ref_right_dut)
            assert_false(await self.is_device_connected(self.ref_right, ref_right_dut, 5), "Should be disconnected")
            assert_true(await self.is_device_connected(self.ref_left, ref_left_dut, 5), "Should be disconnected")

    @avatar.parameterized(
        (RANDOM, RANDOM, Ear.LEFT),
        (RANDOM, RANDOM, Ear.RIGHT),
        (RANDOM, PUBLIC, Ear.LEFT),
        (RANDOM, PUBLIC, Ear.RIGHT),
    )  # type: ignore[misc]
    @asynchronous
    async def test_auto_connection_dual_device(
        self, dut_address_type: OwnAddressType, ref_address_type: OwnAddressType, tested_device: Ear
    ) -> None:
        """
        Prerequisites: DUT and Ref are connected and bonded. Ref is a dual device.
        Description:
           1. One peripheral of Ref initiates disconnection to DUT.
           2. The disconnected peripheral starts sending ASHA advertisements.
           3. Verify that DUT auto-connects to the peripheral.
        """

        advertisement_left = await self.ref_advertise_asha(
            ref_device=self.ref_left, ref_address_type=ref_address_type, ear=Ear.LEFT
        )
        ref_left = await self.dut_scan_for_asha(dut_address_type=dut_address_type, ear=Ear.LEFT)
        (dut_ref_left_res, ref_left_dut_res) = await asyncio.gather(
            self.dut.aio.host.ConnectLE(own_address_type=dut_address_type, **ref_left.address_asdict()),
            anext(aiter(advertisement_left)),  # pytype: disable=name-error
        )
        assert_equal(dut_ref_left_res.result_variant(), 'connection')
        dut_ref_left, ref_left_dut = dut_ref_left_res.connection, ref_left_dut_res.connection
        assert_is_not_none(dut_ref_left)
        assert dut_ref_left
        advertisement_left.cancel()

        advertisement_right = await self.ref_advertise_asha(
            ref_device=self.ref_right, ref_address_type=ref_address_type, ear=Ear.RIGHT
        )
        ref_right = await self.dut_scan_for_asha(dut_address_type=dut_address_type, ear=Ear.RIGHT)
        (dut_ref_right_res, ref_right_dut_res) = await asyncio.gather(
            self.dut.aio.host.ConnectLE(own_address_type=dut_address_type, **ref_right.address_asdict()),
            anext(aiter(advertisement_right)),  # pytype: disable=name-error
        )
        assert_equal(dut_ref_right_res.result_variant(), 'connection')
        dut_ref_right, ref_right_dut = dut_ref_right_res.connection, ref_right_dut_res.connection
        assert_is_not_none(dut_ref_right)
        assert dut_ref_right
        advertisement_right.cancel()

        # Pairing
        (secure_left, wait_security_left) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref_left, le=LE_LEVEL3),
            self.ref_left.aio.security.WaitSecurity(connection=ref_left_dut, le=LE_LEVEL3),
        )
        assert_equal(secure_left.result_variant(), 'success')
        assert_equal(wait_security_left.result_variant(), 'success')

        (secure_right, wait_security_right) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref_right, le=LE_LEVEL3),
            self.ref_right.aio.security.WaitSecurity(connection=ref_right_dut, le=LE_LEVEL3),
        )
        assert_equal(secure_right.result_variant(), 'success')
        assert_equal(wait_security_right.result_variant(), 'success')

        if tested_device == Ear.LEFT:
            await asyncio.gather(
                self.ref_left.aio.host.Disconnect(connection=ref_left_dut),
                self.dut.aio.host.WaitDisconnection(connection=dut_ref_left),
            )
            assert_false(await self.is_device_connected(self.ref_left, ref_left_dut, 5), "Should be disconnected")

            advertisement_left = await self.ref_advertise_asha(
                ref_device=self.ref_left, ref_address_type=ref_address_type, ear=Ear.LEFT
            )
            ref_left_dut = (await anext(aiter(advertisement_left))).connection
            advertisement_left.cancel()
        else:
            await asyncio.gather(
                self.ref_right.aio.host.Disconnect(connection=ref_right_dut),
                self.dut.aio.host.WaitDisconnection(connection=dut_ref_right),
            )
            assert_false(await self.is_device_connected(self.ref_right, ref_right_dut, 5), "Should be disconnected")

            advertisement_right = await self.ref_advertise_asha(
                ref_device=self.ref_right, ref_address_type=ref_address_type, ear=Ear.RIGHT
            )
            ref_right_dut = (await anext(aiter(advertisement_right))).connection
            advertisement_right.cancel()

    @asynchronous
    async def test_music_start(self) -> None:
        """
        DUT discovers Ref.
        DUT initiates connection to Ref.
        Verify that DUT and Ref are bonded and connected.
        DUT starts media streaming.
        Verify that DUT sends a correct AudioControlPoint `Start` command (codec=1,
        audiotype=0, volume=<volume set on DUT>, otherstate=<state of Ref aux if dual devices>).
        """

        async def ref_device_connect(ref_device: BumblePandoraDevice, ear: Ear) -> Tuple[Connection, Connection]:
            advertisement = await self.ref_advertise_asha(ref_device=ref_device, ref_address_type=RANDOM, ear=ear)
            ref = await self.dut_scan_for_asha(dut_address_type=RANDOM, ear=ear)
            # DUT initiates connection to ref_device.
            dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, RANDOM)
            advertisement.cancel()

            return dut_ref, ref_dut

        dut_ref, ref_dut = await ref_device_connect(self.ref_left, Ear.LEFT)
        le_psm_future = self.get_le_psm_future(self.ref_left)
        read_only_properties_future = self.get_read_only_properties_future(self.ref_left)

        # DUT starts pairing with the ref_left
        (secure, wait_security) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref, le=LE_LEVEL3),
            self.ref_left.aio.security.WaitSecurity(connection=ref_dut, le=LE_LEVEL3),
        )

        assert_equal(secure.result_variant(), 'success')
        assert_equal(wait_security.result_variant(), 'success')

        le_psm_out_result = await asyncio.wait_for(le_psm_future, timeout=3.0)
        assert_is_not_none(le_psm_out_result)

        read_only_properties_result = await asyncio.wait_for(read_only_properties_future, timeout=3.0)
        assert_is_not_none(read_only_properties_result)

        start_future = self.get_start_future(self.ref_left)

        logging.info("send start")
        await self.dut.aio.asha.WaitPeripheral(connection=dut_ref)
        _, start_result = await asyncio.gather(
            self.dut.aio.asha.Start(connection=dut_ref), asyncio.wait_for(start_future, timeout=3.0)
        )

        logging.info(f"start_result:{start_result}")
        assert_is_not_none(start_result)
        assert_equal(start_result['codec'], 1)
        assert_equal(start_result['audiotype'], 0)
        assert_is_not_none(start_result['volume'])
        assert_equal(start_result['otherstate'], 0)

    @asynchronous
    async def test_set_volume(self) -> None:
        """
        DUT discovers Ref.
        DUT initiates connection to Ref.
        Verify that DUT and Ref are bonded and connected.
        DUT is streaming media to Ref.
        Change volume on DUT.
        Verify DUT writes the correct value to ASHA `Volume` characteristic.
        """
        raise signals.TestSkip("TODO: update bt test interface for SetVolume to retry")

        advertisement = await self.ref_advertise_asha(ref_device=self.ref_left, ref_address_type=RANDOM, ear=Ear.LEFT)

        ref = await self.dut_scan_for_asha(dut_address_type=RANDOM, ear=Ear.LEFT)

        # DUT initiates connection to Ref.
        dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, RANDOM)
        advertisement.cancel()

        # DUT starts pairing with the ref_left
        (secure, wait_security) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref, le=LE_LEVEL3),
            self.ref_left.aio.security.WaitSecurity(connection=ref_dut, le=LE_LEVEL3),
        )

        assert_equal(secure.result_variant(), 'success')
        assert_equal(wait_security.result_variant(), 'success')

        asha_service = next((x for x in self.ref_left.device.gatt_server.attributes if isinstance(x, AshaGattService)))

        volume_future = asyncio.get_running_loop().create_future()

        def volume_command_handler(connection: Connection, data: int):
            volume_future.set_result(data)

        asha_service.on('volume', volume_command_handler)

        await self.dut.aio.asha.WaitPeripheral(connection=dut_ref)
        await self.dut.aio.asha.Start(connection=dut_ref)
        # set volume to max volume
        _, volume_result = await asyncio.gather(
            self.dut.aio.asha.SetVolume(1), asyncio.wait_for(volume_future, timeout=3.0)
        )

        logging.info(f"start_result:{volume_result}")
        assert_is_not_none(volume_result)
        assert_equal(volume_result, 0)

    @asynchronous
    async def test_music_stop(self) -> None:
        """
        DUT discovers Ref.
        DUT initiates connection to Ref.
        Verify that DUT and Ref are bonded and connected.
        DUT is streaming media to Ref.
        DUT stops media streaming on Ref.
        Verify that DUT sends a correct AudioControlPoint `Stop` command.
        """

        async def ref_device_connect(ref_device: BumblePandoraDevice, ear: Ear) -> Tuple[Connection, Connection]:
            advertisement = await self.ref_advertise_asha(ref_device=ref_device, ref_address_type=RANDOM, ear=ear)
            ref = await self.dut_scan_for_asha(dut_address_type=RANDOM, ear=ear)
            # DUT initiates connection to ref_device.
            dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, RANDOM)
            advertisement.cancel()

            return dut_ref, ref_dut

        dut_ref, ref_dut = await ref_device_connect(self.ref_left, Ear.LEFT)

        # DUT starts pairing with the ref_left
        (secure, wait_security) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref, le=LE_LEVEL3),
            self.ref_left.aio.security.WaitSecurity(connection=ref_dut, le=LE_LEVEL3),
        )

        assert_equal(secure.result_variant(), 'success')
        assert_equal(wait_security.result_variant(), 'success')

        stop_future = self.get_stop_future(self.ref_left)

        await self.dut.aio.asha.WaitPeripheral(connection=dut_ref)
        await self.dut.aio.asha.Start(connection=dut_ref)
        logging.info("send stop")
        _, stop_result = await asyncio.gather(self.dut.aio.asha.Stop(), asyncio.wait_for(stop_future, timeout=10.0))

        logging.info(f"stop_result:{stop_result}")
        assert_is_not_none(stop_result)

        # Sleep 0.5 second to mitigate flaky test first.
        await asyncio.sleep(0.5)

        audio_data = await self.get_audio_data(ref_device=self.ref_left, connection=ref_dut, timeout=10)
        assert_equal(len(audio_data), 0)

    @asynchronous
    async def test_music_restart(self) -> None:
        """
        DUT discovers Ref.
        DUT initiates connection to Ref.
        Verify that DUT and Ref are bonded and connected.
        DUT starts media streaming.
        DUT stops media streaming.
        Verify that DUT sends a correct AudioControlPoint `Stop` command.
        DUT starts media streaming again.
        Verify that DUT sends a correct AudioControlPoint `Start` command.
        """

        async def ref_device_connect(ref_device: BumblePandoraDevice, ear: Ear) -> Tuple[Connection, Connection]:
            advertisement = await self.ref_advertise_asha(ref_device=ref_device, ref_address_type=RANDOM, ear=ear)
            ref = await self.dut_scan_for_asha(dut_address_type=RANDOM, ear=ear)
            # DUT initiates connection to ref_device.
            dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, RANDOM)
            advertisement.cancel()

            return dut_ref, ref_dut

        dut_ref, ref_dut = await ref_device_connect(self.ref_left, Ear.LEFT)

        # DUT starts pairing with the ref_left
        (secure, wait_security) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref, le=LE_LEVEL3),
            self.ref_left.aio.security.WaitSecurity(connection=ref_dut, le=LE_LEVEL3),
        )

        assert_equal(secure.result_variant(), 'success')
        assert_equal(wait_security.result_variant(), 'success')

        stop_future = self.get_stop_future(self.ref_left)

        await self.dut.aio.asha.WaitPeripheral(connection=dut_ref)
        await self.dut.aio.asha.Start(connection=dut_ref)
        _, stop_result = await asyncio.gather(self.dut.aio.asha.Stop(), asyncio.wait_for(stop_future, timeout=10.0))

        logging.info(f"stop_result:{stop_result}")
        assert_is_not_none(stop_result)

        # restart music streaming
        logging.info("restart music streaming")

        start_future = self.get_start_future(self.ref_left)

        await self.dut.aio.asha.WaitPeripheral(connection=dut_ref)
        _, start_result = await asyncio.gather(
            self.dut.aio.asha.Start(connection=dut_ref), asyncio.wait_for(start_future, timeout=3.0)
        )

        logging.info(f"start_result:{start_result}")
        assert_is_not_none(start_result)

    @asynchronous
    async def test_music_start_dual_device(self) -> None:
        """
        DUT discovers Ref.
        DUT initiates connection to Ref.
        Verify that DUT and Ref are bonded and connected.
        DUT starts media streaming.
        Verify that DUT sends a correct AudioControlPoint `Start` command (codec=1,
        audiotype=0, volume=<volume set on DUT>, otherstate=<state of Ref aux if dual devices>).
        """

        async def ref_device_connect(ref_device: BumblePandoraDevice, ear: Ear) -> Tuple[Connection, Connection]:
            advertisement = await self.ref_advertise_asha(ref_device=ref_device, ref_address_type=RANDOM, ear=ear)
            ref = await self.dut_scan_for_asha(dut_address_type=RANDOM, ear=ear)
            # DUT initiates connection to ref_device.
            dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, RANDOM)
            advertisement.cancel()

            return dut_ref, ref_dut

        # connect ref_left
        dut_ref_left, ref_left_dut = await ref_device_connect(self.ref_left, Ear.LEFT)
        le_psm_future_left = self.get_le_psm_future(self.ref_left)
        read_only_properties_future_left = self.get_read_only_properties_future(self.ref_left)

        # DUT starts pairing with the ref_left
        (secure_left, wait_security_left) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref_left, le=LE_LEVEL3),
            self.ref_left.aio.security.WaitSecurity(connection=ref_left_dut, le=LE_LEVEL3),
        )

        assert_equal(secure_left.result_variant(), 'success')
        assert_equal(wait_security_left.result_variant(), 'success')

        le_psm_out_result_left = await asyncio.wait_for(le_psm_future_left, timeout=3.0)
        assert_is_not_none(le_psm_out_result_left)

        read_only_properties_result_left = await asyncio.wait_for(read_only_properties_future_left, timeout=3.0)
        assert_is_not_none(read_only_properties_result_left)

        start_future_left = self.get_start_future(self.ref_left)

        logging.info("send start")
        await self.dut.aio.asha.WaitPeripheral(connection=dut_ref_left)
        _, start_result_left = await asyncio.gather(
            self.dut.aio.asha.Start(connection=dut_ref_left), asyncio.wait_for(start_future_left, timeout=3.0)
        )

        logging.info(f"start_result_left:{start_result_left}")
        assert_is_not_none(start_result_left)
        assert_equal(start_result_left['codec'], 1)
        assert_equal(start_result_left['audiotype'], 0)
        assert_is_not_none(start_result_left['volume'])
        assert_equal(start_result_left['otherstate'], 0)

        # connect ref_right
        dut_ref_right, ref_right_dut = await ref_device_connect(self.ref_right, Ear.RIGHT)
        le_psm_future_right = self.get_le_psm_future(self.ref_right)
        read_only_properties_future_right = self.get_read_only_properties_future(self.ref_right)

        # DUT starts pairing with the ref_right
        (secure_right, wait_security_right) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref_right, le=LE_LEVEL3),
            self.ref_right.aio.security.WaitSecurity(connection=ref_right_dut, le=LE_LEVEL3),
        )

        assert_equal(secure_right.result_variant(), 'success')
        assert_equal(wait_security_right.result_variant(), 'success')

        le_psm_out_result_right = await asyncio.wait_for(le_psm_future_right, timeout=3.0)
        assert_is_not_none(le_psm_out_result_right)

        read_only_properties_result_right = await asyncio.wait_for(read_only_properties_future_right, timeout=3.0)
        assert_is_not_none(read_only_properties_result_right)

        start_future_right = self.get_start_future(self.ref_right)

        logging.info("send start_right")
        await self.dut.aio.asha.WaitPeripheral(connection=dut_ref_right)
        start_result_right = await asyncio.wait_for(start_future_right, timeout=10.0)

        logging.info(f"start_result_right:{start_result_right}")
        assert_is_not_none(start_result_right)
        assert_equal(start_result_right['codec'], 1)
        assert_equal(start_result_right['audiotype'], 0)
        assert_is_not_none(start_result_right['volume'])
        # ref_left already connected, otherstate = 1
        assert_equal(start_result_right['otherstate'], 1)

    @asynchronous
    async def test_music_stop_dual_device(self) -> None:
        """
        DUT discovers Refs.
        DUT initiates connection to Refs.
        Verify that DUT and Refs are bonded and connected.
        DUT is streaming media to Refs.
        DUT stops media streaming on Refs.
        Verify that DUT sends a correct AudioControlPoint `Stop` command.
        Verify Refs cannot recevice audio data after DUT stops media streaming.
        """

        async def ref_device_connect(ref_device: BumblePandoraDevice, ear: Ear) -> Tuple[Connection, Connection]:
            advertisement = await self.ref_advertise_asha(ref_device=ref_device, ref_address_type=RANDOM, ear=ear)
            ref = await self.dut_scan_for_asha(dut_address_type=RANDOM, ear=ear)
            # DUT initiates connection to ref_device.
            dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, RANDOM)
            advertisement.cancel()

            return dut_ref, ref_dut

        # DUT starts connecting, pairing with the ref_left
        dut_ref_left, ref_left_dut = await ref_device_connect(self.ref_left, Ear.LEFT)
        (secure_left, wait_security_left) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref_left, le=LE_LEVEL3),
            self.ref_left.aio.security.WaitSecurity(connection=ref_left_dut, le=LE_LEVEL3),
        )
        assert_equal(secure_left.result_variant(), 'success')
        assert_equal(wait_security_left.result_variant(), 'success')

        # DUT starts connecting, pairing with the ref_right
        dut_ref_right, ref_right_dut = await ref_device_connect(self.ref_right, Ear.RIGHT)
        (secure_right, wait_security_right) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref_right, le=LE_LEVEL3),
            self.ref_right.aio.security.WaitSecurity(connection=ref_right_dut, le=LE_LEVEL3),
        )
        assert_equal(secure_right.result_variant(), 'success')
        assert_equal(wait_security_right.result_variant(), 'success')

        await asyncio.gather(
            self.dut.aio.asha.WaitPeripheral(connection=dut_ref_left),
            self.dut.aio.asha.WaitPeripheral(connection=dut_ref_right),
        )
        await self.dut.aio.asha.Start(connection=dut_ref_left)

        # Stop audio and wait until ref_device connections stopped.
        stop_future_left = self.get_stop_future(self.ref_left)
        stop_future_right = self.get_stop_future(self.ref_right)

        logging.info("send stop")
        _, stop_result_left, stop_result_right = await asyncio.gather(
            self.dut.aio.asha.Stop(),
            asyncio.wait_for(stop_future_left, timeout=10.0),
            asyncio.wait_for(stop_future_right, timeout=10.0),
        )

        logging.info(f"stop_result_left:{stop_result_left}")
        logging.info(f"stop_result_right:{stop_result_right}")
        assert_is_not_none(stop_result_left)
        assert_is_not_none(stop_result_right)

        # Sleep 0.5 second to mitigate flaky test first.
        await asyncio.sleep(0.5)

        (audio_data_left, audio_data_right) = await asyncio.gather(
            self.get_audio_data(self.ref_left, connection=ref_left_dut, timeout=10),
            self.get_audio_data(self.ref_right, connection=ref_right_dut, timeout=10),
        )

        assert_equal(len(audio_data_left), 0)
        assert_equal(len(audio_data_right), 0)

    @asynchronous
    async def test_music_audio_playback(self) -> None:
        """
        DUT discovers Ref.
        DUT initiates connection to Ref.
        Verify that DUT and Ref are bonded and connected.
        DUT is streaming media to Ref using playback API.
        Verify that Ref has received audio data.
        """

        async def ref_device_connect(ref_device: BumblePandoraDevice, ear: Ear) -> Tuple[Connection, Connection]:
            advertisement = await self.ref_advertise_asha(ref_device=ref_device, ref_address_type=RANDOM, ear=ear)
            ref = await self.dut_scan_for_asha(dut_address_type=RANDOM, ear=ear)
            # DUT initiates connection to ref_device.
            dut_ref, ref_dut = await self.dut_connect_to_ref(advertisement, ref, RANDOM)
            advertisement.cancel()

            return dut_ref, ref_dut

        dut_ref_left, ref_left_dut = await ref_device_connect(self.ref_left, Ear.LEFT)

        # DUT starts pairing with the ref_left
        (secure_left, wait_security_left) = await asyncio.gather(
            self.dut.aio.security.Secure(connection=dut_ref_left, le=LE_LEVEL3),
            self.ref_left.aio.security.WaitSecurity(connection=ref_left_dut, le=LE_LEVEL3),
        )

        assert_equal(secure_left.result_variant(), 'success')
        assert_equal(wait_security_left.result_variant(), 'success')

        await self.dut.aio.asha.WaitPeripheral(connection=dut_ref_left)
        await self.dut.aio.asha.Start(connection=dut_ref_left)

        # Clear audio data before start audio playback testing
        await self.get_audio_data(ref_device=self.ref_left, connection=ref_left_dut, timeout=10)

        generated_audio = self.generate_sine(connection=dut_ref_left)

        _, audio_data = await asyncio.gather(
            self.dut.aio.asha.PlaybackAudio(generated_audio),
            self.get_audio_data(ref_device=self.ref_left, connection=ref_left_dut, timeout=10),
        )

        assert_not_equal(len(audio_data), 0)
        # TODO(duoho): decode audio_data and verify the content


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()  # type: ignore
