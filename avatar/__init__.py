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

"""
Avatar is a scalable multi-platform Bluetooth testing tool capable of running
any Bluetooth test cases virtually and physically.
"""

__version__ = "0.0.1"

import functools
import importlib
import logging

from avatar import pandora_server
from avatar.pandora_client import PandoraClient
from avatar.pandora_server import PandoraServer
from mobly import base_test
from typing import Any, Callable, Dict, Iterable, Iterator, List, Sized, Tuple, Type

PANDORA_COMMON_SERVER_CLASSES: Dict[str, Type[pandora_server.PandoraServer[Any]]] = {
    'PandoraDevice': pandora_server.PandoraServer,
    'AndroidDevice': pandora_server.AndroidPandoraServer,
    'BumbleDevice': pandora_server.BumblePandoraServer,
}

KEY_PANDORA_SERVER_CLASS = 'pandora_server_class'


class PandoraDevices(Sized, Iterable[PandoraClient]):
    """Utility for abstracting controller registration and Pandora setup."""

    _test: base_test.BaseTestClass
    _clients: List[PandoraClient]
    _servers: List[PandoraServer[Any]]

    def __init__(self, test: base_test.BaseTestClass) -> None:
        """Creates a PandoraDevices list.

        It performs three steps:
          - Register the underlying controllers to the test.
          - Start the corresponding PandoraServer for each controller.
          - Store a PandoraClient for each server.

        The order in which the clients are returned can be determined by the
        (optional) `order_<controller_class>` params in user_params. Controllers
        without such a param will be set up last (order=100).

        Args:
            test: Instance of the Mobly test class.
        """
        self._test = test
        self._clients = []
        self._servers = []

        user_params: Dict[str, Any] = test.user_params  # type: ignore
        controller_configs: Dict[str, Any] = test.controller_configs.copy()  # type: ignore
        sorted_controllers = sorted(
            controller_configs.keys(), key=lambda controller: user_params.get(f'order_{controller}', 100)
        )
        for controller in sorted_controllers:
            # Find the corresponding PandoraServer class for the controller.
            if f'{KEY_PANDORA_SERVER_CLASS}_{controller}' in user_params:
                # Try to load the server dynamically if module specified in user_params.
                class_path = user_params[f'{KEY_PANDORA_SERVER_CLASS}_{controller}']
                logging.info('Loading Pandora server class %s from config for %s.', class_path, controller)
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

            # Register the controller and load its Pandora servers.
            logging.info('Starting %s(s) for %s', server_cls.__name__, controller)
            devices: Optional[List[Any]] = test.register_controller(server_cls.MOBLY_CONTROLLER_MODULE)  # type: ignore
            assert devices
            for device in devices:  # type: ignore
                self._servers.append(server_cls(device))

        self.start_all()

    def __len__(self) -> int:
        return len(self._clients)

    def __iter__(self) -> Iterator[PandoraClient]:
        return iter(self._clients)

    def start_all(self) -> None:
        """Start all Pandora servers and returns their clients."""
        if len(self._clients):
            return
        for server in self._servers:
            self._clients.append(server.start())

    def stop_all(self) -> None:
        """Closes all opened Pandora clients and servers."""
        if not len(self._clients):
            return
        for client in self:
            client.close()
        for server in self._servers:
            server.stop()
        self._clients.clear()


def _load_pandora_server_class(class_path: str) -> Type[pandora_server.PandoraServer[Any]]:
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
        raise TypeError(f'The specified class {class_path} is not a subclass of PandoraServer.')
    return server_class  # type: ignore


class Wrapper(object):
    func: Callable[..., Any]

    def __init__(self, func: Callable[..., Any]) -> None:
        self.func = func


# Multiply the same function from `inputs` parameters
def parameterized(*inputs: Tuple[Any, ...]) -> Type[Wrapper]:
    class wrapper(Wrapper):
        def __set_name__(self, owner: str, name: str) -> None:
            for input in inputs:

                def decorate(input: Tuple[Any, ...]) -> Callable[..., Any]:
                    @functools.wraps(self.func)
                    def wrapper(*args: Any, **kwargs: Any) -> Any:
                        return self.func(*args, *input, **kwargs)

                    return wrapper

                # we need to pass `input` here, otherwise it will be set to the value
                # from the last iteration of `inputs`
                setattr(owner, f"{name}{input}", decorate(input))

    return wrapper
