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


"""Manages the Pandora gRPC server on an AndroidDevice."""

import threading
import time

from mobly.controllers import android_device
from mobly.controllers.android_device import AndroidDevice

from avatar.servers import pandora_server
from avatar.pandora_client import PandoraClient

ANDROID_SERVER_PACKAGE = 'com.android.pandora'
ANDROID_SERVER_GRPC_PORT = 8999  # TODO: Use a dynamic port


class AndroidPandoraServer(pandora_server.PandoraServer[AndroidDevice]):
    """Manages the Pandora gRPC server on an AndroidDevice."""

    MOBLY_CONTROLLER_MODULE = android_device

    def start(self) -> PandoraClient:
        """Sets up and starts the Pandora server on the Android device."""
        # Start Pandora Android gRPC server.
        self._instrumentation = threading.Thread(
            target=lambda: self.device.adb._exec_adb_cmd(
                'shell',
                f'am instrument --no-hidden-api-checks -w {ANDROID_SERVER_PACKAGE}/.Main',
                shell=False,
                timeout=None,
                stderr=None))

        self._instrumentation.start()

        self.device.adb.forward(
            [f'tcp:{ANDROID_SERVER_GRPC_PORT}', f'tcp:{ANDROID_SERVER_GRPC_PORT}'])

        # Wait a few seconds for the Android gRPC server to be started.
        time.sleep(3)

        return PandoraClient(f'localhost:{ANDROID_SERVER_GRPC_PORT}', None)

    def stop(self) -> None:
        """Stops and cleans up the Pandora server on the Android device."""
        # Stop Pandora Android gRPC server.
        self.device.adb._exec_adb_cmd(
            'shell',
            f'am force-stop {ANDROID_SERVER_PACKAGE}',
            shell=False,
            timeout=None,
            stderr=None)

        self.device.adb.forward(['--remove', f'tcp:{ANDROID_SERVER_GRPC_PORT}'])
        self._instrumentation.join()
