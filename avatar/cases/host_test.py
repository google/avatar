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
import grpc
import logging

from avatar import BumblePandoraDevice
from avatar import PandoraDevice
from avatar import PandoraDevices
from mobly import base_test
from mobly import signals
from mobly import test_runner
from mobly.asserts import assert_equal  # type: ignore
from mobly.asserts import assert_false  # type: ignore
from mobly.asserts import assert_is_none  # type: ignore
from mobly.asserts import assert_is_not_none  # type: ignore
from mobly.asserts import assert_true  # type: ignore
from mobly.asserts import explicit_pass  # type: ignore
from pandora.host_pb2 import DISCOVERABLE_GENERAL
from pandora.host_pb2 import DISCOVERABLE_LIMITED
from pandora.host_pb2 import NOT_DISCOVERABLE
from pandora.host_pb2 import Connection
from pandora.host_pb2 import DiscoverabilityMode
from typing import Optional


class HostTest(base_test.BaseTestClass):  # type: ignore[misc]
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

    @avatar.parameterized(
        (DISCOVERABLE_LIMITED,),
        (DISCOVERABLE_GENERAL,),
    )  # type: ignore[misc]
    def test_discoverable(self, mode: DiscoverabilityMode) -> None:
        self.dut.host.SetDiscoverabilityMode(mode=mode)
        inquiry = self.ref.host.Inquiry(timeout=15.0)
        try:
            assert_is_not_none(next((x for x in inquiry if x.address == self.dut.address), None))
        finally:
            inquiry.cancel()

    # This test should reach the `Inquiry` timeout.
    @avatar.rpc_except(
        {
            grpc.StatusCode.DEADLINE_EXCEEDED: lambda e: explicit_pass(e.details()),
        }
    )
    def test_not_discoverable(self) -> None:
        self.dut.host.SetDiscoverabilityMode(mode=NOT_DISCOVERABLE)
        inquiry = self.ref.host.Inquiry(timeout=3.0)
        try:
            assert_is_none(next((x for x in inquiry if x.address == self.dut.address), None))
        finally:
            inquiry.cancel()

    @avatar.asynchronous
    async def test_connect(self) -> None:
        if self.dut.name == 'android':
            raise signals.TestSkip('TODO: Android connection is too flaky (b/285634621)')
        ref_dut_res, dut_ref_res = await asyncio.gather(
            self.ref.aio.host.WaitConnection(address=self.dut.address),
            self.dut.aio.host.Connect(address=self.ref.address),
        )
        assert_is_not_none(ref_dut_res.connection)
        assert_is_not_none(dut_ref_res.connection)
        ref_dut, dut_ref = ref_dut_res.connection, dut_ref_res.connection
        assert ref_dut and dut_ref
        assert_true(await self.is_connected(self.ref, ref_dut), "")

    @avatar.asynchronous
    async def test_accept(self) -> None:
        dut_ref_res, ref_dut_res = await asyncio.gather(
            self.dut.aio.host.WaitConnection(address=self.ref.address),
            self.ref.aio.host.Connect(address=self.dut.address),
        )
        assert_is_not_none(ref_dut_res.connection)
        assert_is_not_none(dut_ref_res.connection)
        ref_dut, dut_ref = ref_dut_res.connection, dut_ref_res.connection
        assert ref_dut and dut_ref
        assert_true(await self.is_connected(self.ref, ref_dut), "")

    @avatar.asynchronous
    async def test_disconnect(self) -> None:
        if self.dut.name == 'android':
            raise signals.TestSkip('TODO: Android disconnection is too flaky (b/286081956)')
        dut_ref_res, ref_dut_res = await asyncio.gather(
            self.dut.aio.host.WaitConnection(address=self.ref.address),
            self.ref.aio.host.Connect(address=self.dut.address),
        )
        assert_is_not_none(ref_dut_res.connection)
        assert_is_not_none(dut_ref_res.connection)
        ref_dut, dut_ref = ref_dut_res.connection, dut_ref_res.connection
        assert ref_dut and dut_ref
        await self.dut.aio.host.Disconnect(connection=dut_ref)
        assert_false(await self.is_connected(self.ref, ref_dut), "")

    async def is_connected(self, device: PandoraDevice, connection: Connection) -> bool:
        try:
            await device.aio.host.WaitDisconnection(connection=connection, timeout=5)
            return False
        except grpc.RpcError as e:
            assert_equal(e.code(), grpc.StatusCode.DEADLINE_EXCEEDED)  # type: ignore
            return True


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_runner.main()  # type: ignore
