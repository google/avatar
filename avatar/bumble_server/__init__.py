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
import os
import sys
import traceback

from avatar.bumble_device import BumbleDevice
from avatar.bumble_server.asha import ASHAService
from avatar.bumble_server.host import HostService
from avatar.bumble_server.security import SecurityService, SecurityStorageService
from bumble.smp import PairingDelegate
from dataclasses import dataclass
from pandora.asha_grpc_aio import add_ASHAServicer_to_server
from pandora.host_grpc_aio import add_HostServicer_to_server
from pandora.security_grpc_aio import add_SecurityServicer_to_server, add_SecurityStorageServicer_to_server
from typing import Callable, Coroutine, List, Optional

# Add servicers hooks.
_SERVICERS_HOOKS: List[Callable[['Server'], None]] = []


@dataclass
class Configuration:
    io_capability: int


@dataclass
class Server:
    port: int
    bumble: BumbleDevice
    server: grpc.aio.Server
    config: Configuration

    async def start(self) -> None:
        device = self.bumble.device

        # add Pandora services to the gRPC server.
        add_HostServicer_to_server(HostService(self.server, device), self.server)
        add_SecurityServicer_to_server(SecurityService(device, self.config.io_capability), self.server)
        add_SecurityStorageServicer_to_server(SecurityStorageService(device), self.server)
        add_ASHAServicer_to_server(ASHAService(device), self.server)

        # call hooks if any.
        for hook in _SERVICERS_HOOKS:
            hook(self)

        try:
            # open device.
            await self.bumble.open()
        except:
            print(traceback.format_exc(), end='', file=sys.stderr)
            os._exit(1)  # type: ignore

        # Pandora require classic devices to to be discoverable & connectable.
        if device.classic_enabled:
            await device.set_discoverable(False)
            await device.set_connectable(True)

        # start the gRPC server.
        await self.server.start()

    async def serve(self) -> None:
        try:
            while True:
                try:
                    # serve gRPC server.
                    await self.server.wait_for_termination()
                except KeyboardInterrupt:
                    return
                finally:
                    # close device.
                    await self.bumble.close()

                # re-initialize the gRPC server & re-start.
                self.server = grpc.aio.server()
                self.port = self.server.add_insecure_port(f'localhost:{self.port}')
                await self.start()
        except KeyboardInterrupt:
            return
        finally:
            # stop server.
            await self.server.stop(None)


def register_servicer_hook(hook: Callable[['Server'], None]) -> None:
    _SERVICERS_HOOKS.append(hook)


def serve_bumble(
    bumble: BumbleDevice,
    grpc_server: Optional[grpc.aio.Server] = None,
    port: int = 0,
) -> Coroutine[None, None, None]:
    # initialize a gRPC server if not provided.
    server: grpc.aio.Server = grpc_server if grpc_server is not None else grpc.aio.server()

    # load IO capability from config.
    io_capability_name: str = bumble.config.get('io_capability', 'no_output_no_input').upper()
    io_capability: int = getattr(PairingDelegate, io_capability_name)

    # create server.
    bumble_server = Server(port, bumble, server, Configuration(io_capability))

    # start bumble server.
    asyncio.run_coroutine_threadsafe(
        bumble_server.start(),
        asyncio.get_event_loop(),
    ).result()

    return bumble_server.serve()


BUMBLE_SERVER_GRPC_PORT = 7999
ROOTCANAL_PORT_CUTTLEFISH = 7300

if __name__ == '__main__':
    bumble = BumbleDevice({'transport': f'tcp-client:127.0.0.1:{ROOTCANAL_PORT_CUTTLEFISH}', 'classic_enabled': True})

    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(serve_bumble(bumble, port=BUMBLE_SERVER_GRPC_PORT))
