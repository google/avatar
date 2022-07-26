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
import threading

import mobly.controllers.android_device
import mobly.signals

from ..android_service import AndroidService
from ..bumble_server import BumblePandoraServer
from ..utils import Address


from pandora.host_grpc import Host

MOBLY_CONTROLLER_CONFIG_NAME = 'PandoraDevice'


def create(configs):
    def create_device(config):
        module_name = config.pop('module', PandoraDevice.__module__)
        class_name = config.pop('class', PandoraDevice.__name__)

        module = importlib.import_module(module_name)
        return getattr(module, class_name).create(**config)

    return list(map(create_device, configs))


def destroy(devices):
    for device in devices:
        device.close()


class PandoraDevice:

    def __init__(self, target):
        self.channel = grpc.insecure_channel(target)
        self.log = PandoraDeviceLoggerAdapter(logging.getLogger(), {
            'class': self.__class__.__name__,
            'address': self.address
        })

    @classmethod
    def create(cls, **kwargs):
        return cls(**kwargs)

    @property
    def host(self):
        return Host(self.channel)

    @property
    def address(self):
        return Address(self.host.ReadLocalAddress().address)

    def close(self):
        self.channel.close()


class PandoraDeviceLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        msg = f'[{self.extra["class"]}|{self.extra["address"]}] {msg}'
        return (msg, kwargs)


class AndroidPandoraDevice(PandoraDevice):

    def __init__(self, android_device):
        self.android_device = android_device
        # TODO: Use a dynamic port
        port = 8999
        self.android_device.services.register('pandora', AndroidService, configs={
            'port': port
        })
        super().__init__(f'localhost:{port}')

    def close(self):
        super().close()
        mobly.controllers.android_device.destroy([self.android_device])

    @classmethod
    def create(cls, config):
        android_devices = mobly.controllers.android_device.create(config)
        if not android_devices:
            raise mobly.signals.ControllerError(
                'Expected to get at least 1 android controller objects, got 0.')
        head, *tail = android_devices
        mobly.controllers.android_device.destroy(tail)
        return cls(head)


class BumblePandoraDevice(PandoraDevice):

    def __init__(self, server):
        self.server = server
        self.loop = asyncio.get_event_loop()
        self.loop.run_until_complete(self.server.start())
        self.thread = threading.Thread(target=lambda: self.loop.run_forever())
        self.thread.start()

        super().__init__(f'localhost:{self.server.grpc_port}')

    def close(self):
        super().close()
        self.loop.call_soon_threadsafe(lambda: self.loop.stop())
        self.thread.join()

    @property
    def device(self):
        return self.server.device

    @classmethod
    def create(cls, transport, **kwargs):
        loop = asyncio.get_event_loop()
        server = loop.run_until_complete(
            BumblePandoraServer.open(0, transport, kwargs))
        return cls(server)
