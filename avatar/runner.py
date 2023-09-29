# Copyright 2023 Google LLC
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


"""Avatar runner."""

import inspect
import logging
import os
import pathlib

from importlib.machinery import SourceFileLoader
from mobly import base_test
from mobly import config_parser
from mobly import signals
from mobly import test_runner
from typing import Dict, List, Tuple, Type

_BUMBLE_BTSNOOP_FMT = 'bumble_btsnoop_{pid}_{instance}.log'


class SuiteRunner:
    test_beds: List[str] = []
    test_run_configs: List[config_parser.TestRunConfig] = []
    test_classes: List[Type[base_test.BaseTestClass]] = []
    test_filters: List[str] = []
    logs_dir: pathlib.Path = pathlib.Path('out')
    logs_verbose: bool = False

    def set_logs_dir(self, path: pathlib.Path) -> None:
        self.logs_dir = path

    def set_logs_verbose(self, verbose: bool = True) -> None:
        self.logs_verbose = verbose

    def add_test_beds(self, test_beds: List[str]) -> None:
        self.test_beds += test_beds

    def add_test_filters(self, test_filters: List[str]) -> None:
        self.test_filters += test_filters

    def add_config_file(self, path: pathlib.Path) -> None:
        self.test_run_configs += config_parser.load_test_config_file(str(path))  # type: ignore

    def add_test_class(self, cls: Type[base_test.BaseTestClass]) -> None:
        self.test_classes.append(cls)

    def add_test_module(self, path: pathlib.Path) -> None:
        try:
            module = SourceFileLoader(path.stem, str(path)).load_module()
            classes = inspect.getmembers(module, inspect.isclass)
            for _, cls in classes:
                if issubclass(cls, base_test.BaseTestClass):
                    self.test_classes.append(cls)
        except ImportError:
            pass

    def add_path(self, path: pathlib.Path, root: bool = True) -> None:
        if path.is_file():
            if path.name.endswith('_test.py'):
                self.add_test_module(path)
            elif not self.test_run_configs and not root and path.name in ('config.yml', 'config.yaml'):
                self.add_config_file(path)
            elif root:
                raise ValueError(f'{path} is not a test file')
        else:
            for child in path.iterdir():
                self.add_path(child, root=False)

    def is_included(self, cls: base_test.BaseTestClass, test: str) -> bool:
        return not self.test_filters or any(filter_match(cls, test, filter) for filter in self.test_filters)

    @property
    def included_tests(self) -> Dict[Type[base_test.BaseTestClass], Tuple[str, List[str]]]:
        result: Dict[Type[base_test.BaseTestClass], Tuple[str, List[str]]] = {}
        for test_class in self.test_classes:
            cls = test_class(config_parser.TestRunConfig())
            test_names: List[str] = []
            try:
                # Executes pre-setup procedures, this is required since it might
                # generate test methods that we want to return as well.
                cls._pre_run()
                test_names = cls.tests or cls.get_existing_test_names()  # type: ignore
                test_names = list(test for test in test_names if self.is_included(cls, test))
                if test_names:
                    assert cls.TAG
                    result[test_class] = (cls.TAG, test_names)
            except Exception:
                logging.exception('Failed to retrieve generated tests.')
            finally:
                cls._clean_up()
        return result

    def run(self) -> bool:
        # Create logs directory.
        if not self.logs_dir.exists():
            self.logs_dir.mkdir()

        # Enable Bumble snoop logs.
        os.environ.setdefault('BUMBLE_SNOOPER', f'btsnoop:file:{self.logs_dir}/{_BUMBLE_BTSNOOP_FMT}')

        # Execute the suite
        ok = True
        for config in self.test_run_configs:
            test_bed: str = config.test_bed_name  # type: ignore
            if self.test_beds and test_bed not in self.test_beds:
                continue
            runner = test_runner.TestRunner(config.log_path, config.testbed_name)
            with runner.mobly_logger(console_level=logging.DEBUG if self.logs_verbose else logging.INFO):
                for test_class, (_, tests) in self.included_tests.items():
                    runner.add_test_class(config, test_class, tests)  # type: ignore
                try:
                    runner.run()
                    ok = ok and runner.results.is_all_pass
                except signals.TestAbortAll:
                    ok = ok and not self.test_beds
                except Exception:
                    logging.exception('Exception when executing %s.', config.testbed_name)
                    ok = False
        return ok


def filter_match(cls: base_test.BaseTestClass, test: str, filter: str) -> bool:
    tag: str = cls.TAG  # type: ignore
    if '.test_' in filter:
        return f"{tag}.{test}".startswith(filter)
    if filter.startswith('test_'):
        return test.startswith(filter)
    return tag.startswith(filter)
