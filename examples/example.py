import logging

from mobly import suite_runner, asserts
from grpc import RpcError

from dut2ref.test import DutToRefTest


class ExampleTest(DutToRefTest):

    def test_print_addresses(self):
        dut_address = self.dut.bt.read_local_address()
        self.dut.log.info(f'Address: {dut_address}')
        ref_address = self.ref.read_local_address()
        self.ref.log.info(f'Address: {ref_address}')

    def test_classic_connect(self):
        dut_address = self.dut.bt.read_local_address()
        self.dut.log.info(f'Address: {dut_address}')
        try:
            self.ref.connect(address=dut_address)
        except RpcError as error:
            self.dut.log.error(error)
            asserts.assert_true(False, 'gRPC Error')


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    # Use suite runner since test runner does not work with superclass of
    # mobly.base_test.BaseTestClass.
    suite_runner.run_suite([ExampleTest])
