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

import asyncio
import avatar
import logging

from avatar import BumblePandoraDevice, PandoraDevice, PandoraDevices
from bumble.pairing import PairingDelegate
from concurrent import futures
from contextlib import suppress
from mobly import base_test, signals, test_runner
from mobly.asserts import assert_equal  # type: ignore
from mobly.asserts import assert_in  # type: ignore
from mobly.asserts import assert_is_not_none  # type: ignore
from mobly.asserts import fail  # type: ignore
from pandora.host_pb2 import PUBLIC, RANDOM, DataTypes, OwnAddressType
from pandora.security_pb2 import LE_LEVEL3, PairingEventAnswer
from typing import NoReturn, Optional


class LeSecurityTest(base_test.BaseTestClass):  # type: ignore[misc]
    devices: Optional[PandoraDevices] = None

    # pandora devices.
    dut: PandoraDevice
    ref: PandoraDevice

    def setup_class(self) -> None:
        self.devices = PandoraDevices(self)
        self.dut, self.ref, *_ = self.devices

        # Enable BR/EDR mode for Bumble devices.
        for device in self.devices:
            if isinstance(device, BumblePandoraDevice):
                device.config.setdefault('classic_enabled', True)

    def teardown_class(self) -> None:
        if self.devices:
            self.devices.stop_all()

    @avatar.asynchronous
    async def setup_test(self) -> None:  # pytype: disable=wrong-arg-types
        await asyncio.gather(self.dut.reset(), self.ref.reset())

    async def handle_pairing_events(self) -> NoReturn:
        ref_pairing_stream = self.ref.aio.security.OnPairing()
        dut_pairing_stream = self.dut.aio.security.OnPairing()

        try:
            while True:
                ref_pairing_event, dut_pairing_event = await asyncio.gather(
                    anext(ref_pairing_stream),  # pytype: disable=name-error
                    anext(dut_pairing_stream),  # pytype: disable=name-error
                )

                if dut_pairing_event.method_variant() in ('numeric_comparison', 'just_works'):
                    assert_in(ref_pairing_event.method_variant(), ('numeric_comparison', 'just_works'))
                    dut_pairing_stream.send_nowait(
                        PairingEventAnswer(
                            event=dut_pairing_event,
                            confirm=True,
                        )
                    )
                    ref_pairing_stream.send_nowait(
                        PairingEventAnswer(
                            event=ref_pairing_event,
                            confirm=True,
                        )
                    )
                elif dut_pairing_event.method_variant() == 'passkey_entry_notification':
                    assert_equal(ref_pairing_event.method_variant(), 'passkey_entry_request')
                    ref_pairing_stream.send_nowait(
                        PairingEventAnswer(
                            event=ref_pairing_event,
                            passkey=dut_pairing_event.passkey_entry_notification,
                        )
                    )
                elif dut_pairing_event.method_variant() == 'passkey_entry_request':
                    assert_equal(ref_pairing_event.method_variant(), 'passkey_entry_notification')
                    dut_pairing_stream.send_nowait(
                        PairingEventAnswer(
                            event=dut_pairing_event,
                            passkey=ref_pairing_event.passkey_entry_notification,
                        )
                    )
                else:
                    fail("unreachable")

        finally:
            ref_pairing_stream.cancel()
            dut_pairing_stream.cancel()

    @avatar.parameterized(
        (RANDOM, RANDOM, PairingDelegate.NO_OUTPUT_NO_INPUT),
        (RANDOM, RANDOM, PairingDelegate.KEYBOARD_INPUT_ONLY),
        (RANDOM, RANDOM, PairingDelegate.DISPLAY_OUTPUT_ONLY),
        (RANDOM, RANDOM, PairingDelegate.DISPLAY_OUTPUT_AND_YES_NO_INPUT),
        (RANDOM, RANDOM, PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT),
        (RANDOM, PUBLIC, PairingDelegate.DISPLAY_OUTPUT_AND_KEYBOARD_INPUT),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_pairing(  # pytype: disable=wrong-arg-types
        self,
        dut_address_type: OwnAddressType,
        ref_address_type: OwnAddressType,
        ref_io_capability: PairingDelegate.IoCapability,
    ) -> None:
        if not isinstance(self.ref, BumblePandoraDevice):
            raise signals.TestSkip('Test require Bumble as reference device(s)')

        # override reference device IO capability
        self.ref.server_config.io_capability = ref_io_capability

        advertisement = self.dut.aio.host.Advertise(
            legacy=True,
            connectable=True,
            own_address_type=dut_address_type,
            data=DataTypes(manufacturer_specific_data=b'pause cafe'),
        )

        scan = self.ref.aio.host.Scan(own_address_type=ref_address_type)
        dut = await anext(
            (x async for x in scan if b'pause cafe' in x.data.manufacturer_specific_data)
        )  # pytype: disable=name-error
        scan.cancel()

        pairing = asyncio.create_task(self.handle_pairing_events())
        (ref_dut_res, dut_ref_res) = await asyncio.gather(
            self.ref.aio.host.ConnectLE(own_address_type=ref_address_type, **dut.address_asdict()),
            anext(aiter(advertisement)),  # pytype: disable=name-error
        )

        advertisement.cancel()
        ref_dut, dut_ref = ref_dut_res.connection, dut_ref_res.connection
        assert_is_not_none(ref_dut)
        assert ref_dut

        (secure, wait_security) = await asyncio.gather(
            self.ref.aio.security.Secure(connection=ref_dut, le=LE_LEVEL3),
            self.dut.aio.security.WaitSecurity(connection=dut_ref, le=LE_LEVEL3),
        )

        pairing.cancel()
        with suppress(asyncio.CancelledError, futures.CancelledError):
            await pairing

        assert_equal(secure.result_variant(), 'success')
        assert_equal(wait_security.result_variant(), 'success')

        await asyncio.gather(
            self.dut.aio.host.Disconnect(connection=dut_ref),
            self.ref.aio.host.WaitDisconnection(connection=ref_dut),
        )


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()  # type: ignore
