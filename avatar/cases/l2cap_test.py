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

import asyncio
import avatar
import logging

from avatar import BumblePandoraDevice
from avatar import PandoraDevice
from avatar import PandoraDevices
from avatar import pandora_snippet
from mobly import base_test
from mobly import test_runner
from mobly.asserts import assert_equal  # type: ignore
from mobly.asserts import assert_is_not_none  # type: ignore
from pandora import host_pb2
from typing import Any, Dict, Optional

CLASSIC_PSM = 0xFEFF
LE_SPSM = 0xF0


class L2capTest(base_test.BaseTestClass):  # type: ignore[misc]
    devices: Optional[PandoraDevices] = None

    # pandora devices.
    dut: PandoraDevice
    ref: PandoraDevice

    # BR/EDR & Low-Energy connections.
    dut_ref: Dict[str, host_pb2.Connection] = {}
    ref_dut: Dict[str, host_pb2.Connection] = {}

    def setup_class(self) -> None:
        self.devices = PandoraDevices(self)
        self.dut, self.ref, *_ = self.devices

        # Enable BR/EDR mode for Bumble devices.
        for device in self.devices:
            if isinstance(device, BumblePandoraDevice):
                device.config.setdefault("classic_enabled", True)

    def teardown_class(self) -> None:
        if self.devices:
            self.devices.stop_all()

    @avatar.asynchronous
    async def setup_test(self) -> None:  # pytype: disable=wrong-arg-types
        await asyncio.gather(self.dut.reset(), self.ref.reset())

        # Connect REF to DUT in both BR/EDR and Low-Energy.
        ref_dut_br, dut_ref_br = await pandora_snippet.connect(self.ref, self.dut)
        ref_dut_le, dut_ref_le = await pandora_snippet.connect_le_dummy(self.ref, self.dut)

        self.dut_ref = dict(basic=dut_ref_br, le_credit_based=dut_ref_le)
        self.ref_dut = dict(basic=ref_dut_br, le_credit_based=ref_dut_le)

    @avatar.parameterized(
        (dict(basic=dict(psm=CLASSIC_PSM)),),
        (dict(le_credit_based=dict(spsm=LE_SPSM, mtu=2046, mps=2048, initial_credit=256)),),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_connect(
        self,
        request: Dict[str, Any],
    ) -> None:
        transport = next(iter(request.keys()))
        ref_dut, dut_ref = await asyncio.gather(
            self.ref.aio.l2cap.WaitConnection(connection=self.ref_dut[transport], **request),
            self.dut.aio.l2cap.Connect(connection=self.dut_ref[transport], **request),
        )
        assert_is_not_none(ref_dut.channel)
        assert_is_not_none(dut_ref.channel)

    @avatar.parameterized(
        (dict(basic=dict(psm=CLASSIC_PSM)),),
        (dict(le_credit_based=dict(spsm=LE_SPSM, mtu=2046, mps=2048, initial_credit=256)),),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_wait_connection(
        self,
        request: Dict[str, Any],
    ) -> None:
        transport = next(iter(request.keys()))
        dut_ref, ref_dut = await asyncio.gather(
            self.ref.aio.l2cap.WaitConnection(connection=self.dut_ref[transport], **request),
            self.dut.aio.l2cap.Connect(connection=self.ref_dut[transport], **request),
        )
        assert_is_not_none(ref_dut.channel)
        assert_is_not_none(dut_ref.channel)

    @avatar.parameterized(
        (dict(basic=dict(psm=CLASSIC_PSM)),),
        (dict(le_credit_based=dict(spsm=LE_SPSM, mtu=2046, mps=2048, initial_credit=256)),),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_disconnect(
        self,
        request: Dict[str, Any],
    ) -> None:
        transport = next(iter(request.keys()))
        dut_ref, ref_dut = await asyncio.gather(
            self.ref.aio.l2cap.WaitConnection(connection=self.dut_ref[transport], **request),
            self.dut.aio.l2cap.Connect(connection=self.ref_dut[transport], **request),
        )
        assert_is_not_none(ref_dut.channel)
        assert_is_not_none(dut_ref.channel)
        assert ref_dut.channel and dut_ref.channel

        _, dis = await asyncio.gather(
            self.ref.aio.l2cap.WaitDisconnection(channel=ref_dut.channel),
            self.dut.aio.l2cap.Disconnect(channel=dut_ref.channel),
        )

        assert_equal(dis.result_variant(), 'success')

    @avatar.parameterized(
        (dict(basic=dict(psm=CLASSIC_PSM)),),
        (dict(le_credit_based=dict(spsm=LE_SPSM, mtu=2046, mps=2048, initial_credit=256)),),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_wait_disconnection(
        self,
        request: Dict[str, Any],
    ) -> None:
        transport = next(iter(request.keys()))
        dut_ref, ref_dut = await asyncio.gather(
            self.ref.aio.l2cap.WaitConnection(connection=self.dut_ref[transport], **request),
            self.dut.aio.l2cap.Connect(connection=self.ref_dut[transport], **request),
        )
        assert_is_not_none(ref_dut.channel)
        assert_is_not_none(dut_ref.channel)
        assert ref_dut.channel and dut_ref.channel

        dis, _ = await asyncio.gather(
            self.dut.aio.l2cap.WaitDisconnection(channel=dut_ref.channel),
            self.ref.aio.l2cap.Disconnect(channel=ref_dut.channel),
        )

        assert_equal(dis.result_variant(), 'success')

    @avatar.parameterized(
        (dict(basic=dict(psm=CLASSIC_PSM)),),
        (dict(le_credit_based=dict(spsm=LE_SPSM, mtu=2046, mps=2048, initial_credit=256)),),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_send(
        self,
        request: Dict[str, Any],
    ) -> None:
        transport = next(iter(request.keys()))
        dut_ref, ref_dut = await asyncio.gather(
            self.ref.aio.l2cap.WaitConnection(connection=self.dut_ref[transport], **request),
            self.dut.aio.l2cap.Connect(connection=self.ref_dut[transport], **request),
        )
        assert_is_not_none(ref_dut.channel)
        assert_is_not_none(dut_ref.channel)
        assert ref_dut.channel and dut_ref.channel

        ref_source = self.ref.aio.l2cap.Receive(channel=dut_ref.channel)
        _, recv = await asyncio.gather(
            self.dut.aio.l2cap.Send(channel=ref_dut.channel, data=b"The quick brown fox jumps over the lazy dog"),
            anext(aiter(ref_source)),
        )

        assert_equal(recv.data, b"The quick brown fox jumps over the lazy dog")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()  # type: ignore
