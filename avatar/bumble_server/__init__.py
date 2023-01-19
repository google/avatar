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

"""Pandora Bumble Server."""

__version__ = "0.0.1"

import asyncio
import grpc
import logging
import os
import random
import sys
import traceback

from bumble.smp import PairingDelegate
from bumble.host import Host
from bumble.device import Device, DeviceConfiguration
from bumble.transport import open_transport
from bumble.sdp import (
    DataElement, ServiceAttribute,
    SDP_SERVICE_RECORD_HANDLE_ATTRIBUTE_ID,
    SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID,
    SDP_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID,
    SDP_BLUETOOTH_PROFILE_DESCRIPTOR_LIST_ATTRIBUTE_ID
)
from bumble.core import (
    BT_GENERIC_AUDIO_SERVICE, BT_HANDSFREE_SERVICE,
    BT_L2CAP_PROTOCOL_ID, BT_RFCOMM_PROTOCOL_ID
)

from .host import HostService
from pandora.host_grpc import add_HostServicer_to_server

from .security import SecurityService, SecurityStorageService
from pandora.security_grpc import add_SecurityServicer_to_server, add_SecurityStorageServicer_to_server

from pandora.asha_grpc import add_ASHAServicer_to_server
from .asha import ASHAService

BUMBLE_SERVER_GRPC_PORT = 7999
ROOTCANAL_PORT_CUTTLEFISH = 7300

def make_sdp_records(rfcomm_channel):
    return {
        0x00010001: [
            ServiceAttribute(SDP_SERVICE_RECORD_HANDLE_ATTRIBUTE_ID,
                             DataElement.unsigned_integer_32(0x00010001)),
            ServiceAttribute(
                SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID,
                DataElement.sequence([
                    DataElement.uuid(BT_HANDSFREE_SERVICE),
                    DataElement.uuid(BT_GENERIC_AUDIO_SERVICE)
                ])),
            ServiceAttribute(
                SDP_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID,
                DataElement.sequence([
                    DataElement.sequence(
                        [DataElement.uuid(BT_L2CAP_PROTOCOL_ID)]),
                    DataElement.sequence([
                        DataElement.uuid(BT_RFCOMM_PROTOCOL_ID),
                        DataElement.unsigned_integer_8(rfcomm_channel)
                    ])
                ])),
            ServiceAttribute(
                SDP_BLUETOOTH_PROFILE_DESCRIPTOR_LIST_ATTRIBUTE_ID,
                DataElement.sequence([
                    DataElement.sequence([
                        DataElement.uuid(BT_HANDSFREE_SERVICE),
                        DataElement.unsigned_integer_16(0x0105)
                    ])
                ]))
        ]
    }

class BumblePandoraServer:

    def __init__(self, transport, config):
        self.transport = transport
        self.config = config

    async def start(self, grpc_server: grpc.aio.Server):
        self.hci = await open_transport(self.transport)

        # generate a random address
        random_address = f"{random.randint(192,255):02X}"  # address is static random
        for c in random.sample(range(255), 5): random_address += f":{c:02X}"

        # initialize bumble device
        device_config = DeviceConfiguration()
        device_config.load_from_dict(self.config)
        host = Host(controller_source=self.hci.source, controller_sink=self.hci.sink)
        self.device = Device(config=device_config, host=host, address=random_address)

        # FIXME: add `classic_enabled` to `DeviceConfiguration` ?
        self.device.classic_enabled = self.config.get('classic_enabled', False)
        # Add fake a2dp service to avoid Android disconnect (TODO: remove when a2dp is supported)
        self.device.sdp_service_records = make_sdp_records(1)
        io_capability_name = self.config.get('io_capability', 'no_output_no_input').upper()
        io_capability = getattr(PairingDelegate, io_capability_name)

        # start bumble device
        await self.device.power_on()

        # add our services to the gRPC server
        add_HostServicer_to_server(await HostService(grpc_server, self.device).start(), grpc_server)
        add_SecurityServicer_to_server(SecurityService(self.device, io_capability), grpc_server)
        add_SecurityStorageServicer_to_server(SecurityStorageService(self.device), grpc_server)
        add_ASHAServicer_to_server(ASHAService(self.device), grpc_server)

    async def close(self):
        await self.device.host.flush()
        await self.hci.close()

    @classmethod
    async def serve(cls, transport, config, grpc_server, grpc_port, on_started=None):
        try:
            while True:
                try:
                    server = cls(transport, config)
                    await server.start(grpc_server)
                except:
                    print(traceback.format_exc(), end='', file=sys.stderr)
                    os._exit(1)

                if on_started:
                    on_started(server)

                await grpc_server.start()
                await grpc_server.wait_for_termination()
                await server.close()

                # re-initialize gRPC server
                grpc_server = grpc.aio.server()
                grpc_server.add_insecure_port(f'localhost:{grpc_port}')

        finally:
            await server.close()
            await grpc_server.stop(None)


async def serve():
    grpc_server = grpc.aio.Server()
    grpc_port = grpc_server.add_insecure_port(f'localhost:{BUMBLE_SERVER_GRPC_PORT}')

    transport = f'tcp-client:127.0.0.1:{ROOTCANAL_PORT_CUTTLEFISH}'
    config = {'classic_enabled': True}

    await BumblePandoraServer.serve(transport, config, grpc_server, grpc_port)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(serve())
