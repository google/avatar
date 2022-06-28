import logging

from mobly import test_runner, base_test, asserts

from grpc import RpcError

from dut2ref.controllers import pandora_device


class ExampleTest(base_test.BaseTestClass):
    def setup_class(self):
        self.pandora_devices = self.register_controller(pandora_device)
        self.dut = self.pandora_devices[0]
        self.ref = self.pandora_devices[1]

    def test_print_addresses(self):
        dut_address = self.dut.address
        self.dut.log.info(f'Address: {dut_address}')
        ref_address = self.ref.address
        self.ref.log.info(f'Address: {ref_address}')

    def test_classic_connect(self):
        dut_address = self.dut.address
        self.dut.log.info(f'Address: {dut_address}')
        try:
            self.ref.host.Connect(address=dut_address)
        except RpcError as error:
            self.dut.log.error(error)
            asserts.assert_true(False, 'gRPC Error')


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()
