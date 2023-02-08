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
import bumble.device
import grpc
import grpc.aio
import logging
import struct

from avatar.bumble_server.utils import BumbleServerLoggerAdapter, address_from_request
from bumble.core import BT_BR_EDR_TRANSPORT, BT_LE_TRANSPORT, UUID, AdvertisingData, ConnectionError
from bumble.device import (
    DEVICE_DEFAULT_SCAN_INTERVAL,
    DEVICE_DEFAULT_SCAN_WINDOW,
    Advertisement,
    AdvertisingType,
    Connection as BumbleConnection,
    Device,
)
from bumble.gatt import Service
from bumble.hci import (
    HCI_CONNECTION_ALREADY_EXISTS_ERROR,
    HCI_PAGE_TIMEOUT_ERROR,
    HCI_REMOTE_USER_TERMINATED_CONNECTION_ERROR,
    Address,
    HCI_Error,
)
from google.protobuf import any_pb2, empty_pb2
from pandora.host_grpc import (
    ConnectabilityMode,
    Connection,
    ConnectLERequest,
    ConnectLEResponse,
    ConnectRequest,
    ConnectResponse,
    DataTypes,
    DisconnectRequest,
    DiscoverabilityMode,
    GetConnectionRequest,
    GetConnectionResponse,
    GetLEConnectionRequest,
    GetLEConnectionResponse,
    GetRemoteNameRequest,
    GetRemoteNameResponse,
    InquiryResponse,
    PrimaryPhy,
    ReadLocalAddressResponse,
    ScanningResponse,
    ScanRequest,
    SecondaryPhy,
    SetConnectabilityModeRequest,
    SetDiscoverabilityModeRequest,
    StartAdvertisingRequest,
    StartAdvertisingResponse,
    StopAdvertisingRequest,
    WaitConnectionRequest,
    WaitConnectionResponse,
    WaitDisconnectionRequest,
    WaitLEConnectionRequest,
    WaitLEConnectionResponse,
)
from pandora.host_grpc_aio import HostServicer
from typing import AsyncGenerator, Dict, List, Optional, Tuple, Union, cast

PRIMARY_PHY_MAP: Dict[int, PrimaryPhy] = {1: PrimaryPhy.PRIMARY_1M, 3: PrimaryPhy.PRIMARY_CODED}

SECONDARY_PHY_MAP: Dict[int, SecondaryPhy] = {
    0: SecondaryPhy.SECONDARY_NONE,
    1: SecondaryPhy.SECONDARY_1M,
    2: SecondaryPhy.SECONDARY_2M,
    3: SecondaryPhy.SECONDARY_CODED,
}


