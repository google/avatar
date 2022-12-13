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
import grpc
import struct

from avatar.bumble_server.utils import address_from_request

from bumble.core import (
    BT_BR_EDR_TRANSPORT, BT_LE_TRANSPORT,
    AdvertisingData, ConnectionError
)
from bumble.device import (
    DEVICE_DEFAULT_SCAN_INTERVAL, DEVICE_DEFAULT_SCAN_WINDOW,
    AdvertisingType, Device
)
from bumble.hci import (
    HCI_REMOTE_USER_TERMINATED_CONNECTION_ERROR, HCI_PAGE_TIMEOUT_ERROR,
    HCI_CONNECTION_ALREADY_EXISTS_ERROR,
    Address, HCI_Error
)
from bumble.gatt import (
    Service
)

from google.protobuf.empty_pb2 import Empty
from google.protobuf.any_pb2 import Any

from pandora.host_grpc import HostServicer
from pandora.host_pb2 import (
    DiscoverabilityMode, ConnectabilityMode,
    Connection, DataTypes
)
from pandora.host_pb2 import (
    ReadLocalAddressResponse,
    ConnectResponse, GetConnectionResponse, WaitConnectionResponse,
    ConnectLEResponse, GetLEConnectionResponse, WaitLEConnectionResponse,
    StartAdvertisingResponse, ScanningResponse, InquiryResponse,
    GetRemoteNameResponse
)


