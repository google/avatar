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
from avatar.common import make_bredr_connection
from avatar.common import make_le_connection
from mobly import base_test
from mobly import test_runner
from mobly.asserts import assert_equal  # type: ignore
from mobly.asserts import assert_is_not_none  # type: ignore
from pandora import host_pb2
from pandora import l2cap_pb2
from typing import Any, Awaitable, Callable, Dict, Literal, Optional, Tuple, Union

CONNECTORS: Dict[
    str,
    Callable[[avatar.PandoraDevice, avatar.PandoraDevice], Awaitable[Tuple[host_pb2.Connection, host_pb2.Connection]]],
] = {
    'Classic': make_bredr_connection,
    'LE': make_le_connection,
}

FIXED_CHANNEL_CID = 0x3E
CLASSIC_PSM = 0xFEFF
LE_SPSM = 0xF0


class L2capTest(base_test.BaseTestClass):  # type: ignore[misc]
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
                device.config.setdefault("classic_enabled", True)

    def teardown_class(self) -> None:
        if self.devices:
            self.devices.stop_all()

    @avatar.asynchronous
    async def setup_test(self) -> None:  # pytype: disable=wrong-arg-types
        await asyncio.gather(self.dut.reset(), self.ref.reset())

    @avatar.parameterized(
        ('Classic', dict(fixed=l2cap_pb2.FixedChannelRequest(cid=FIXED_CHANNEL_CID))),
        ('LE', dict(fixed=l2cap_pb2.FixedChannelRequest(cid=FIXED_CHANNEL_CID))),
        ('Classic', dict(basic=l2cap_pb2.ConnectionOrientedChannelRequest(psm=CLASSIC_PSM))),
        (
            'LE',
            dict(
                le_credit_based=l2cap_pb2.CreditBasedChannelRequest(
                    spsm=LE_SPSM, mtu=2046, mps=2048, initial_credit=256
                )
            ),
        ),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_connect(
        self,
        transport: Union[Literal['Classic'], Literal['LE']],
        request: Dict[str, Any],
    ) -> None:
        dut_ref_acl, ref_dut_acl = await CONNECTORS[transport](self.dut, self.ref)
        server = self.ref.aio.l2cap.OnConnection(connection=ref_dut_acl, **request)
        ref_dut_res, dut_ref_res = await asyncio.gather(
            anext(aiter(server)),
            self.dut.aio.l2cap.Connect(connection=dut_ref_acl, **request),
        )
        assert_is_not_none(ref_dut_res.channel)
        assert_is_not_none(dut_ref_res.channel)

    @avatar.parameterized(
        ('Classic', dict(fixed=l2cap_pb2.FixedChannelRequest(cid=FIXED_CHANNEL_CID))),
        ('LE', dict(fixed=l2cap_pb2.FixedChannelRequest(cid=FIXED_CHANNEL_CID))),
        ('Classic', dict(basic=l2cap_pb2.ConnectionOrientedChannelRequest(psm=CLASSIC_PSM))),
        (
            'LE',
            dict(
                le_credit_based=l2cap_pb2.CreditBasedChannelRequest(
                    spsm=LE_SPSM, mtu=2046, mps=2048, initial_credit=256
                )
            ),
        ),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_on_connection(
        self,
        transport: Union[Literal['Classic'], Literal['LE']],
        request: Dict[str, Any],
    ) -> None:
        dut_ref_acl, ref_dut_acl = await CONNECTORS[transport](self.dut, self.ref)
        server = self.dut.aio.l2cap.OnConnection(connection=dut_ref_acl, **request)
        ref_dut_res, dut_ref_res = await asyncio.gather(
            self.ref.aio.l2cap.Connect(connection=ref_dut_acl, **request),
            anext(aiter(server)),
        )
        assert_is_not_none(ref_dut_res.channel)
        assert_is_not_none(dut_ref_res.channel)

    @avatar.parameterized(
        ('Classic', dict(basic=l2cap_pb2.ConnectionOrientedChannelRequest(psm=CLASSIC_PSM))),
        (
            'LE',
            dict(
                le_credit_based=l2cap_pb2.CreditBasedChannelRequest(
                    spsm=LE_SPSM, mtu=2046, mps=2048, initial_credit=256
                )
            ),
        ),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_disconnect(
        self,
        transport: Union[Literal['Classic'], Literal['LE']],
        request: Dict[str, Any],
    ) -> None:
        dut_ref_acl, ref_dut_acl = await CONNECTORS[transport](self.dut, self.ref)
        server = self.ref.aio.l2cap.OnConnection(connection=ref_dut_acl, **request)
        ref_dut_res, dut_ref_res = await asyncio.gather(
            anext(aiter(server)),
            self.dut.aio.l2cap.Connect(connection=dut_ref_acl, **request),
        )
        assert dut_ref_res.channel and ref_dut_res.channel

        await asyncio.gather(
            self.dut.aio.l2cap.Disconnect(channel=dut_ref_res.channel),
            self.ref.aio.l2cap.WaitDisconnection(channel=ref_dut_res.channel),
        )

    @avatar.parameterized(
        ('Classic', dict(basic=l2cap_pb2.ConnectionOrientedChannelRequest(psm=CLASSIC_PSM))),
        (
            'LE',
            dict(
                le_credit_based=l2cap_pb2.CreditBasedChannelRequest(
                    spsm=LE_SPSM, mtu=2046, mps=2048, initial_credit=256
                )
            ),
        ),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_wait_disconnection(
        self,
        transport: Union[Literal['Classic'], Literal['LE']],
        request: Dict[str, Any],
    ) -> None:
        dut_ref_acl, ref_dut_acl = await CONNECTORS[transport](self.dut, self.ref)
        server = self.ref.aio.l2cap.OnConnection(connection=ref_dut_acl, **request)
        ref_dut_res, dut_ref_res = await asyncio.gather(
            anext(aiter(server)),
            self.dut.aio.l2cap.Connect(connection=dut_ref_acl, **request),
        )
        assert dut_ref_res.channel and ref_dut_res.channel

        await asyncio.gather(
            self.ref.aio.l2cap.Disconnect(channel=ref_dut_res.channel),
            self.dut.aio.l2cap.WaitDisconnection(channel=dut_ref_res.channel),
        )

    @avatar.parameterized(
        ('Classic', dict(fixed=l2cap_pb2.FixedChannelRequest(cid=FIXED_CHANNEL_CID))),
        ('LE', dict(fixed=l2cap_pb2.FixedChannelRequest(cid=FIXED_CHANNEL_CID))),
        ('Classic', dict(basic=l2cap_pb2.ConnectionOrientedChannelRequest(psm=CLASSIC_PSM))),
        (
            'LE',
            dict(
                le_credit_based=l2cap_pb2.CreditBasedChannelRequest(
                    spsm=LE_SPSM, mtu=2046, mps=2048, initial_credit=256
                )
            ),
        ),
    )  # type: ignore[misc]
    @avatar.asynchronous
    async def test_send(
        self,
        transport: Union[Literal['Classic'], Literal['LE']],
        request: Dict[str, Any],
    ) -> None:
        dut_ref_acl, ref_dut_acl = await CONNECTORS[transport](self.dut, self.ref)
        server = self.dut.aio.l2cap.OnConnection(connection=dut_ref_acl, **request)
        ref_dut_res, dut_ref_res = await asyncio.gather(
            self.ref.aio.l2cap.Connect(connection=ref_dut_acl, **request),
            anext(aiter(server)),
        )
        ref_dut_channel = ref_dut_res.channel
        dut_ref_channel = dut_ref_res.channel
        assert_is_not_none(ref_dut_res.channel)
        assert_is_not_none(dut_ref_res.channel)
        assert ref_dut_channel and dut_ref_channel

        dut_ref_stream = self.ref.aio.l2cap.Receive(channel=dut_ref_channel)
        _send_res, recv_res = await asyncio.gather(
            self.dut.aio.l2cap.Send(channel=ref_dut_channel, data=b"The quick brown fox jumps over the lazy dog"),
            anext(aiter(dut_ref_stream)),
        )
        assert recv_res.data
        assert_equal(recv_res.data, b"The quick brown fox jumps over the lazy dog")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()  # type: ignore
