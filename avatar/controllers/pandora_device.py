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
import grpc
import importlib
import asyncio
import avatar
import contextlib

import mobly.controllers.android_device
import mobly.signals

from contextlib import suppress

from ..android_service import ANDROID_SERVER_GRPC_PORT, AndroidService
from ..bumble_server import BumblePandoraServer
from ..utils import Address

from pandora.host_grpc import Host
from pandora.security_grpc import Security, SecurityStorage

from bumble.device import Device

MOBLY_CONTROLLER_CONFIG_NAME = 'PandoraDevice'


def create(configs):
    def create_device(config):
        module_name = config.pop('module', PandoraDevice.__module__)
        class_name = config.pop('class', PandoraDevice.__name__)

        module = importlib.import_module(module_name)
        return getattr(module, class_name)(**config)

    return list(map(create_device, configs))

def destroy(devices):
    [device.destroy() for device in devices]


class PandoraDevice:

    def __init__(self, target):
        self._address = Address(b'\x00\x00\x00\x00\x00\x00')
        self._target = target
        self._channel = grpc.insecure_channel(target)
        self._aio_channel = None
        self.log = PandoraDeviceLoggerAdapter(logging.getLogger(), self)

    def destroy(self):
        self._channel.close()
        if self._aio_channel:
            avatar.run_until_complete(self._aio_channel.close())

    @property
    def channel(self):
        # Force the use of the asynchronous channel when running in our event loop.
        with contextlib.suppress(RuntimeError):
            if asyncio.get_running_loop() == avatar.loop:
                if not self._aio_channel:
                    self._aio_channel = grpc.aio.insecure_channel(self._target)
                return self._aio_channel
        return self._channel

    @property
    def address(self):
        return self._address

    @address.setter
    def address(self, bytes):
        self._address = Address(bytes)

    @property
    def host(self) -> Host:
        return Host(self.channel)

    @property
    def security(self) -> Security:
        return Security(self.channel)

    @property
    def security_storage(self) -> SecurityStorage:
        return SecurityStorage(self.channel)


class PandoraDeviceLoggerAdapter(logging.LoggerAdapter):

    def process(self, msg, kwargs):
        msg = f'[{self.extra.__class__.__name__}|{self.extra.address}] {msg}'
        return (msg, kwargs)


class AndroidPandoraDevice(PandoraDevice):

    def __init__(self, config):
        android_devices = mobly.controllers.android_device.create(config)
        if not android_devices:
            raise mobly.signals.ControllerError(
                'Expected to get at least 1 android controller objects, got 0.')
        head, *tail = android_devices
        mobly.controllers.android_device.destroy(tail)

        self.android_device = head
        port = ANDROID_SERVER_GRPC_PORT
        self.android_device.services.register('pandora', AndroidService, configs={
            'port': port
        })
        super().__init__(f'localhost:{port}')

    def destroy(self):
        super().destroy()
        mobly.controllers.android_device.destroy([self.android_device])


class BumblePandoraDevice(PandoraDevice):

    def __init__(self, transport, **config):
        asyncio.set_event_loop(avatar.loop)
        grpc_server = grpc.aio.server()
        grpc_port = grpc_server.add_insecure_port('localhost:0')

        super().__init__(f'localhost:{grpc_port}')

        self.device: Device = None
        self.server_task = avatar.loop.create_task(
            BumblePandoraServer.serve(
                transport, config, grpc_server, grpc_port,
                on_started=lambda server: setattr(self, 'device', server.device)
            )
        )

    def destroy(self):
        async def server_stop():
            self.server_task.cancel()
            with suppress(asyncio.CancelledError): await self.server_task

        super().destroy()
        avatar.run_until_complete(server_stop())
