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

"""Bumble Pandora server."""

__version__ = "0.0.1"

import asyncio
import grpc
import grpc.aio
import logging

from avatar.bumble_device import BumbleDevice
from avatar.bumble_server.asha import AshaService
from avatar.bumble_server.host import HostService
from avatar.bumble_server.security import SecurityService, SecurityStorageService
from bumble.smp import PairingDelegate
from pandora.asha_grpc_aio import add_AshaServicer_to_server
from pandora.host_grpc_aio import add_HostServicer_to_server
from pandora.security_grpc_aio import add_SecurityServicer_to_server, add_SecurityStorageServicer_to_server
from typing import Callable, List, Optional

# Add servicers hooks.
_SERVICERS_HOOKS: List[Callable[[BumbleDevice, grpc.aio.Server], None]] = []


def register_servicer_hook(hook: Callable[[BumbleDevice, grpc.aio.Server], None]) -> None:
    _SERVICERS_HOOKS.append(hook)


async def serve_bumble(bumble: BumbleDevice, grpc_server: Optional[grpc.aio.Server] = None, port: int = 0) -> None:
    # initialize a gRPC server if not provided.
    server = grpc_server if grpc_server is not None else grpc.aio.server()
    port = server.add_insecure_port(f'localhost:{port}')

    # load IO capability from config.
    io_capability_name: str = bumble.config.get('io_capability', 'no_output_no_input').upper()
    io_capability: int = getattr(PairingDelegate, io_capability_name)

    try:
        while True:
            # add Pandora services to the gRPC server.
            add_HostServicer_to_server(HostService(server, bumble.device), server)
            add_SecurityServicer_to_server(SecurityService(bumble.device, io_capability), server)
            add_SecurityStorageServicer_to_server(SecurityStorageService(bumble.device), server)
            add_AshaServicer_to_server(AshaService(bumble.device), server)

            # call hooks if any.
            for hook in _SERVICERS_HOOKS:
                hook(bumble, server)

            # open device.
            await bumble.open()
            try:
                # Pandora require classic devices to to be discoverable & connectable.
                if bumble.device.classic_enabled:
                    await bumble.device.set_discoverable(False)
                    await bumble.device.set_connectable(True)

                # start & serve gRPC server.
                await server.start()
                await server.wait_for_termination()
            finally:
                # close device.
                await bumble.close()

            # re-initialize the gRPC server.
            server = grpc.aio.server()
            server.add_insecure_port(f'localhost:{port}')
    finally:
        # stop server.
        await server.stop(None)


BUMBLE_SERVER_GRPC_PORT = 7999
ROOTCANAL_PORT_CUTTLEFISH = 7300

if __name__ == '__main__':
    bumble = BumbleDevice({'transport': f'tcp-client:127.0.0.1:{ROOTCANAL_PORT_CUTTLEFISH}', 'classic_enabled': True})
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(serve_bumble(bumble, port=BUMBLE_SERVER_GRPC_PORT))
