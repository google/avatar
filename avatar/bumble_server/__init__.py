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
import logging
import os
import grpc

from bumble.host import Host
from bumble.device import Device, DeviceConfiguration
from bumble.transport import open_transport

from bumble.a2dp import make_audio_sink_service_sdp_records

from pandora.host_grpc import add_HostServicer_to_server
from .host import HostService

BUMBLE_SERVER_GRPC_PORT = 7999
ROOTCANAL_PORT_CUTTLEFISH = 7300

current_dir = os.path.dirname(os.path.realpath(__file__))


class BumblePandoraServer:

    def __init__(self, grpc_port, transport_name, config):
        self.transport_name = transport_name
        self.config = config
        self.grpc_server = grpc.aio.server()

        self.host_service = HostService(self)
        add_HostServicer_to_server(self.host_service, self.grpc_server)
        self.grpc_port = self.grpc_server.add_insecure_port(
            f'localhost:{grpc_port}')

    async def start(self):
        self.hci = await open_transport(self.transport_name)

        # initialize bumble device
        device_config = DeviceConfiguration()
        device_config.load_from_dict(self.config)
        host = Host(controller_source=self.hci.source,
                    controller_sink=self.hci.sink)
        self.device = Device(config=device_config, host=host)
        self.device.classic_enabled = self.config.get('classic_enabled', False)

        # setup current device into host service
        self.host_service.set_device(self.device)

        # start bumble device
        await self.device.power_on()

    @classmethod
    async def open(cls, grpc_port, transport_name, config):
        server = cls(grpc_port, transport_name, config)
        await server.grpc_server.start()
        return server

    async def wait_for_termination(self):
        await self.grpc_server.wait_for_termination()

    async def close(self):
        await self.grpc_server.stop(None)
        await self.hci.close()

    async def reset(self):
        # close device without closing the gRPC server
        await self.hci.close()
        # FIXME: do you really need this ?
        #  if yes may we need to `del` device too ?
        del self.hci
        # start will reset the bumble device object
        await self.start()


async def serve():
    transport = f'tcp-client:127.0.0.1:{ROOTCANAL_PORT_CUTTLEFISH}'
    server = await BumblePandoraServer.open(BUMBLE_SERVER_GRPC_PORT, transport,
                                            {'classic_enabled': True})

    await server.start()
    await server.wait_for_termination()
    await server.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(serve())