class HostService(HostServicer):
    grpc_server: grpc.aio.Server
    device: Device
    scan_queue: asyncio.Queue[Advertisement]
    inquiry_queue: asyncio.Queue[Optional[Tuple[Address, int, AdvertisingData, int]]]

    def __init__(self, grpc_server: grpc.aio.Server, device: Device) -> None:
        super().__init__()
        self.log = BumbleServerLoggerAdapter(logging.getLogger(), {'service_name': 'Host', 'device': device})
        self.grpc_server = grpc_server
        self.device = device
        self.scan_queue = asyncio.Queue()
        self.inquiry_queue = asyncio.Queue()

    async def FactoryReset(self, request: empty_pb2.Empty, context: grpc.ServicerContext) -> empty_pb2.Empty:
        self.log.info('FactoryReset')

        # delete all bonds
        if self.device.keystore is not None:
            await self.device.keystore.delete_all()

        # trigger gRCP server stop then return
        asyncio.create_task(self.grpc_server.stop(None))
        return empty_pb2.Empty()

    async def Reset(self, request: empty_pb2.Empty, context: grpc.ServicerContext) -> empty_pb2.Empty:
        self.log.info('Reset')

        # (re) power device on
        await self.device.power_on()
        return empty_pb2.Empty()

    async def ReadLocalAddress(
        self, request: empty_pb2.Empty, context: grpc.ServicerContext
    ) -> ReadLocalAddressResponse:
        self.log.info('ReadLocalAddress')
        return ReadLocalAddressResponse(address=bytes(reversed(bytes(self.device.public_address))))

    async def Connect(self, request: ConnectRequest, context: grpc.ServicerContext) -> ConnectResponse:
        # Need to reverse bytes order since Bumble Address is using MSB.
        address = Address(bytes(reversed(request.address)), address_type=Address.PUBLIC_DEVICE_ADDRESS)
        self.log.info(f"Connect: {address}")

        try:
            self.log.info("Connecting...")
            connection = await self.device.connect(address, transport=BT_BR_EDR_TRANSPORT)
            self.log.info("Connected")
        except ConnectionError as e:
            if e.error_code == HCI_PAGE_TIMEOUT_ERROR:
                self.log.warning(f"Peer not found: {e}")
                return ConnectResponse(peer_not_found=empty_pb2.Empty())
            if e.error_code == HCI_CONNECTION_ALREADY_EXISTS_ERROR:
                self.log.warning(f"Connection already exists: {e}")
                return ConnectResponse(connection_already_exists=empty_pb2.Empty())
            raise e

        self.log.info(f"Connect: connection handle: {connection.handle}")
        cookie = any_pb2.Any(value=connection.handle.to_bytes(4, 'big'))
        return ConnectResponse(connection=Connection(cookie=cookie))

    async def GetConnection(
        self, request: GetConnectionRequest, context: grpc.ServicerContext
    ) -> GetConnectionResponse:
        # Need to reverse bytes order since Bumble Address is using MSB.
        address = Address(bytes(reversed(request.address)))
        self.log.info(f"GetConnection: {address}")

        if not (connection := self.device.find_connection_by_bd_addr(address, transport=BT_BR_EDR_TRANSPORT)):
            return GetConnectionResponse(peer_not_found=empty_pb2.Empty())

        cookie = any_pb2.Any(value=connection.handle.to_bytes(4, 'big'))
        return GetConnectionResponse(connection=Connection(cookie=cookie))

    async def WaitConnection(
        self, request: WaitConnectionRequest, context: grpc.ServicerContext
    ) -> WaitConnectionResponse:
        # Need to reverse bytes order since Bumble Address is using MSB.
        if request.address:
            address = Address(bytes(reversed(request.address)), address_type=Address.PUBLIC_DEVICE_ADDRESS)
            self.log.info(f"WaitConnection: {address}")

            if connection := self.device.find_connection_by_bd_addr(address, transport=BT_BR_EDR_TRANSPORT):
                cookie = any_pb2.Any(value=connection.handle.to_bytes(4, 'big'))
                return WaitConnectionResponse(connection=Connection(cookie=cookie))
        else:
            address = Address.ANY
            self.log.info(f"WaitConnection: {address}")

        self.log.info("Wait connection...")
        connection = await self.device.accept(address)
        self.log.info("Connected")

        self.log.info(f"WaitConnection: connection handle: {connection.handle}")
        cookie = any_pb2.Any(value=connection.handle.to_bytes(4, 'big'))
        return WaitConnectionResponse(connection=Connection(cookie=cookie))

    async def ConnectLE(self, request: ConnectLERequest, context: grpc.ServicerContext) -> ConnectLEResponse:
        address = address_from_request(request, request.WhichOneof("address"))
        self.log.info(f"ConnectLE: {address}")

        try:
            self.log.info("Connecting...")
            connection: BumbleConnection = await self.device.connect(
                address, transport=BT_LE_TRANSPORT, own_address_type=request.own_address_type
            )
            self.log.info("Connected")
        except ConnectionError as e:
            if e.error_code == HCI_PAGE_TIMEOUT_ERROR:
                self.log.warning(f"Peer not found: {e}")
                return ConnectLEResponse(peer_not_found=empty_pb2.Empty())
            if e.error_code == HCI_CONNECTION_ALREADY_EXISTS_ERROR:
                self.log.warning(f"Connection already exists: {e}")
                return ConnectLEResponse(connection_already_exists=empty_pb2.Empty())
            raise e

        self.log.info(f"ConnectLE: connection handle: {connection.handle}")
        cookie = any_pb2.Any(value=connection.handle.to_bytes(4, 'big'))
        return ConnectLEResponse(connection=Connection(cookie=cookie))

    async def GetLEConnection(
        self, request: GetLEConnectionRequest, context: grpc.ServicerContext
    ) -> GetLEConnectionResponse:
        address = address_from_request(request, request.WhichOneof("address"))
        self.log.info(f"GetLEConnection: {address}")

        connection = self.device.find_connection_by_bd_addr(
            address, transport=BT_LE_TRANSPORT, check_address_type=True
        )

        if not connection:
            return GetLEConnectionResponse(peer_not_found=empty_pb2.Empty())

        cookie = any_pb2.Any(value=connection.handle.to_bytes(4, 'big'))
        return GetLEConnectionResponse(connection=Connection(cookie=cookie))

    async def WaitLEConnection(
        self, request: WaitLEConnectionRequest, context: grpc.ServicerContext
    ) -> WaitLEConnectionResponse:
        if request.address:
            address = address_from_request(request, request.WhichOneof("address"))
        else:
            address = Address.ANY

        self.log.info(f"WaitLEConnection: {address}")

        if address != Address.ANY:
            if conn := self.device.find_connection_by_bd_addr(
                address, transport=BT_LE_TRANSPORT, check_address_type=True
            ):
                cookie = any_pb2.Any(value=conn.handle.to_bytes(4, 'big'))
                return WaitLEConnectionResponse(connection=Connection(cookie=cookie))

        pending_connection: asyncio.Future[bumble.device.Connection] = asyncio.get_running_loop().create_future()

        if address != Address.ANY:

            def on_connection(connection: bumble.device.Connection) -> None:
                if connection.transport == BT_LE_TRANSPORT and connection.peer_address == address:
                    pending_connection.set_result(connection)

            def on_connection_failure(error: ConnectionError) -> None:
                if connection.transport == BT_LE_TRANSPORT and connection.peer_address == address:
                    pending_connection.set_exception(error)

        else:

            def on_connection(connection: bumble.device.Connection) -> None:
                if connection.transport == BT_LE_TRANSPORT:
                    pending_connection.set_result(connection)

            def on_connection_failure(error: ConnectionError) -> None:
                if connection.transport == BT_LE_TRANSPORT:
                    pending_connection.set_exception(error)

        self.device.on('connection', on_connection)
        self.device.on('connection_failure', on_connection_failure)

        try:
            connection = await pending_connection
            cookie = any_pb2.Any(value=connection.handle.to_bytes(4, 'big'))
            return WaitLEConnectionResponse(connection=Connection(cookie=cookie))
        finally:
            self.device.remove_listener('connection', on_connection)  # type: ignore
            self.device.remove_listener('connection_failure', on_connection_failure)  # type: ignore

    async def Disconnect(self, request: DisconnectRequest, context: grpc.ServicerContext) -> empty_pb2.Empty:
        connection_handle = int.from_bytes(request.connection.cookie.value, 'big')
        self.log.info(f"Disconnect: {connection_handle}")

        self.log.info("Disconnecting...")
        if connection := self.device.lookup_connection(connection_handle):
            await connection.disconnect(HCI_REMOTE_USER_TERMINATED_CONNECTION_ERROR)
        self.log.info("Disconnected")

        return empty_pb2.Empty()

    async def WaitDisconnection(
        self, request: WaitDisconnectionRequest, context: grpc.ServicerContext
    ) -> empty_pb2.Empty:
        connection_handle = int.from_bytes(request.connection.cookie.value, 'big')
        self.log.info(f"WaitDisconnection: {connection_handle}")

        if connection := self.device.lookup_connection(connection_handle):
            disconnection_future: asyncio.Future[None] = asyncio.get_running_loop().create_future()

            def on_disconnection(_: None) -> None:
                disconnection_future.set_result(None)

            connection.on('disconnection', on_disconnection)
            await disconnection_future
            self.log.info("Disconnected")

        return empty_pb2.Empty()

    # TODO: use advertising set commands
    async def StartAdvertising(
        self, request: StartAdvertisingRequest, context: grpc.ServicerContext
    ) -> StartAdvertisingResponse:
        # TODO: add support for extended advertising in Bumble
        # TODO: add support for `request.interval`
        # TODO: add support for `request.interval_range`
        # TODO: add support for `request.primary_phy`
        # TODO: add support for `request.secondary_phy`
        assert request.legacy
        assert not request.interval
        assert not request.interval_range
        assert not request.primary_phy
        assert not request.secondary_phy

        self.log.info('StartAdvertising')

        if data := request.data:
            self.device.advertising_data = bytes(self.unpack_data_types(data))

            if scan_response_data := request.scan_response_data:
                self.device.scan_response_data = bytes(self.unpack_data_types(scan_response_data))
                scannable = True
            else:
                scannable = False

            # Retrieve services data
            for service in self.device.gatt_server.attributes:
                if isinstance(service, Service) and (service_data := service.get_advertising_data()):
                    service_uuid = service.uuid.to_hex_str()
                    if (
                        service_uuid in request.data.incomplete_service_class_uuids16
                        or service_uuid in request.data.complete_service_class_uuids16
                        or service_uuid in request.data.incomplete_service_class_uuids32
                        or service_uuid in request.data.complete_service_class_uuids32
                        or service_uuid in request.data.incomplete_service_class_uuids128
                        or service_uuid in request.data.complete_service_class_uuids128
                    ):
                        self.device.advertising_data += service_data
                    if (
                        service_uuid in scan_response_data.incomplete_service_class_uuids16
                        or service_uuid in scan_response_data.complete_service_class_uuids16
                        or service_uuid in scan_response_data.incomplete_service_class_uuids32
                        or service_uuid in scan_response_data.complete_service_class_uuids32
                        or service_uuid in scan_response_data.incomplete_service_class_uuids128
                        or service_uuid in scan_response_data.complete_service_class_uuids128
                    ):
                        self.device.scan_response_data += service_data

            target = None
            if request.connectable and scannable:
                advertising_type = AdvertisingType.UNDIRECTED_CONNECTABLE_SCANNABLE
            elif scannable:
                advertising_type = AdvertisingType.UNDIRECTED_SCANNABLE
            else:
                advertising_type = AdvertisingType.UNDIRECTED
        else:
            target = None
            advertising_type = AdvertisingType.UNDIRECTED

        if request.target:
            # Need to reverse bytes order since Bumble Address is using MSB.
            target_bytes = bytes(reversed(request.target))
            if request.target_variant == "public":
                target = Address(target_bytes, Address.PUBLIC_DEVICE_ADDRESS)
                advertising_type = AdvertisingType.DIRECTED_CONNECTABLE_HIGH_DUTY  # FIXME: HIGH_DUTY ?
            else:
                target = Address(target_bytes, Address.RANDOM_DEVICE_ADDRESS)
                advertising_type = AdvertisingType.DIRECTED_CONNECTABLE_HIGH_DUTY  # FIXME: HIGH_DUTY ?

        await self.device.start_advertising(
            target=target, advertising_type=advertising_type, own_address_type=request.own_address_type
        )

        # FIXME: wait for advertising sets to have a correct set, use `None` for now
        return StartAdvertisingResponse()

    # TODO: use advertising set commands
    async def StopAdvertising(self, request: StopAdvertisingRequest, context: grpc.ServicerContext) -> empty_pb2.Empty:
        self.log.info('StopAdvertising')
        await self.device.stop_advertising()
        return empty_pb2.Empty()

    async def Scan(
        self, request: ScanRequest, context: grpc.ServicerContext
    ) -> AsyncGenerator[ScanningResponse, None]:
        # TODO: add support for `request.phys`
        # TODO: modify `start_scanning` to accept floats instead of int for ms values
        assert not request.phys

        self.log.info('Scan')

        handler = self.device.on('advertisement', self.scan_queue.put_nowait)
        await self.device.start_scanning(
            legacy=request.legacy,
            active=not request.passive,
            own_address_type=request.own_address_type,
            scan_interval=int(request.interval) if request.interval else DEVICE_DEFAULT_SCAN_INTERVAL,
            scan_window=int(request.window) if request.window else DEVICE_DEFAULT_SCAN_WINDOW,
        )

        try:
            # TODO: add support for `direct_address` in Bumble
            # TODO: add support for `periodic_advertising_interval` in Bumble
            while adv := await self.scan_queue.get():
                sr = ScanningResponse(
                    legacy=adv.is_legacy,
                    connectable=adv.is_connectable,
                    scannable=adv.is_scannable,
                    truncated=adv.is_truncated,
                    sid=adv.sid,
                    primary_phy=PRIMARY_PHY_MAP[adv.primary_phy],
                    secondary_phy=SECONDARY_PHY_MAP[adv.secondary_phy],
                    tx_power=adv.tx_power,
                    rssi=adv.rssi,
                    data=self.pack_data_types(adv.data),
                )

                if adv.address.address_type == Address.PUBLIC_DEVICE_ADDRESS:
                    sr.public = bytes(reversed(bytes(adv.address)))
                elif adv.address.address_type == Address.RANDOM_DEVICE_ADDRESS:
                    sr.random = bytes(reversed(bytes(adv.address)))
                elif adv.address.address_type == Address.PUBLIC_IDENTITY_ADDRESS:
                    sr.public_identity = bytes(reversed(bytes(adv.address)))
                else:
                    sr.random_static_identity = bytes(reversed(bytes(adv.address)))

                yield sr

        finally:
            self.device.remove_listener('advertisement', handler)  # type: ignore
            self.scan_queue = asyncio.Queue()
            await self.device.abort_on('flush', self.device.stop_scanning())

    async def Inquiry(
        self, request: empty_pb2.Empty, context: grpc.ServicerContext
    ) -> AsyncGenerator[InquiryResponse, None]:
        self.log.info('Inquiry')

        complete_handler = self.device.on('inquiry_complete', lambda: self.inquiry_queue.put_nowait(None))
        result_handler = self.device.on(  # type: ignore
            'inquiry_result',
            lambda address, class_of_device, eir_data, rssi: self.inquiry_queue.put_nowait(  # type: ignore
                (address, class_of_device, eir_data, rssi)  # type: ignore
            ),
        )

        await self.device.start_discovery(auto_restart=False)
        try:
            while inquiry_result := await self.inquiry_queue.get():
                (address, class_of_device, eir_data, rssi) = inquiry_result
                # FIXME: if needed, add support for `page_scan_repetition_mode` and `clock_offset` in Bumble
                yield InquiryResponse(
                    address=bytes(reversed(bytes(address))),
                    class_of_device=class_of_device,
                    rssi=rssi,
                    data=self.pack_data_types(eir_data),
                )

        finally:
            self.device.remove_listener('inquiry_complete', complete_handler)  # type: ignore
            self.device.remove_listener('inquiry_result', result_handler)  # type: ignore
            self.inquiry_queue = asyncio.Queue()
            await self.device.abort_on('flush', self.device.stop_discovery())

    async def SetDiscoverabilityMode(
        self, request: SetDiscoverabilityModeRequest, context: grpc.ServicerContext
    ) -> empty_pb2.Empty:
        self.log.info("SetDiscoverabilityMode")
        await self.device.set_discoverable(request.mode != DiscoverabilityMode.NOT_DISCOVERABLE)
        return empty_pb2.Empty()

    async def SetConnectabilityMode(
        self, request: SetConnectabilityModeRequest, context: grpc.ServicerContext
    ) -> empty_pb2.Empty:
        self.log.info("SetConnectabilityMode")
        await self.device.set_connectable(request.mode != ConnectabilityMode.NOT_CONNECTABLE)
        return empty_pb2.Empty()

    async def GetRemoteName(
        self, request: GetRemoteNameRequest, context: grpc.ServicerContext
    ) -> GetRemoteNameResponse:
        remote: Union[Address, BumbleConnection]
        if request.remote_variant == 'connection':
            assert request.connection
            connection_handle = int.from_bytes(request.connection.cookie.value, 'big')
            self.log.info(f"GetRemoteName: {connection_handle}")

            connection = self.device.lookup_connection(connection_handle)
            assert connection
            remote = connection
        else:
            # Need to reverse bytes order since Bumble Address is using MSB.
            assert request.address
            remote = Address(bytes(reversed(request.address)), address_type=Address.PUBLIC_DEVICE_ADDRESS)
            self.log.info(f"GetRemoteName: {remote}")

        try:
            assert remote
            remote_name = await self.device.request_remote_name(remote)
            return GetRemoteNameResponse(name=remote_name)
        except HCI_Error as e:
            if e.error_code == HCI_PAGE_TIMEOUT_ERROR:
                self.log.warning(f"Peer not found: {e}")
                return GetRemoteNameResponse(remote_not_found=empty_pb2.Empty())
            raise e

    def unpack_data_types(self, dt: DataTypes) -> AdvertisingData:
        ad_structures: List[Tuple[int, bytes]] = []

        uuids: List[str]
        datas: Dict[str, bytes]

        if uuids := dt.incomplete_service_class_uuids16:
            ad_structures.append(
                (
                    AdvertisingData.INCOMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
                    b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in uuids]),
                )
            )
        if uuids := dt.complete_service_class_uuids16:
            ad_structures.append(
                (
                    AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
                    b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in uuids]),
                )
            )
        if uuids := dt.incomplete_service_class_uuids32:
            ad_structures.append(
                (
                    AdvertisingData.INCOMPLETE_LIST_OF_32_BIT_SERVICE_CLASS_UUIDS,
                    b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in uuids]),
                )
            )
        if uuids := dt.complete_service_class_uuids32:
            ad_structures.append(
                (
                    AdvertisingData.COMPLETE_LIST_OF_32_BIT_SERVICE_CLASS_UUIDS,
                    b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in uuids]),
                )
            )
        if uuids := dt.incomplete_service_class_uuids128:
            ad_structures.append(
                (
                    AdvertisingData.INCOMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS,
                    b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in uuids]),
                )
            )
        if uuids := dt.complete_service_class_uuids128:
            ad_structures.append(
                (
                    AdvertisingData.COMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS,
                    b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in uuids]),
                )
            )
        if dt.HasField('include_shortened_local_name'):
            ad_structures.append((AdvertisingData.SHORTENED_LOCAL_NAME, bytes(self.device.name[:8], 'utf-8')))
        elif dt.shortened_local_name:
            ad_structures.append((AdvertisingData.SHORTENED_LOCAL_NAME, bytes(dt.shortened_local_name, 'utf-8')))
        if dt.HasField('include_complete_local_name'):
            ad_structures.append((AdvertisingData.COMPLETE_LOCAL_NAME, bytes(self.device.name, 'utf-8')))
        elif dt.complete_local_name:
            ad_structures.append((AdvertisingData.COMPLETE_LOCAL_NAME, bytes(dt.complete_local_name, 'utf-8')))
        if dt.HasField('include_tx_power_level'):
            raise ValueError('unsupported data type')
        elif dt.tx_power_level:
            ad_structures.append((AdvertisingData.TX_POWER_LEVEL, bytes(struct.pack('<I', dt.tx_power_level)[:1])))
        if dt.HasField('include_class_of_device'):
            ad_structures.append(
                (AdvertisingData.CLASS_OF_DEVICE, bytes(struct.pack('<I', self.device.class_of_device)[:-1]))
            )
        elif dt.class_of_device:
            ad_structures.append((AdvertisingData.CLASS_OF_DEVICE, bytes(struct.pack('<I', dt.class_of_device)[:-1])))
        if dt.peripheral_connection_interval_min:
            ad_structures.append(
                (
                    AdvertisingData.PERIPHERAL_CONNECTION_INTERVAL_RANGE,
                    bytes(
                        [
                            *struct.pack('<H', dt.peripheral_connection_interval_min),
                            *struct.pack(
                                '<H',
                                dt.peripheral_connection_interval_max
                                if dt.peripheral_connection_interval_max
                                else dt.peripheral_connection_interval_min,
                            ),
                        ]
                    ),
                )
            )
        if uuids := dt.service_solicitation_uuids16:
            ad_structures.append(
                (
                    AdvertisingData.LIST_OF_16_BIT_SERVICE_SOLICITATION_UUIDS,
                    b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in uuids]),
                )
            )
        if uuids := dt.service_solicitation_uuids32:
            ad_structures.append(
                (
                    AdvertisingData.LIST_OF_32_BIT_SERVICE_SOLICITATION_UUIDS,
                    b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in uuids]),
                )
            )
        if uuids := dt.service_solicitation_uuids128:
            ad_structures.append(
                (
                    AdvertisingData.LIST_OF_128_BIT_SERVICE_SOLICITATION_UUIDS,
                    b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in uuids]),
                )
            )
        if datas := dt.service_data_uuid16:
            ad_structures.extend(
                [
                    (AdvertisingData.SERVICE_DATA_16_BIT_UUID, bytes.fromhex(uuid) + data)
                    for uuid, data in datas.items()
                ]
            )
        if datas := dt.service_data_uuid32:
            ad_structures.extend(
                [
                    (AdvertisingData.SERVICE_DATA_32_BIT_UUID, bytes.fromhex(uuid) + data)
                    for uuid, data in datas.items()
                ]
            )
        if datas := dt.service_data_uuid128:
            ad_structures.extend(
                [
                    (AdvertisingData.SERVICE_DATA_128_BIT_UUID, bytes.fromhex(uuid) + data)
                    for uuid, data in datas.items()
                ]
            )
        if dt.appearance:
            ad_structures.append((AdvertisingData.APPEARANCE, struct.pack('<H', dt.appearance)))
        if dt.advertising_interval:
            ad_structures.append((AdvertisingData.ADVERTISING_INTERVAL, struct.pack('<H', dt.advertising_interval)))
        if dt.uri:
            ad_structures.append((AdvertisingData.URI, bytes(dt.uri, 'utf-8')))
        if dt.le_supported_features:
            ad_structures.append((AdvertisingData.LE_SUPPORTED_FEATURES, dt.le_supported_features))
        if dt.manufacturer_specific_data:
            ad_structures.append((AdvertisingData.MANUFACTURER_SPECIFIC_DATA, dt.manufacturer_specific_data))

        return AdvertisingData(ad_structures)

    def pack_data_types(self, ad: AdvertisingData) -> DataTypes:
        dt = DataTypes()
        uuids: List[UUID]
        s: str
        i: int
        ij: Tuple[int, int]
        uuid_data: Tuple[UUID, bytes]
        data: bytes

        if uuids := cast(List[UUID], ad.get(AdvertisingData.INCOMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS)):
            dt.incomplete_service_class_uuids16.extend(list(map(lambda x: x.to_hex_str(), uuids)))
        if uuids := cast(List[UUID], ad.get(AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS)):
            dt.complete_service_class_uuids16.extend(list(map(lambda x: x.to_hex_str(), uuids)))
        if uuids := cast(List[UUID], ad.get(AdvertisingData.INCOMPLETE_LIST_OF_32_BIT_SERVICE_CLASS_UUIDS)):
            dt.incomplete_service_class_uuids32.extend(list(map(lambda x: x.to_hex_str(), uuids)))
        if uuids := cast(List[UUID], ad.get(AdvertisingData.COMPLETE_LIST_OF_32_BIT_SERVICE_CLASS_UUIDS)):
            dt.complete_service_class_uuids32.extend(list(map(lambda x: x.to_hex_str(), uuids)))
        if uuids := cast(List[UUID], ad.get(AdvertisingData.INCOMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS)):
            dt.incomplete_service_class_uuids128.extend(list(map(lambda x: x.to_hex_str(), uuids)))
        if uuids := cast(List[UUID], ad.get(AdvertisingData.COMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS)):
            dt.complete_service_class_uuids128.extend(list(map(lambda x: x.to_hex_str(), uuids)))
        if s := cast(str, ad.get(AdvertisingData.SHORTENED_LOCAL_NAME)):
            dt.shortened_local_name = s
        if s := cast(str, ad.get(AdvertisingData.COMPLETE_LOCAL_NAME)):
            dt.complete_local_name = s
        if i := cast(int, ad.get(AdvertisingData.TX_POWER_LEVEL)):
            dt.tx_power_level = i
        if i := cast(int, ad.get(AdvertisingData.CLASS_OF_DEVICE)):
            dt.class_of_device = i
        if ij := cast(Tuple[int, int], ad.get(AdvertisingData.PERIPHERAL_CONNECTION_INTERVAL_RANGE)):
            dt.peripheral_connection_interval_min = ij[0]
            dt.peripheral_connection_interval_max = ij[1]
        if uuids := cast(List[UUID], ad.get(AdvertisingData.LIST_OF_16_BIT_SERVICE_SOLICITATION_UUIDS)):
            dt.service_solicitation_uuids16.extend(list(map(lambda x: x.to_hex_str(), uuids)))
        if uuids := cast(List[UUID], ad.get(AdvertisingData.LIST_OF_32_BIT_SERVICE_SOLICITATION_UUIDS)):
            dt.service_solicitation_uuids32.extend(list(map(lambda x: x.to_hex_str(), uuids)))
        if uuids := cast(List[UUID], ad.get(AdvertisingData.LIST_OF_128_BIT_SERVICE_SOLICITATION_UUIDS)):
            dt.service_solicitation_uuids128.extend(list(map(lambda x: x.to_hex_str(), uuids)))
        if uuid_data := cast(Tuple[UUID, bytes], ad.get(AdvertisingData.SERVICE_DATA_16_BIT_UUID)):
            dt.service_data_uuid16[uuid_data[0].to_hex_str()] = uuid_data[1]
        if uuid_data := cast(Tuple[UUID, bytes], ad.get(AdvertisingData.SERVICE_DATA_32_BIT_UUID)):
            dt.service_data_uuid32[uuid_data[0].to_hex_str()] = uuid_data[1]
        if uuid_data := cast(Tuple[UUID, bytes], ad.get(AdvertisingData.SERVICE_DATA_128_BIT_UUID)):
            dt.service_data_uuid128[uuid_data[0].to_hex_str()] = uuid_data[1]
        if data := cast(bytes, ad.get(AdvertisingData.PUBLIC_TARGET_ADDRESS, raw=True)):
            dt.public_target_addresses.extend([data[i * 6 :: i * 6 + 6] for i in range(int(len(data) / 6))])
        if data := cast(bytes, ad.get(AdvertisingData.RANDOM_TARGET_ADDRESS, raw=True)):
            dt.random_target_addresses.extend([data[i * 6 :: i * 6 + 6] for i in range(int(len(data) / 6))])
        if i := cast(int, ad.get(AdvertisingData.APPEARANCE)):
            dt.appearance = i
        if i := cast(int, ad.get(AdvertisingData.ADVERTISING_INTERVAL)):
            dt.advertising_interval = i
        if s := cast(str, ad.get(AdvertisingData.URI)):
            dt.uri = s
        if data := cast(bytes, ad.get(AdvertisingData.LE_SUPPORTED_FEATURES, raw=True)):
            dt.le_supported_features = data
        if data := cast(bytes, ad.get(AdvertisingData.MANUFACTURER_SPECIFIC_DATA, raw=True)):
            dt.manufacturer_specific_data = data

        return dt
