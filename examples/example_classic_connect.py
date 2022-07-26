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

import logging

from mobly import suite_runner, asserts, base_test

from avatar.controllers import pandora_device

from bumble.smp import PairingDelegate, PairingConfig


class ClassicConnect(base_test.BaseTestClass):
    def setup_class(self):
        self.pandora_devices = self.register_controller(pandora_device)
        self.dut = self.pandora_devices[0]
        self.bumble = self.pandora_devices[1]

    def setup_test(self):
        self.dut.host.Reset()

    def test_io_cap_keyboard_only(self):
        self._connect_to_dut(PairingDelegate.KEYBOARD_INPUT_ONLY)

    def test_display_yes_no(self):
        self._connect_to_dut(PairingDelegate.DISPLAY_OUTPUT_AND_YES_NO_INPUT)

    def test_io_cap_display_only(self):
        self._connect_to_dut(PairingDelegate.DISPLAY_OUTPUT_ONLY)

    def test_io_cap_no_input_no_output(self):
        self._connect_to_dut(PairingDelegate.NO_OUTPUT_NO_INPUT)

    def _connect_to_dut(self, io_cap):
        bumble_address = self.bumble.address
        self.bumble.device.pairing_config_factory = lambda _: PairingConfig(
            delegate=Delegate(io_cap, self.dut, bumble_address)
        )
        connect_resp = self.bumble.host.Connect(
            address=self.dut.address, wait_for_ready=True)
        asserts.assert_true(connect_resp.WhichOneof(
            "result") == "connection", "Failed to connect")


class Delegate(PairingDelegate):

  def __init__(self, io_capability, dut, address):
    super().__init__(io_capability)
    logging.info("Delegate init")
    self._dut = dut
    self._address = address

  async def get_number(self):
    logging.info("get_number")
    passkey = self._dut.host.ReadPasskey(address=self._address).passkey
    return passkey

  async def compare_numbers(self, number, digits=6):
    logging.info("compare_number")
    dut_passkey = self._dut.host.ReadPasskey(address=self._address).passkey
    return dut_passkey == number


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    suite_runner.run_suite([ClassicConnect])
