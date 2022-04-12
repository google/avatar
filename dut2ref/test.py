from mobly import base_test
from mobly.controllers import android_device

from dut2ref import bumble_controller
from dut2ref.android_service import AndroidService


class DutToRefTest(base_test.BaseTestClass):

    def setup_class(self):
        # For now, DUT-to-ref tests only support testing one Android DUT
        # against a Bumble device.
        self.android_devices = self.register_controller(android_device)
        self.dut = self.android_devices[0]

        self.dut.services.register('blueberry', AndroidService)
        self.dut.bt = self.dut.services.blueberry

        self.bumble_devices = self.register_controller(bumble_controller)
        self.ref = self.bumble_devices[0]
