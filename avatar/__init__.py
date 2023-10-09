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

__version__ = "0.0.5"

import argparse
import enum
import functools
import grpc
import grpc.aio
import importlib
import logging
import pathlib

from avatar import pandora_server
from avatar.aio import asynchronous
from avatar.metrics import trace
from avatar.pandora_client import BumblePandoraClient as BumblePandoraDevice
from avatar.pandora_client import PandoraClient as PandoraDevice
from avatar.pandora_server import PandoraServer
from avatar.runner import SuiteRunner
from mobly import base_test
from mobly import signals
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sized, Tuple, Type, TypeVar

# public symbols
__all__ = [
    'asynchronous',
    'parameterized',
    'rpc_except',
    'PandoraDevices',
    'PandoraDevice',
    'BumblePandoraDevice',
]


PANDORA_COMMON_SERVER_CLASSES: Dict[str, Type[pandora_server.PandoraServer[Any]]] = {
    'PandoraDevice': pandora_server.PandoraServer,
    'AndroidDevice': pandora_server.AndroidPandoraServer,
    'BumbleDevice': pandora_server.BumblePandoraServer,
}

KEY_PANDORA_SERVER_CLASS = 'pandora_server_class'


class PandoraDevices(Sized, Iterable[PandoraDevice]):
    """Utility for abstracting controller registration and Pandora setup."""

    _test: base_test.BaseTestClass
    _clients: List[PandoraDevice]
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

        trace.hook_test(test, self)
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
            try:
                devices: Optional[List[Any]] = test.register_controller(  # type: ignore
                    server_cls.MOBLY_CONTROLLER_MODULE
                )
            except Exception:
                logging.exception('abort: failed to register controller')
                raise signals.TestAbortAll("")
            assert devices
            for device in devices:  # type: ignore
                self._servers.append(server_cls(device))

        self.start_all()

    def __len__(self) -> int:
        return len(self._clients)

    def __iter__(self) -> Iterator[PandoraDevice]:
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

                def normalize(a: Any) -> Any:
                    if isinstance(a, enum.Enum):
                        return a.value
                    return a

                # we need to pass `input` here, otherwise it will be set to the value
                # from the last iteration of `inputs`
                setattr(
                    owner,
                    f"{name}{tuple([normalize(a) for a in input])}".replace(" ", ""),
                    decorate(input),
                )
            delattr(owner, name)

    return wrapper


_T = TypeVar('_T')


# Decorate a test function with a wrapper that catch gRPC errors
# and call a callback if the status `code` match.
def rpc_except(
    excepts: Dict[grpc.StatusCode, Callable[[grpc.aio.AioRpcError], Any]],
) -> Callable[[Callable[..., _T]], Callable[..., _T]]:
    def wrap(func: Callable[..., _T]) -> Callable[..., _T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> _T:
            try:
                return func(*args, **kwargs)
            except (grpc.RpcError, grpc.aio.AioRpcError) as e:
                if f := excepts.get(e.code(), None):  # type: ignore
                    return f(e)  # type: ignore
                raise e

        return wrapper

    return wrap


def args_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Avatar test runner.')
    parser.add_argument(
        'input',
        type=str,
        nargs='*',
        metavar='<PATH>',
        help='Lits of folder or test file to run',
        default=[],
    )
    parser.add_argument('-c', '--config', type=str, metavar='<PATH>', help='Path to the test configuration file.')
    parser.add_argument(
        '-l',
        '--list',
        '--list_tests',  # For backward compatibility with tradefed `MoblyBinaryHostTest`
        action='store_true',
        help='Print the names of the tests defined in a script without ' 'executing them.',
    )
    parser.add_argument(
        '-o',
        '--log-path',
        '--log_path',  # For backward compatibility with tradefed `MoblyBinaryHostTest`
        type=str,
        metavar='<PATH>',
        help='Path to the test configuration file.',
    )
    parser.add_argument(
        '-t',
        '--tests',
        nargs='+',
        type=str,
        metavar='[ClassA[.test_a] ClassB[.test_b] ...]',
        help='A list of test classes and optional tests to execute.',
    )
    parser.add_argument(
        '-b',
        '--test-beds',
        '--test_bed',  # For backward compatibility with tradefed `MoblyBinaryHostTest`
        nargs='+',
        type=str,
        metavar='[<TEST BED NAME1> <TEST BED NAME2> ...]',
        help='Specify which test beds to run tests on.',
    )
    parser.add_argument('-v', '--verbose', action='store_true', help='Set console logger level to DEBUG')
    parser.add_argument('-x', '--no-default-cases', action='store_true', help='Dot no include default test cases')
    return parser


# Avatar default entry point
def main(args: Optional[argparse.Namespace] = None) -> None:
    import sys

    # Create an Avatar suite runner.
    runner = SuiteRunner()

    # Parse arguments.
    argv = args or args_parser().parse_args()
    if argv.input:
        for path in argv.input:
            runner.add_path(pathlib.Path(path))
    if argv.config:
        runner.add_config_file(pathlib.Path(argv.config))
    if argv.log_path:
        runner.set_logs_dir(pathlib.Path(argv.log_path))
    if argv.tests:
        runner.add_test_filters(argv.tests)
    if argv.test_beds:
        runner.add_test_beds(argv.test_beds)
    if argv.verbose:
        runner.set_logs_verbose()
    if not argv.no_default_cases:
        runner.add_path(pathlib.Path(__file__).resolve().parent / 'cases')

    # List tests to standard output.
    if argv.list:
        for _, (tag, test_names) in runner.included_tests.items():
            for name in test_names:
                print(f"{tag}.{name}")
        sys.exit(0)

    # Run the test suite.
    logging.basicConfig(level=logging.INFO)
    if not runner.run():
        sys.exit(1)
