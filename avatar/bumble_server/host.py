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
import struct

from bumble.core import BT_BR_EDR_TRANSPORT, BT_LE_TRANSPORT, AdvertisingData
from bumble.device import AdvertisingType, Device
from bumble.hci import Address, HCI_REMOTE_USER_TERMINATED_CONNECTION_ERROR
from bumble.smp import PairingConfig

from google.protobuf import empty_pb2
from google.protobuf.message import Message

from pandora.host_grpc import HostServicer
from pandora.host_pb2 import (
    DiscoverabilityMode, ConnectabilityMode,
    Connection, DataTypes
)
from pandora.host_pb2 import (
    ReadLocalAddressResponse,
    ConnectResponse, GetConnectionResponse, WaitConnectionResponse,
    ConnectLEResponse, GetLEConnectionResponse,
    StartAdvertisingResponse, StartScanningResponse, StartInquiryResponse,
    GetRemoteNameResponse
)


class HostService(HostServicer):

    def __init__(self, server):
        self.server = server
        super().__init__()

    async def set_device(self, device: Device):
        self.device = device
        self.device.pairing_config_factory = lambda connection: PairingConfig(bonding=False)
        self.scan_queue = asyncio.Queue()
        self.inquiry_queue = asyncio.Queue()
        self.discoverability_mode = DiscoverabilityMode.NOT_DISCOVERABLE
        self.connectability_mode = ConnectabilityMode.CONNECTABLE

        # According to `host.proto`:
        # At startup, the Host must be in BR/EDR connectable mode
        await self.device.set_scan_enable(False, True)

    async def HardReset(self, request, context):
        logging.info('HardReset')
        await self.server.reset()
        return empty_pb2.Empty()

    async def SoftReset(self, request, context):
        logging.info('SoftReset')
        await self.device.power_on()
        return empty_pb2.Empty()

    async def ReadLocalAddress(self, request, context):
        logging.info('ReadLocalAddress')
        return ReadLocalAddressResponse(
            address=bytes(reversed(bytes(self.device.public_address))))

    async def Connect(self, request, context):
        # Need to reverse bytes order since Bumble Address is using MSB.
        address = Address(bytes(reversed(request.address)), address_type=Address.PUBLIC_DEVICE_ADDRESS)
        logging.info(f"Connect: {address}")

        logging.info("Connecting...")
        connection = await self.device.connect(
            address, transport=BT_BR_EDR_TRANSPORT, timeout=10)
        logging.info("Connected")

        if not request.skip_pairing:
            logging.info("Authenticating...")
            await self.device.authenticate(connection)
            logging.info("Authenticated")

            logging.info("Enabling encryption...")
            await self.device.encrypt(connection)
            logging.info("Encryption on")

        # TODO: add support for `request.manually_confirm`
        assert not request.manually_confirm

        logging.info(f"Connect: connection handle: {connection.handle}")
        connection_handle = connection.handle.to_bytes(4, 'big')
        return ConnectResponse(connection=Connection(cookie=connection_handle, transport=BT_BR_EDR_TRANSPORT))

    async def GetConnection(self, request, context):
        # Need to reverse bytes order since Bumble Address is using MSB.
        address = Address(bytes(reversed(request.address)))
        logging.info(f"GetConnection: {address}")

        connection_handle = self.device.find_connection_by_bd_addr(
            address, transport=BT_BR_EDR_TRANSPORT).handle.to_bytes(4, 'big')
        return GetConnectionResponse(connection=Connection(cookie=connection_handle, transport=BT_BR_EDR_TRANSPORT))

    async def WaitConnection(self, request, context):
        # Need to reverse bytes order since Bumble Address is using MSB.
        address = Address(bytes(reversed(request.address)), address_type=Address.PUBLIC_DEVICE_ADDRESS)
        logging.info(f"WaitConnection: {address}")

        logging.info("Wait connection...")
        connection = await self.device.accept(address)
        logging.info("Connected")

        logging.info(f"WaitConnection: connection handle: {connection.handle}")
        connection_handle = connection.handle.to_bytes(4, 'big')
        return WaitConnectionResponse(connection=Connection(cookie=connection_handle, transport=BT_BR_EDR_TRANSPORT))

    async def ConnectLE(self, request, context):
        # Need to reverse bytes order since Bumble Address is using MSB.
        address = Address(bytes(reversed(request.address)), request.address_type)
        logging.info(f"ConnectLE: {address}")

        logging.info("Connecting...")
        connection = await self.device.connect(
            address, transport=BT_LE_TRANSPORT, timeout=10)
        logging.info("Connected")

        logging.info(f"ConnectLE: connection handle: {connection.handle}")
        connection_handle = connection.handle.to_bytes(4, 'big')
        return ConnectLEResponse(connection=Connection(cookie=connection_handle, transport=BT_LE_TRANSPORT))

    async def GetLEConnection(self, request, context):
        address = Address(bytes(reversed(request.address)))
        logging.info(f"GetConnection: {address}")

        connection_handle = self.device.find_connection_by_bd_addr(
            address, transport=BT_LE_TRANSPORT).handle.to_bytes(4, 'big')
        return GetLEConnectionResponse(connection=Connection(cookie=connection_handle, transport=BT_LE_TRANSPORT))

    async def Disconnect(self, request, context):
        connection_handle = int.from_bytes(request.connection.cookie, 'big')
        logging.info(f"Disconnect: {connection_handle}")

        logging.info("Disconnecting...")
        connection = self.device.lookup_connection(connection_handle)
        assert request.connection.transport == connection.transport
        await connection.disconnect(HCI_REMOTE_USER_TERMINATED_CONNECTION_ERROR)
        logging.info("Disconnected")

        return empty_pb2.Empty()

    # TODO: use adversing set commands
    async def StartAdvertising(self, request: Message, context):
        logging.info('StartAdvertising')

        if data := request.data:
            self.device.advertising_data = bytes(self.unpack_data_types(data))
            if scan_response_data := request.scan_response_data:
                self.device.scan_response_data =  bytes(self.unpack_data_types(scan_response_data))
                scannable = True
            else:
                scannable = False

            target = None
            if request.is_connectable and scannable:
                advertising_type = AdvertisingType.UNDIRECTED_CONNECTABLE_SCANNABLE
            elif scannable:
                advertising_type = AdvertisingType.UNDIRECTED_SCANNABLE
            else:
                advertising_type = AdvertisingType.UNDIRECTED

        if address := request.target:
            target = Address(bytes(reversed(address)), request.target_address_type)
            advertising_type =  AdvertisingType.DIRECTED_CONNECTABLE_HIGH_DUTY  # FIXME: HIGH_DUTY ?

        # TODO: add support for `request.extended`
        # TODO: add support for `request.interval`
        # TODO: add support for `request.interval_range`
        assert not request.extended
        assert not request.interval
        assert not request.interval_range

        await self.device.start_advertising(
            target=target,
            advertising_type=advertising_type,
            own_address_type=request.own_address_type if request.own_address_type != b'' else Address.RANDOM_DEVICE_ADDRESS
        )

        # FIXME: wait for advertising sets to have a correct set, use `None` for now
        return StartAdvertisingResponse(set=None)

    # TODO: use adversing set commands
    async def StopAdvertising(self, request, context):
        logging.info('StopAdvertising')
        await self.device.stop_advertising()
        return empty_pb2.Empty()

    async def StartScanning(self, request, context):
        logging.info('StartScanning')

        req = {}
        if interval := request.interval:
            req['scan_interval'] = interval
        if window := request.window:
            req['scan_window'] = window

        # TODO: add support for `request.extended`
        assert not request.extended

        handler = self.device.on('advertisement', self.scan_queue.put_nowait)
        await self.device.start_scanning(**req)
        try:
            while adv := await self.scan_queue.get():
                yield StartScanningResponse(
                    extended=not adv.is_legacy,
                    address=bytes(reversed(bytes(adv.address))),
                    address_type=adv.address.address_type,
                    is_connectable=adv.is_connectable,
                    is_scannable=adv.is_scannable,
                    is_truncated=adv.is_truncated,
                    sid=adv.sid,
                    primary_phy=adv.primary_phy,
                    secondary_phy=adv.secondary_phy,
                    tx_power=adv.tx_power,
                    rssi=adv.rssi,
                    data=self.pack_data_types(adv.data)
                )

        finally:
            self.device.remove_listener('advertisement', handler)
            self.scan_queue = asyncio.Queue()
            await self.device.stop_scanning()

    async def StopScanning(self, request, context):
        logging.info("StopScanning")
        await self.device.stop_scanning()
        await self.scan_queue.put(None)
        return empty_pb2.Empty()

    async def StartInquiry(self, request, context):
        logging.info('StartInquiry')

        handler = self.device.on(
            'inquiry_result',
            lambda address, class_of_device, eir_data, rssi:
                self.inquiry_queue.put_nowait((address, class_of_device, eir_data, rssi))
        )
        await self.device.start_discovery(auto_restart=False)
        try:
            while inquiry_result := await self.inquiry_queue.get():
                (address, class_of_device, eir_data, rssi) = inquiry_result
                # FIXME: if needed, add support for `page_scan_rep_mode` and `clock_offset` in Bumble
                yield StartInquiryResponse(
                    address=bytes(reversed(bytes(address))),
                    class_of_device=class_of_device,
                    rssi=rssi,
                    data=self.pack_data_types(eir_data)
                )

        finally:
            self.device.remove_listener('inquiry_result', handler)
            self.inquiry_queue = asyncio.Queue()
            await self.device.stop_discovery()

    async def StopInquiry(self, request, context):
        logging.info("StopInquiry")
        await self.device.stop_discovery()
        await self.inquiry_queue.put(None)
        return empty_pb2.Empty()

    async def SetDiscoverabilityMode(self, request, context):
        logging.info("SetDiscoverabilityMode")
        self.discoverability_mode = request.mode
        await self.device.set_scan_enable(
            self.discoverability_mode != DiscoverabilityMode.NOT_DISCOVERABLE,
            self.connectability_mode != ConnectabilityMode.NOT_CONNECTABLE
        )
        return empty_pb2.Empty()

    async def SetConnectabilityMode(self, request, context):
        logging.info("SetConnectabilityMode")
        self.connectability_mode = request.mode
        await self.device.set_scan_enable(
            self.discoverability_mode != DiscoverabilityMode.NOT_DISCOVERABLE,
            self.connectability_mode != ConnectabilityMode.NOT_CONNECTABLE
        )
        return empty_pb2.Empty()

    async def GetRemoteName(self, request: Message, context):
        if request.WhichOneof('remote') == 'connection':
            connection_handle = int.from_bytes(request.connection.cookie, 'big')
            logging.info("GetRemoteName {connection_handle}")

            remote = self.device.lookup_connection(connection_handle)
            assert request.connection.transport == remote.transport
        else:
            # Need to reverse bytes order since Bumble Address is using MSB.
            remote = Address(bytes(reversed(request.address)), address_type=Address.PUBLIC_DEVICE_ADDRESS)
            logging.info(f"GetRemoteName: {remote}")

        remote_name = await self.device.request_remote_name(remote)
        return GetRemoteNameResponse(name=remote_name)


    def unpack_data_types(self, datas: Message) -> AdvertisingData:
        res = AdvertisingData()
        if data := datas.incomplete_service_class_uuids16:
            res.ad_structures.append((
                AdvertisingData.INCOMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
                bytes([reversed(bytes.fromhex(uuid)) for uuid in data])
            ))
        if data := datas.complete_service_class_uuids16:
            res.ad_structures.append((
                AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
                bytes([reversed(bytes.fromhex(uuid)) for uuid in data])
            ))
        if data := datas.incomplete_service_class_uuids32:
            res.ad_structures.append((
                AdvertisingData.INCOMPLETE_LIST_OF_32_BIT_SERVICE_CLASS_UUIDS,
                bytes([reversed(bytes.fromhex(uuid)) for uuid in data])
            ))
        if data := datas.complete_service_class_uuids32:
            res.ad_structures.append((
                AdvertisingData.COMPLETE_LIST_OF_32_BIT_SERVICE_CLASS_UUIDS,
                bytes([reversed(bytes.fromhex(uuid)) for uuid in data])
            ))
        if data := datas.incomplete_service_class_uuids128:
            res.ad_structures.append((
                AdvertisingData.INCOMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS,
                bytes([reversed(bytes.fromhex(uuid)) for uuid in data])
            ))
        if data := datas.complete_service_class_uuids128:
            res.ad_structures.append((
                AdvertisingData.COMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS,
                bytes([reversed(bytes.fromhex(uuid)) for uuid in data])
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
                struct.pack('<c', data)
            ))
        if datas.HasField('include_class_of_device'):
            res.ad_structures.append((
                AdvertisingData.CLASS_OF_DEVICE,
                bytes(struct.pack('<I', self.device.class_of_device)[1:])
            ))
        elif data := datas.class_of_device:
            res.ad_structures.append((
                AdvertisingData.CLASS_OF_DEVICE,
                bytes(struct.pack('<I', data)[1:])
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
