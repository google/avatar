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

import time

from mobly.controllers.android_device_lib.services.base_service \
    import BaseService

ANDROID_SERVER_PACKAGE = 'com.android.pandora'
ANDROID_SERVER_GRPC_PORT = 8999


class AndroidService(BaseService):

    def __init__(self, device, configs=None):
        super().__init__(device, configs)
        self.port = configs['port']
        self._is_alive = False

    @property
    def is_alive(self):
        return self._is_alive

    def start(self):
        # Start Pandora Android gRPC server.
        self._device.adb._exec_adb_cmd(
            'shell',
            f'am instrument -r -e Debug false {ANDROID_SERVER_PACKAGE}/.Main',
            shell=False,
            timeout=None,
            stderr=None)

        self._device.adb.forward(
            [f'tcp:{self.port}', f'tcp:{ANDROID_SERVER_GRPC_PORT}'])

        # Wait a few seconds for the Android gRPC server to be started.
        time.sleep(3)

        self._is_alive = True

    def stop(self):
        # Stop Pandora Android gRPC server.
        self._device.adb._exec_adb_cmd(
            'shell',
            f'am force-stop {ANDROID_SERVER_PACKAGE}',
            shell=False,
            timeout=None,
            stderr=None)

        self._device.adb.forward(['--remove', f'tcp:{self.port}'])

        self._is_alive = False
