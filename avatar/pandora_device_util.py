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


"""Utility for abstracting controller registration and Pandora server setup."""

import importlib
import logging
from typing import List

from mobly import base_test

from avatar import pandora_client, bumble_server
from avatar.servers import android_pandora_server
from avatar.servers import pandora_server

PANDORA_COMMON_SERVER_CLASSES = {
    'AndroidDevice': android_pandora_server.AndroidPandoraServer,
    'BumbleDevice': bumble_server.BumblePandoraServer,
}

KEY_PANDORA_SERVER_CLASS = 'pandora_server_class'


class PandoraDeviceUtil:
    """Utility for abstracting controller registration and Pandora setup."""

    def __init__(self, test_class_instance: base_test.BaseTestClass):
        """Creates a PandoraDeviceUtil.

        Args:
          test_class_instance: Instance of the Mobly test class.
        """
        self._test_class_instance = test_class_instance
        self._clients = []
        self._servers = []

    def get_pandora_devices(self) -> List[pandora_client.PandoraClient]:
        """Returns PandoraClient instances given the test's controller config.

        It performs three steps:
          - Register the underlying controllers to the test.
          - Start the corresponding PandoraServer for each controller.
          - Start a PandoraClient for each server.

        The order in which the clients are returned can be determined by the
        (optional) `order_<controller_class>` params in user_params. Controllers
        without such a param will be set up last (order=100).

        Raises:
          RuntimeError: if get_pandora_devices() is already called previously.
        """
        if self._clients:
            raise RuntimeError('Pandora clients already active.')
        user_params = self._test_class_instance.user_params
        controller_configs = self._test_class_instance.controller_configs.copy()
        sorted_controllers = sorted(
            controller_configs.keys(),
            key=lambda controller: user_params.get(f'order_{controller}', 100),
        )
        for controller in sorted_controllers:
            # Find the corresponding PandoraServer class for the controller.
            if f'{KEY_PANDORA_SERVER_CLASS}_{controller}' in user_params:
                # Try to load the server dynamically if module specified in user_params.
                class_path = user_params[f'{KEY_PANDORA_SERVER_CLASS}_{controller}']
                logging.info(
                    'Loading Pandora server class %s from config for %s.',
                    class_path,
                    controller,
                )
                server_cls = _load_pandora_server_class(class_path)
            else:
                # Search in the list of commonly-used controllers.
                try:
                  server_cls = PANDORA_COMMON_SERVER_CLASSES[controller]
                except KeyError as e:
                  raise RuntimeError(
                      f'PandoraServer module for {controller} not found in either the '
                      'config or PANDORA_COMMON_SERVER_CLASSES.'
                  ) from e

            # Register the controller and load its Pandora server + client.
            logging.info('Starting %s(s) for %s', server_cls.__name__, controller)
            devices = self._test_class_instance.register_controller(
                server_cls.MOBLY_CONTROLLER_MODULE
            )
            for device in devices:
                server: pandora_server.PandoraServer = server_cls(device)
                client = server.start()
                self._servers.append(server)
                self._clients.append(client)
        return self._clients

    def cleanup(self) -> None:
        """Closes all opened Pandora clients and servers."""
        for client in self._clients:
            client.close()
        for server in self._servers:
            server.stop()


def _load_pandora_server_class(class_path: str) -> pandora_server.PandoraServer:
    """Dynamically load a PandoraServer from a user-specified module+class.

    Args:
      class_path: String in format '<module>.<class>', where the module is fully
        importable using importlib.import_module. e.g.:
        my.pandora.server.module.MyPandoraServer

    Returns:
      The loaded PandoraServer instance.
    """
    # Dynamically import the module, and get the class
    module_name, class_name = class_path.rsplit('.', 1)
    module = importlib.import_module(module_name)
    server_class = getattr(module, class_name)
    # Check that the class is a subclass of PandoraServer
    if not issubclass(server_class, pandora_server.PandoraServer):
        raise TypeError(
            f'The specified class {class_path} is not a subclass of PandoraServer.'
        )
    return server_class
