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
import logging
import os
import sys
import traceback

from typing import NoReturn, Optional

from bumble.smp import PairingDelegate

from pandora.host_grpc import add_HostServicer_to_server
from pandora.security_grpc import add_SecurityServicer_to_server, add_SecurityStorageServicer_to_server
from pandora.asha_grpc import add_ASHAServicer_to_server

from avatar.bumble_device import BumbleDevice
from avatar.bumble_server.host import HostService
from avatar.bumble_server.security import SecurityService, SecurityStorageService
from avatar.bumble_server.asha import ASHAService


async def serve_bumble(
    bumble: BumbleDevice,
    server: Optional[grpc.aio.Server] = None,
    port: int = 0,
) -> NoReturn:
    # load IO capability from config.
    io_capability_name = bumble.config.get('io_capability', 'no_output_no_input').upper()
    io_capability = getattr(PairingDelegate, io_capability_name)

    if server is None:
        server = grpc.aio.server()

    try:
        while True:
            # add Pandora services to the gRPC server.
            add_HostServicer_to_server(HostService(server, bumble.device), server)
            add_SecurityServicer_to_server(SecurityService(bumble.device, io_capability), server)
            add_SecurityStorageServicer_to_server(SecurityStorageService(bumble.device), server)
            add_ASHAServicer_to_server(ASHAService(bumble.device), server)

            try:
                # open device.
                await bumble.open()
            except:
                print(traceback.format_exc(), end='', file=sys.stderr)
                os._exit(1)

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
            port = server.add_insecure_port(f'localhost:{port}')
    finally:
        # stop server.
        await server.stop(None)


BUMBLE_SERVER_GRPC_PORT = 7999
ROOTCANAL_PORT_CUTTLEFISH = 7300

if __name__ == '__main__':
    bumble = BumbleDevice({
        'transport': f'tcp-client:127.0.0.1:{ROOTCANAL_PORT_CUTTLEFISH}',
        'classic_enabled': True
    })

    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(serve_bumble(bumble, port=BUMBLE_SERVER_GRPC_PORT))