class HostService(HostServicer):

    def __init__(self, grpc_server: grpc.aio.Server, device: Device):
        super().__init__()
        self.grpc_server = grpc_server
        self.device = device
        self.scan_queue = asyncio.Queue()
        self.inquiry_queue = asyncio.Queue()

    async def start(self) -> "HostService":
        # According to `host.proto`:
        # At startup, the Host must be in BR/EDR connectable mode
        await self.device.set_discoverable(False)
        await self.device.set_connectable(True)
        return self

    async def FactoryReset(self, request, context):
        logging.info('FactoryReset')

        # delete all bonds
        if self.device.keystore is not None:
            await self.device.keystore.delete_all()

        # trigger gRCP server stop then return
        asyncio.create_task(self.grpc_server.stop(None))
        return Empty()

    async def Reset(self, request, context):
        logging.info('Reset')

        # (re) power device on
        await self.device.power_on()
        return Empty()

    async def ReadLocalAddress(self, request, context):
        logging.info('ReadLocalAddress')
        return ReadLocalAddressResponse(
            address=bytes(reversed(bytes(self.device.public_address))))

    async def Connect(self, request, context):
        # Need to reverse bytes order since Bumble Address is using MSB.
        address = Address(bytes(reversed(request.address)), address_type=Address.PUBLIC_DEVICE_ADDRESS)
        logging.info(f"Connect: {address}")

        try:
            logging.info("Connecting...")
            connection = await self.device.connect(address, transport=BT_BR_EDR_TRANSPORT)
            logging.info("Connected")
        except ConnectionError as e:
            if e.error_code == HCI_PAGE_TIMEOUT_ERROR:
                logging.warning(f"Peer not found: {e}")
                return ConnectResponse(peer_not_found=Empty())
            if e.error_code == HCI_CONNECTION_ALREADY_EXISTS_ERROR:
                logging.warning(f"Connection already exists: {e}")
                return ConnectResponse(connection_already_exists=Empty())
            raise e

        logging.info(f"Connect: connection handle: {connection.handle}")
        cookie = Any(value=connection.handle.to_bytes(4, 'big'))
        return ConnectResponse(connection=Connection(cookie=cookie))

    async def GetConnection(self, request, context):
        # Need to reverse bytes order since Bumble Address is using MSB.
        address = Address(bytes(reversed(request.address)))
        logging.info(f"GetConnection: {address}")

        connection = self.device.find_connection_by_bd_addr(
            address, transport=BT_BR_EDR_TRANSPORT)

        if not connection:
            return GetConnectionResponse(peer_not_found=Empty())

        cookie = Any(value=connection.handle.to_bytes(4, 'big'))
        return GetConnectionResponse(connection=Connection(cookie=cookie))

    async def WaitConnection(self, request, context):
        # Need to reverse bytes order since Bumble Address is using MSB.
        if request.address:
            address = Address(bytes(reversed(request.address)), address_type=Address.PUBLIC_DEVICE_ADDRESS)
            logging.info(f"WaitConnection: {address}")

            connection = self.device.find_connection_by_bd_addr(
                address, transport=BT_BR_EDR_TRANSPORT)

            if connection:
                cookie = Any(value=connection.handle.to_bytes(4, 'big'))
                return WaitConnectionResponse(connection=Connection(cookie=cookie))
        else:
            address = Address.ANY
            logging.info(f"WaitConnection: {address}")

        logging.info("Wait connection...")
        connection = await self.device.accept(address)
        logging.info("Connected")

        logging.info(f"WaitConnection: connection handle: {connection.handle}")
        cookie = Any(value=connection.handle.to_bytes(4, 'big'))
        return WaitConnectionResponse(connection=Connection(cookie=cookie))

    async def ConnectLE(self, request, context):
        address = address_from_request(request, request.WhichOneof("address"))
        logging.info(f"ConnectLE: {address}")

        try:
            logging.info("Connecting...")
            connection = await self.device.connect(address,
                transport=BT_LE_TRANSPORT, own_address_type=request.own_address_type)
            logging.info("Connected")
        except ConnectionError as e:
            if e.error_code == HCI_PAGE_TIMEOUT_ERROR:
                logging.warning(f"Peer not found: {e}")
                return ConnectLEResponse(peer_not_found=Empty())
            if e.error_code == HCI_CONNECTION_ALREADY_EXISTS_ERROR:
                logging.warning(f"Connection already exists: {e}")
                return ConnectLEResponse(connection_already_exists=Empty())
            raise e

        logging.info(f"ConnectLE: connection handle: {connection.handle}")
        cookie = Any(value=connection.handle.to_bytes(4, 'big'))
        return ConnectLEResponse(connection=Connection(cookie=cookie))

    async def GetLEConnection(self, request, context):
        address = address_from_request(request, request.WhichOneof("address"))
        logging.info(f"GetLEConnection: {address}")

        connection = self.device.find_connection_by_bd_addr(
            address, transport=BT_LE_TRANSPORT, check_address_type=True)

        if not connection:
            return GetLEConnectionResponse(peer_not_found=Empty())

        cookie = Any(value=connection.handle.to_bytes(4, 'big'))
        return GetLEConnectionResponse(connection=Connection(cookie=cookie))

    async def WaitLEConnection(self, request, context):
        address = address_from_request(request, request.WhichOneof("address"))
        logging.info(f"WaitLEConnection: {address}")

        connection = self.device.find_connection_by_bd_addr(
            address, transport=BT_LE_TRANSPORT, check_address_type=True)

        if connection:
            cookie = Any(value=connection.handle.to_bytes(4, 'big'))
            return WaitLEConnectionResponse(connection=Connection(cookie=cookie))

        pending_connection = asyncio.get_running_loop().create_future()
        handler = self.device.on('connection', lambda connection:
            pending_connection.set_result(connection)
                if connection.transport == BT_LE_TRANSPORT and connection.peer_address == address else None)
        failure_handler = self.device.on('connection_failure', lambda error:
            pending_connection.set_exception(error)
                if error.transport == BT_LE_TRANSPORT and error.peer_address == address else None)

        try:
            connection = await pending_connection
            cookie = Any(value=connection.handle.to_bytes(4, 'big'))
            return WaitLEConnectionResponse(connection=Connection(cookie=cookie))
        finally:
            self.device.remove_listener('connection', handler)
            self.device.remove_listener('connection_failure', failure_handler)

    async def Disconnect(self, request, context):
        connection_handle = int.from_bytes(request.connection.cookie.value, 'big')
        logging.info(f"Disconnect: {connection_handle}")

        logging.info("Disconnecting...")
        connection = self.device.lookup_connection(connection_handle)
        await connection.disconnect(HCI_REMOTE_USER_TERMINATED_CONNECTION_ERROR)
        logging.info("Disconnected")

        return Empty()

    async def WaitDisconnection(self, request, context):
        connection_handle = int.from_bytes(request.connection.cookie.value, 'big')
        logging.info(f"WaitDisconnection: {connection_handle}")

        if (connection := self.device.lookup_connection(connection_handle)):
            disconnection_future = asyncio.get_running_loop().create_future()
            connection.on('disconnection', lambda _: disconnection_future.set_result(True))
            await disconnection_future
            logging.info("Disconnected")

        return Empty()

    # TODO: use advertising set commands
    async def StartAdvertising(self, request, context):
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

        logging.info('StartAdvertising')

        if data := request.data:
            self.device.advertising_data = bytes(self.unpack_data_types(data))

            if scan_response_data := request.scan_response_data:
                self.device.scan_response_data = bytes(
                    self.unpack_data_types(scan_response_data))
                scannable = True
            else:
                scannable = False

            # Retrieve services data
            for service in self.device.gatt_server.attributes:
                if isinstance(service, Service) and (data := service.get_advertising_data()):
                    service_uuid = service.uuid.to_hex_str()
                    if (
                        service_uuid in request.data.incomplete_service_class_uuids16 or
                        service_uuid in request.data.complete_service_class_uuids16 or
                        service_uuid in request.data.incomplete_service_class_uuids32 or
                        service_uuid in request.data.complete_service_class_uuids32 or
                        service_uuid in request.data.incomplete_service_class_uuids128 or
                        service_uuid in request.data.complete_service_class_uuids128
                    ):
                        self.device.advertising_data += data
                    if (
                        service_uuid in scan_response_data.incomplete_service_class_uuids16 or
                        service_uuid in scan_response_data.complete_service_class_uuids16 or
                        service_uuid in scan_response_data.incomplete_service_class_uuids32 or
                        service_uuid in scan_response_data.complete_service_class_uuids32 or
                        service_uuid in scan_response_data.incomplete_service_class_uuids128 or
                        service_uuid in scan_response_data.complete_service_class_uuids128
                    ):
                        self.device.scan_response_data += data

            target = None
            if request.connectable and scannable:
                advertising_type = AdvertisingType.UNDIRECTED_CONNECTABLE_SCANNABLE
            elif scannable:
                advertising_type = AdvertisingType.UNDIRECTED_SCANNABLE
            else:
                advertising_type = AdvertisingType.UNDIRECTED

        # Need to reverse bytes order since Bumble Address is using MSB.
        if request.WhichOneof("target") == "public":
            target = Address(bytes(reversed(request.public)), Address.PUBLIC_DEVICE_ADDRESS)
            advertising_type =  AdvertisingType.DIRECTED_CONNECTABLE_HIGH_DUTY  # FIXME: HIGH_DUTY ?
        elif request.WhichOneof("target") == "random":
            target = Address(bytes(reversed(request.random)), Address.RANDOM_DEVICE_ADDRESS)
            advertising_type =  AdvertisingType.DIRECTED_CONNECTABLE_HIGH_DUTY  # FIXME: HIGH_DUTY ?

        await self.device.start_advertising(
            target           = target,
            advertising_type = advertising_type,
            own_address_type = request.own_address_type
        )

        # FIXME: wait for advertising sets to have a correct set, use `None` for now
        return StartAdvertisingResponse(set=None)

    # TODO: use advertising set commands
    async def StopAdvertising(self, request, context):
        logging.info('StopAdvertising')
        await self.device.stop_advertising()
        return Empty()

    async def Scan(self, request, context):
        # TODO: add support for `request.phys`
        assert not request.phys

        logging.info('Scan')

        handler = self.device.on('advertisement', self.scan_queue.put_nowait)
        await self.device.start_scanning(
            legacy           = request.legacy,
            active           = not request.passive,
            own_address_type = request.own_address_type,
            scan_interval    = request.interval if request.interval else DEVICE_DEFAULT_SCAN_INTERVAL,
            scan_window      = request.window if request.window else DEVICE_DEFAULT_SCAN_WINDOW
        )

        try:
            # TODO: add support for `direct_address` in Bumble
            # TODO: add support for `periodic_advertising_interval` in Bumble
            while adv := await self.scan_queue.get():
                kwargs = {
                    'legacy':        adv.is_legacy,
                    'connectable':   adv.is_connectable,
                    'scannable':     adv.is_scannable,
                    'truncated':     adv.is_truncated,
                    'sid':           adv.sid,
                    'primary_phy':   adv.primary_phy,
                    'secondary_phy': adv.secondary_phy,
                    'tx_power':      adv.tx_power,
                    'rssi':          adv.rssi,
                    'data':          self.pack_data_types(adv.data)
                }

                if adv.address.address_type == Address.PUBLIC_DEVICE_ADDRESS:
                    kwargs['public'] = bytes(reversed(bytes(adv.address)))
                elif adv.address.address_type == Address.RANDOM_DEVICE_ADDRESS:
                    kwargs['random'] = bytes(reversed(bytes(adv.address)))
                elif adv.address.address_type == Address.PUBLIC_IDENTITY_ADDRESS:
                    kwargs['public_identity'] = bytes(reversed(bytes(adv.address)))
                elif adv.address.address_type == Address.RANDOM_IDENTITY_ADDRESS:
                    kwargs['random_static_identity'] = bytes(reversed(bytes(adv.address)))

                yield ScanningResponse(**kwargs)

        finally:
            self.device.remove_listener('advertisement', handler)
            self.scan_queue = asyncio.Queue()
            await self.device.abort_on('flush', self.device.stop_scanning())

    async def Inquiry(self, request, context):
        logging.info('Inquiry')

        complete_handler = self.device.on('inquiry_complete', lambda: self.inquiry_queue.put_nowait(None))
        result_handler = self.device.on(
            'inquiry_result',
            lambda address, class_of_device, eir_data, rssi:
                self.inquiry_queue.put_nowait((address, class_of_device, eir_data, rssi))
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
                    data=self.pack_data_types(eir_data)
                )

        finally:
            self.device.remove_listener('inquiry_complete', complete_handler)
            self.device.remove_listener('inquiry_result', result_handler)
            self.inquiry_queue = asyncio.Queue()
            await self.device.abort_on('flush', self.device.stop_discovery())

    async def SetDiscoverabilityMode(self, request, context):
        logging.info("SetDiscoverabilityMode")
        await self.device.set_discoverable(request.mode != DiscoverabilityMode.NOT_DISCOVERABLE)
        return Empty()

    async def SetConnectabilityMode(self, request, context):
        logging.info("SetConnectabilityMode")
        await self.device.set_connectable(request.mode != ConnectabilityMode.NOT_CONNECTABLE)
        return Empty()

    async def GetRemoteName(self, request, context):
        if request.WhichOneof('remote') == 'connection':
            connection_handle = int.from_bytes(request.connection.cookie.value, 'big')
            logging.info(f"GetRemoteName: {connection_handle}")

            remote = self.device.lookup_connection(connection_handle)
        else:
            # Need to reverse bytes order since Bumble Address is using MSB.
            remote = Address(bytes(reversed(request.address)), address_type=Address.PUBLIC_DEVICE_ADDRESS)
            logging.info(f"GetRemoteName: {remote}")

        try:
            remote_name = await self.device.request_remote_name(remote)
            return GetRemoteNameResponse(name=remote_name)
        except HCI_Error as e:
            if e.error_code == HCI_PAGE_TIMEOUT_ERROR:
                logging.warning(f"Peer not found: {e}")
                return GetRemoteNameResponse(remote_not_found=Empty())
            raise e


    def unpack_data_types(self, datas) -> AdvertisingData:
        res = AdvertisingData()
        if data := datas.incomplete_service_class_uuids16:
            res.ad_structures.append((
                AdvertisingData.INCOMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
                b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in data])
            ))
        if data := datas.complete_service_class_uuids16:
            res.ad_structures.append((
                AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
                b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in data])
            ))
        if data := datas.incomplete_service_class_uuids32:
            res.ad_structures.append((
                AdvertisingData.INCOMPLETE_LIST_OF_32_BIT_SERVICE_CLASS_UUIDS,
                b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in data])
            ))
        if data := datas.complete_service_class_uuids32:
            res.ad_structures.append((
                AdvertisingData.COMPLETE_LIST_OF_32_BIT_SERVICE_CLASS_UUIDS,
                b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in data])
            ))
        if data := datas.incomplete_service_class_uuids128:
            res.ad_structures.append((
                AdvertisingData.INCOMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS,
                b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in data])
            ))
        if data := datas.complete_service_class_uuids128:
            res.ad_structures.append((
                AdvertisingData.COMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS,
                b''.join([bytes(reversed(bytes.fromhex(uuid))) for uuid in data])
            ))
        if datas.HasField('include_shortened_local_name'):
            res.ad_structures.append((
                AdvertisingData.SHORTENED_LOCAL_NAME,
                bytes(self.device.name[:8], 'utf-8')
            ))
        elif data := datas.shortened_local_name:
            res.ad_structures.append((
                AdvertisingData.SHORTENED_LOCAL_NAME,
                bytes(data, 'utf-8')
            ))
        if datas.HasField('include_complete_local_name'):
            res.ad_structures.append((
                AdvertisingData.COMPLETE_LOCAL_NAME,
                bytes(self.device.name, 'utf-8')
            ))
        elif data := datas.complete_local_name:
            res.ad_structures.append((
                AdvertisingData.COMPLETE_LOCAL_NAME,
                bytes(data, 'utf-8')
            ))
        if datas.HasField('include_tx_power_level'):
            raise ValueError('unsupported data type')
        elif data := datas.tx_power_level:
            res.ad_structures.append((
                AdvertisingData.TX_POWER_LEVEL,
                bytes(struct.pack('<I', data)[:1])
            ))
        if datas.HasField('include_class_of_device'):
            res.ad_structures.append((
                AdvertisingData.CLASS_OF_DEVICE,
                bytes(struct.pack('<I', self.device.class_of_device)[:-1])
            ))
        elif data := datas.class_of_device:
            res.ad_structures.append((
                AdvertisingData.CLASS_OF_DEVICE,
                bytes(struct.pack('<I', data)[:-1])
            ))
        if data := datas.peripheral_connection_interval_min:
            res.ad_structures.append((
                AdvertisingData.PERIPHERAL_CONNECTION_INTERVAL_RANGE,
                bytes([
                    *struct.pack('<H', data),
                    *struct.pack('<H', datas.peripheral_connection_interval_max \
                        if datas.peripheral_connection_interval_max else data)
                ])
            ))
        if data := datas.service_solicitation_uuids16:
            res.ad_structures.append((
                AdvertisingData.LIST_OF_16_BIT_SERVICE_SOLICITATION_UUIDS,
                bytes([reversed(bytes.fromhex(uuid)) for uuid in data])
            ))
        if data := datas.service_solicitation_uuids32:
            res.ad_structures.append((
                AdvertisingData.LIST_OF_32_BIT_SERVICE_SOLICITATION_UUIDS,
                bytes([reversed(bytes.fromhex(uuid)) for uuid in data])
            ))
        if data := datas.service_solicitation_uuids128:
            res.ad_structures.append((
                AdvertisingData.LIST_OF_128_BIT_SERVICE_SOLICITATION_UUIDS,
                bytes([reversed(bytes.fromhex(uuid)) for uuid in data])
            ))
        # TODO: use `bytes.fromhex(uuid) + (data)` instead of `.extend`.
        #  we may also need to remove all the `reverse`
        if data := datas.service_data_uuid16:
            res.ad_structures.extend([(
                AdvertisingData.SERVICE_DATA_16_BIT_UUID,
                bytes.fromhex(uuid).extend(data)
            ) for uuid, data in data.items()])
        if data := datas.service_data_uuid32:
            res.ad_structures.extend([(
                AdvertisingData.SERVICE_DATA_32_BIT_UUID,
                bytes.fromhex(uuid).extend(data)
            ) for uuid, data in data.items()])
        if data := datas.service_data_uuid128:
            res.ad_structures.extend([(
                AdvertisingData.SERVICE_DATA_128_BIT_UUID,
                bytes.fromhex(uuid).extend(data)
            ) for uuid, data in data.items()])
        if data := datas.appearance:
            res.ad_structures.append((
                AdvertisingData.APPEARANCE,
                struct.pack('<H', data)
            ))
        if data := datas.advertising_interval:
            res.ad_structures.append((
                AdvertisingData.ADVERTISING_INTERVAL,
                struct.pack('<H', data)
            ))
        if data := datas.uri:
            res.ad_structures.append((
                AdvertisingData.URI,
                bytes(data, 'utf-8')
            ))
        if data := datas.le_supported_features:
            res.ad_structures.append((
                AdvertisingData.LE_SUPPORTED_FEATURES,
                data
            ))
        if data := datas.manufacturer_specific_data:
            res.ad_structures.append((
                AdvertisingData.MANUFACTURER_SPECIFIC_DATA,
                data
            ))
        return res


    def pack_data_types(self, ad: AdvertisingData) -> DataTypes:
        kwargs = {
            'service_data_uuid16': {},
            'service_data_uuid32': {},
            'service_data_uuid128': {}
        }

        if data :=  ad.get(AdvertisingData.INCOMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS):
            kwargs['incomplete_service_class_uuids16'] = list(map(lambda x: x.to_hex_str(), data))
        if data := ad.get(AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS):
            kwargs['complete_service_class_uuids16'] = list(map(lambda x: x.to_hex_str(), data))
        if data :=  ad.get(AdvertisingData.INCOMPLETE_LIST_OF_32_BIT_SERVICE_CLASS_UUIDS):
            kwargs['incomplete_service_class_uuids32'] = list(map(lambda x: x.to_hex_str(), data))
        if data := ad.get(AdvertisingData.COMPLETE_LIST_OF_32_BIT_SERVICE_CLASS_UUIDS):
            kwargs['complete_service_class_uuids32'] = list(map(lambda x: x.to_hex_str(), data))
        if data :=  ad.get(AdvertisingData.INCOMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS):
            kwargs['incomplete_service_class_uuids128'] = list(map(lambda x: x.to_hex_str(), data))
        if data := ad.get(AdvertisingData.COMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS):
            kwargs['complete_service_class_uuids128'] = list(map(lambda x: x.to_hex_str(), data))
        if data := ad.get(AdvertisingData.SHORTENED_LOCAL_NAME):
            kwargs['shortened_local_name'] = data
        if data := ad.get(AdvertisingData.COMPLETE_LOCAL_NAME):
            kwargs['complete_local_name'] = data
        if data := ad.get(AdvertisingData.TX_POWER_LEVEL):
            kwargs['tx_power_level'] = data
        if data := ad.get(AdvertisingData.CLASS_OF_DEVICE):
            kwargs['class_of_device'] = data
        if data := ad.get(AdvertisingData.PERIPHERAL_CONNECTION_INTERVAL_RANGE):
            kwargs['peripheral_connection_interval_min'] = data[0]
            kwargs['peripheral_connection_interval_max'] = data[1]
        if data :=  ad.get(AdvertisingData.LIST_OF_16_BIT_SERVICE_SOLICITATION_UUIDS):
            kwargs['service_solicitation_uuids16'] = list(map(lambda x: x.to_hex_str(), data))
        if data :=  ad.get(AdvertisingData.LIST_OF_32_BIT_SERVICE_SOLICITATION_UUIDS):
            kwargs['service_solicitation_uuids32'] = list(map(lambda x: x.to_hex_str(), data))
        if data :=  ad.get(AdvertisingData.LIST_OF_128_BIT_SERVICE_SOLICITATION_UUIDS):
            kwargs['service_solicitation_uuids128'] = list(map(lambda x: x.to_hex_str(), data))
        if data :=  ad.get(AdvertisingData.SERVICE_DATA_16_BIT_UUID):
            kwargs['service_data_uuid16'][data[0].to_hex_str()] = data[1]
        if data :=  ad.get(AdvertisingData.SERVICE_DATA_32_BIT_UUID):
            kwargs['service_data_uuid32'][data[0].to_hex_str()] = data[1]
        if data :=  ad.get(AdvertisingData.SERVICE_DATA_128_BIT_UUID):
            kwargs['service_data_uuid128'][data[0].to_hex_str()] = data[1]
        if data :=  ad.get(AdvertisingData.PUBLIC_TARGET_ADDRESS, raw=True):
            kwargs['public_target_addresses'] = [data[i*6::i*6+6] for i in range(len(data) / 6)]
        if data :=  ad.get(AdvertisingData.RANDOM_TARGET_ADDRESS, raw=True):
            kwargs['random_target_addresses'] = [data[i*6::i*6+6] for i in range(len(data) / 6)]
        if data := ad.get(AdvertisingData.APPEARANCE):
            kwargs['appearance'] = data
        if data := ad.get(AdvertisingData.ADVERTISING_INTERVAL):
            kwargs['advertising_interval'] = data
        if data := ad.get(AdvertisingData.URI):
            kwargs['uri'] = data
        if data := ad.get(AdvertisingData.LE_SUPPORTED_FEATURES, raw=True):
            kwargs['le_supported_features'] = data
        if data := ad.get(AdvertisingData.MANUFACTURER_SPECIFIC_DATA, raw=True):
            kwargs['manufacturer_specific_data'] = data

        if not len(kwargs['service_data_uuid16']):
            del kwargs['service_data_uuid16']
        if not len(kwargs['service_data_uuid32']):
            del kwargs['service_data_uuid32']
        if not len(kwargs['service_data_uuid128']):
            del kwargs['service_data_uuid128']

        return DataTypes(**kwargs)
