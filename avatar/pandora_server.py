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
import avatar.aio
import grpc
import grpc.aio
import logging
import os
import portpicker
import re
import shlex
import threading
import types

from avatar.controllers import bumble_device, pandora_device
from avatar.pandora_client import BumblePandoraClient, PandoraClient
from bumble import pandora as bumble_server
from bumble.pandora.device import PandoraDevice as BumblePandoraDevice
from contextlib import suppress
from mobly.controllers import android_device
from mobly.controllers.android_device import AndroidDevice
from typing import Generic, Optional, TypeVar

ANDROID_SERVER_PACKAGE = 'com.android.pandora'
ANDROID_SERVER_GRPC_PORT = 8999


# Generic type for `PandoraServer`.
TDevice = TypeVar('TDevice')


class PandoraServer(Generic[TDevice]):
    """Abstract interface to manage the Pandora gRPC server on the device."""

    MOBLY_CONTROLLER_MODULE: types.ModuleType = pandora_device

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


class BumblePandoraServer(PandoraServer[BumblePandoraDevice]):
    """Manages the Pandora gRPC server on a BumbleDevice."""

    MOBLY_CONTROLLER_MODULE = bumble_device

    _task: Optional[asyncio.Task[None]] = None

    def start(self) -> BumblePandoraClient:
        """Sets up and starts the Pandora server on the Bumble device."""
        assert self._task is None

        # set the event loop to make sure the gRPC server use the avatar one.
        asyncio.set_event_loop(avatar.aio.loop)

        # create gRPC server & port.
        server = grpc.aio.server()
        port = server.add_insecure_port(f'localhost:{0}')

        config = bumble_server.Config()
        self._task = avatar.aio.loop.create_task(
            bumble_server.serve(self.device, config=config, grpc_server=server, port=port)
        )

        return BumblePandoraClient(f'localhost:{port}', self.device, config)

    def stop(self) -> None:
        """Stops and cleans up the Pandora server on the Bumble device."""

        async def server_stop() -> None:
            assert self._task is not None
            if not self._task.done():
                self._task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._task
            self._task = None

        avatar.aio.run_until_complete(server_stop())


class AndroidPandoraServer(PandoraServer[AndroidDevice]):
    """Manages the Pandora gRPC server on an AndroidDevice."""

    MOBLY_CONTROLLER_MODULE = android_device

    _instrumentation: Optional[threading.Thread] = None
    _port: int
    _logger: logging.Logger
    _handler: logging.Handler

    def start(self) -> PandoraClient:
        """Sets up and starts the Pandora server on the Android device."""
        assert self._instrumentation is None

        # start Pandora Android gRPC server.
        self._port = portpicker.pick_unused_port()  # type: ignore
        self._instrumentation = threading.Thread(
            target=lambda: self.device.adb._exec_adb_cmd(  # type: ignore
                'shell',
                f'am instrument --no-hidden-api-checks -w {ANDROID_SERVER_PACKAGE}/.Main',
                shell=False,
                timeout=None,
                stderr=None,
            )
        )

        self._instrumentation.start()
        self.device.adb.forward([f'tcp:{self._port}', f'tcp:{ANDROID_SERVER_GRPC_PORT}'])  # type: ignore

        # Forward all logging to ADB logs
        adb = self.device.adb

        class AdbLoggingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                if record.levelno <= logging.DEBUG:
                    return
                ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                msg = self.format(record)
                msg = ansi_escape.sub('', msg)
                level = {
                    logging.FATAL: 'f',
                    logging.ERROR: 'e',
                    logging.WARN: 'w',
                    logging.INFO: 'i',
                    logging.DEBUG: 'd',
                    logging.NOTSET: 'd',
                }[record.levelno]
                for msg in msg.splitlines():
                    os.system(f'adb -s {adb.serial} shell "log -t Avatar -p {level} {shlex.quote(msg)}"')

        self._logger = logging.getLogger()
        self._handler = AdbLoggingHandler()
        self._logger.addHandler(self._handler)

        return PandoraClient(f'localhost:{self._port}', 'android')

    def stop(self) -> None:
        """Stops and cleans up the Pandora server on the Android device."""
        assert self._instrumentation is not None

        # Stop Pandora Android gRPC server.
        self.device.adb._exec_adb_cmd(  # type: ignore
            'shell', f'am force-stop {ANDROID_SERVER_PACKAGE}', shell=False, timeout=None, stderr=None
        )

        # Remove ADB logging handler
        self._logger.removeHandler(self._handler)

        self.device.adb.forward(['--remove', f'tcp:{self._port}'])  # type: ignore
        self._instrumentation.join()
        self._instrumentation = None
