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


""" Bumble Pandora Server for Avatar"""

import asyncio
import avatar
import grpc

from contextlib import suppress

from bumble.smp import PairingDelegate

from avatar.pandora_client import PandoraClient
from avatar.controllers import bumble_device
from avatar.servers import pandora_server

from avatar.bumble_server.host import HostService
from pandora.host_grpc import add_HostServicer_to_server

from avatar.bumble_server.security import SecurityService, SecurityStorageService
from pandora.security_grpc import add_SecurityServicer_to_server, add_SecurityStorageServicer_to_server

from avatar.bumble_server.asha import ASHAService
from pandora.asha_grpc import add_ASHAServicer_to_server


class BumblePandoraServer(pandora_server.PandoraServer[bumble_device.BumbleDevice]):
    MOBLY_CONTROLLER_MODULE = bumble_device

    _grpc_server: grpc.aio.server = None

    _grpc_port: int = 0

    _server_task: asyncio.Task = None

    def start(self) -> PandoraClient:
        """Run the bumble pandora server over given transport."""

        async def coro():
            await self.__prepare_grpc_server()

        avatar.run_until_complete(coro())

        self._server_task = avatar.loop.create_task(
            self.__serve()
        )

        return PandoraClient(f"localhost:{self._grpc_port}", self.device)

    def stop(self) -> None:
        """Stop the bumble pandora."""

        async def coro():
            self._server_task.cancel()
            with suppress(asyncio.CancelledError): await self._server_task

        avatar.run_until_complete(coro())

    def reset(self):
        self.stop()
        self.start()

    def wait_for_termination(self):
        async def coro():
            await self._server_task

        avatar.run_until_complete(coro())

    async def __prepare_grpc_server(self):
        self._grpc_server = grpc.aio.server()
        self._grpc_port = self._grpc_server.add_insecure_port(
            f"localhost:{self._grpc_port}"
        )
        io_capability = getattr(
            PairingDelegate, self.device.io_capability_name
        )
        add_HostServicer_to_server(
            await HostService(
                self._grpc_server, self.device.device
            ).start(),
            self._grpc_server,
        )
        add_SecurityServicer_to_server(
            SecurityService(self.device.device, io_capability),
            self._grpc_server,
        )
        add_SecurityStorageServicer_to_server(
            SecurityStorageService(self.device.device), self._grpc_server
        )
        add_ASHAServicer_to_server(
            ASHAService(self.device.device), self._grpc_server
        )
        await self._grpc_server.start()

    async def __serve(self) -> None:
        try:
            while True:
                await self._grpc_server.wait_for_termination()
                await self.device.reset()
                await self.__prepare_grpc_server()

        finally:
            await self._grpc_server.stop(None)

    @property
    def grpc_port(self) -> int:
        return self._grpc_port

    @grpc_port.setter
    def grpc_port(self, port: int) -> None:
        self._grpc_port = port


if __name__ == "__main__":
    # 7300 for cuttlefish rootcanal hci port
    config = [{
        "transport": "tcp-client:127.0.0.1:7300",
        "classic_enabled": True,
    }]
    devices = bumble_device.create(config)
    dev = devices[0]
    server = BumblePandoraServer(dev)
    server.grpc_port = 7999
    server.start()
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        pass
    server.stop()
