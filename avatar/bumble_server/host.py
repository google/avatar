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

from bumble.core import BT_BR_EDR_TRANSPORT
from bumble.hci import Address, HCI_REMOTE_USER_TERMINATED_CONNECTION_ERROR
from bumble.smp import PairingConfig

from pandora.host_pb2 import ReadLocalAddressResponse, ConnectResponse, \
    Connection, DisconnectResponse, GetConnectionResponse
from pandora.host_grpc import HostServicer


class HostService(HostServicer):

    def __init__(self, device):
        self.device = device
        self.device.pairing_config_factory = lambda connection: PairingConfig(
            bonding=False)

    async def ReadLocalAddress(self, request, context):
        logging.info('ReadLocalAddress')
        return ReadLocalAddressResponse(
            address=bytes(reversed(bytes(self.device.public_address))))

    async def Connect(self, request, context):
        # Need to reverse bytes order since Bumble Address is using MSB.
        address = Address(bytes(reversed(request.address)))
        logging.info(f"Connect: {address}")

        try:
            logging.info("Connecting...")
            connection = await self.device.connect(
                address, transport=BT_BR_EDR_TRANSPORT)
            logging.info("Connected")

            logging.info("Authenticating...")
            await self.device.authenticate(connection)
            logging.info("Authenticated")

            logging.info("Enabling encryption...")
            await self.device.encrypt(connection)
            logging.info("Encryption on")

            logging.info(f"Connect: connection handle: {connection.handle}")
            connection_handle = connection.handle.to_bytes(4, 'big')
            return ConnectResponse(connection=Connection(cookie=connection_handle))

        except Exception as error:
            logging.error(error)
            return ConnectResponse()

    async def Disconnect(self, request, context):
        # Need to reverse bytes order since Bumble Address is using MSB.
        connection_handle = int.from_bytes(request.connection.cookie,'big')
        logging.info(f"Disconnect: {connection_handle}")

        try:
            logging.info("Disconnecting...")
            connection = self.device.lookup_connection(connection_handle)
            await connection.disconnect(HCI_REMOTE_USER_TERMINATED_CONNECTION_ERROR)
        except Exception as error:
            logging.error(error)

        return DisconnectResponse()

    async def GetConnection(self, request, context):
        address = Address(bytes(reversed(request.address)))
        logging.info(f"GetConnection: {address}")

        try:
            connection_handle = self.device.find_connection_by_bd_addr(
                address).handle.to_bytes(4, 'big')
            return GetConnectionResponse(connection=Connection(cookie=connection_handle))

        except Exception as error:
            logging.error(error)
            return GetConnectionResponse()
