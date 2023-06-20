import argparse
import logging
import os

from argparse import Namespace
from mobly import suite_runner
from typing import List, Tuple

_BUMBLE_BTSNOOP_FMT = 'bumble_btsnoop_{pid}_{instance}.log'

# Import test cases modules.
import host_test
import le_host_test
import le_security_test
import security_test

_TEST_CLASSES_LIST = [
    host_test.HostTest,
    le_host_test.LeHostTest,
    security_test.SecurityTest,
    le_security_test.LeSecurityTest,
]


def _parse_cli_args() -> Tuple[Namespace, List[str]]:
    parser = argparse.ArgumentParser(description='Avatar test runner.')
    parser.add_argument('-o', '--log_path', type=str, metavar='<PATH>', help='Path to the test configuration file.')
    return parser.parse_known_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Enable bumble snoop logger.
    ns, argv = _parse_cli_args()
    if ns.log_path:
        os.environ.setdefault('BUMBLE_SNOOPER', f'btsnoop:file:{ns.log_path}/{_BUMBLE_BTSNOOP_FMT}')

    # Run the test suite.
    suite_runner.run_suite(_TEST_CLASSES_LIST, argv)  # type: ignore
