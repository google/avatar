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


"""Interface for controller-specific Pandora server management."""

import asyncio
import avatar
import grpc
import threading
import time
import types

from contextlib import suppress

from typing import NoReturn, Optional, TypeVar, Generic

from mobly.controllers import android_device
from mobly.controllers.android_device import AndroidDevice

from avatar.bumble_device import BumbleDevice
from avatar.bumble_server import serve_bumble
from avatar.pandora_client import PandoraClient, BumblePandoraClient
from avatar.controllers import bumble_device

ANDROID_SERVER_PACKAGE = 'com.android.pandora'
ANDROID_SERVER_GRPC_PORT = 8999 # TODO: Use a dynamic port


# Generic type for `PandoraServer`.
TDevice = TypeVar('TDevice')

class PandoraServer(Generic[TDevice]):
    """Abstract interface to manage the Pandora gRPC server on the device."""

    MOBLY_CONTROLLER_MODULE: types.ModuleType

    device: TDevice

    def __init__(self, device: TDevice) -> None:
        """Creates a PandoraServer.

        Args:
            device: A Mobly controller instance.
        """
        self.device = device

    def start(self) -> PandoraClient:
        """Sets up and starts the Pandora server on the device."""
        assert isinstance(self.device, PandoraClient)
        return self.device

    def stop(self) -> None:
        """Stops and cleans up the Pandora server on the device."""


class BumblePandoraServer(PandoraServer[BumbleDevice]):
    """Manages the Pandora gRPC server on an BumbleDevice."""

    MOBLY_CONTROLLER_MODULE = bumble_device

    _task: Optional[asyncio.Task[NoReturn]] = None

    def start(self) -> BumblePandoraClient:
        """Sets up and starts the Pandora server on the Bumble device."""
        assert self._task is None

        # set the event loop to make sure the gRPC server use the avatar one.
        asyncio.set_event_loop(avatar.loop)

        # create gRPC server & port.
        server = grpc.aio.server()
        port = server.add_insecure_port(f'localhost:{0}')

        self._task = avatar.loop.create_task(serve_bumble(
            self.device,
            server=server,
            port=port,
        ))

        return BumblePandoraClient(f'localhost:{port}', self.device)

    def stop(self) -> None:
        """Stops and cleans up the Pandora server on the Bumble device."""
        async def server_stop() -> None:
            assert self._task is not None
            self._task.cancel()
            with suppress(asyncio.CancelledError): await self._task

        avatar.run_until_complete(server_stop())


class AndroidPandoraServer(PandoraServer[AndroidDevice]):
    """Manages the Pandora gRPC server on an AndroidDevice."""

    MOBLY_CONTROLLER_MODULE = android_device

    _instrumentation: Optional[threading.Thread] = None
    _port: int = ANDROID_SERVER_GRPC_PORT

    def start(self) -> PandoraClient:
        """Sets up and starts the Pandora server on the Android device."""
        assert self._instrumentation is None

        # start Pandora Android gRPC server.
        self._instrumentation = threading.Thread(
            target=lambda: self.device.adb._exec_adb_cmd(
                'shell',
                f'am instrument --no-hidden-api-checks -w {ANDROID_SERVER_PACKAGE}/.Main',
                shell=False,
                timeout=None,
                stderr=None
            )
        )

        self._instrumentation.start()
        self.device.adb.forward([f'tcp:{self._port}', f'tcp:{ANDROID_SERVER_GRPC_PORT}'])

        # wait a few seconds for the Android gRPC server to be started.
        time.sleep(3)

        return PandoraClient(f'localhost:{self._port}')

    def stop(self) -> None:
        """Stops and cleans up the Pandora server on the Android device."""
        assert self._instrumentation is not None

        # Stop Pandora Android gRPC server.
        self.device.adb._exec_adb_cmd(
            'shell',
            f'am force-stop {ANDROID_SERVER_PACKAGE}',
            shell=False,
            timeout=None,
            stderr=None)

        self.device.adb.forward(['--remove', f'tcp:{ANDROID_SERVER_GRPC_PORT}'])
        self._instrumentation.join()
