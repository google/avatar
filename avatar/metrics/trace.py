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

"""Avatar metrics trace."""

import re
import time
import types

from avatar.metrics.trace_pb2 import (
    DebugAnnotation,
    ProcessDescriptor,
    ThreadDescriptor,
    Trace,
    TracePacket,
    TrackDescriptor,
    TrackEvent,
)
from google.protobuf.text_encoding import CUnescape
from mobly.base_test import BaseTestClass
from typing import TYPE_CHECKING, Any, Dict, List, Protocol, Union

if TYPE_CHECKING:
    from avatar.pandora_client import PandoraClient
    from avatar import PandoraDevices
else:
    PandoraClient = object
    PandoraDevices = object


packets: List[TracePacket] = []
is_class_method_override: bool = False

def process_name(test: BaseTestClass) -> str:
    return f"{test.__class__.__name__}.{test.current_test_info.name}"

def process_id(test: BaseTestClass) -> int:
    return hash(process_name(test)) & 0xFFFF

def device_id(device: PandoraClient) -> int:
    return (id(device) & 0xFFFF) | (process_id(device.test) << 0x4)

class AsTrace(Protocol):
    def as_trace(self) -> TracePacket:
        ...


class Callsite(AsTrace):
    id_counter = 0

    @classmethod
    def next_id(cls) -> int:
        cls.id_counter += 1
        return cls.id_counter

    def __init__(self, device: PandoraClient, name: Union[bytes, str], message: Any) -> None:
        self.at = time.perf_counter_ns()
        self.name = name if isinstance(name, str) else name.decode('utf-8')
        self.device = device
        self.message = message
        self.events: List[CallEvent] = []
        self.id = Callsite.next_id()

        global packets, is_class_method_override
        if not is_class_method_override:
            is_class_method_override = True
            original_teardown_class = device.test.__class__.teardown_class
            original_setup_test = device.test.__class__.setup_test

            def teardown_class(self: BaseTestClass) -> None:
                output_path: str = device.test.current_test_info.output_path  # type: ignore
                trace = Trace(packet=packets)
                with open(f"{output_path}/avatar.trace", "wb") as f:
                    f.write(trace.SerializeToString())
                original_teardown_class(self)


            def setup_test(self: BaseTestClass) -> None:
                assert hasattr(self, "devices")
                devices: PandoraDevices = getattr(self, "devices", [])
                packets.append(
                    TracePacket(
                        track_descriptor=TrackDescriptor(
                            uuid=process_id(self),
                            process=ProcessDescriptor(pid=1, process_name=process_name(self)),
                        )
                    )
                )

                for device in devices:
                    descriptor = TrackDescriptor(
                        uuid=device_id(device),
                        parent_uuid=process_id(self),
                        thread=ThreadDescriptor(thread_name=device.name, pid=1, tid=id(device) & 0xFFFF),
                    )
                    packets.append(TracePacket(track_descriptor=descriptor))

                original_setup_test(self)

            device.test.__class__.teardown_class = types.MethodType(teardown_class, device.test)
            device.test.__class__.setup_test =  types.MethodType(setup_test, device.test)

        device.log.info(f"{self}")

    def __str__(self) -> str:
        name_pretty = self.name[1:].replace('/', '.')
        if self.message is None:
            return f"%{self.id} {name_pretty}"
        message_pretty = message_prettifier(f"{self.message}")
        return f"%{self.id} {name_pretty}({message_pretty})"

    def output(self, message: Any) -> None:
        self.events.append(CallOutput(self, message))

    def input(self, message: Any) -> None:
        self.events.append(CallInput(self, message))

    def end(self, message: Any) -> None:
        global packets
        self.events.append(CallEnd(self, message))
        packets.append(self.as_trace())
        for event in self.events:
            packets.append(event.as_trace())

    def as_trace(self) -> TracePacket:
        return TracePacket(
            timestamp=self.at,
            track_event=TrackEvent(
                name=self.name,
                type=TrackEvent.Type.TYPE_SLICE_BEGIN,
                track_uuid=device_id(self.device),
                debug_annotations=None
                if self.message is None
                else [DebugAnnotation(string_value=message_prettifier(f"{self.message}"))],
            ),
            trusted_packet_sequence_id=1,
        )


class CallEvent(AsTrace):
    def __init__(self, callsite: Callsite, message: Any) -> None:
        self.at = time.perf_counter_ns()
        self.callsite = callsite
        self.message = message

        callsite.device.log.info(f"{self}")

    def __str__(self) -> str:
        return "└── " + self.stringify('->')

    def as_trace(self) -> TracePacket:
        return TracePacket(
            timestamp=self.at,
            track_event=TrackEvent(
                name=self.callsite.name,
                type=TrackEvent.Type.TYPE_INSTANT,
                track_uuid=device_id(self.callsite.device),
                debug_annotations=None
                if self.message is None
                else [DebugAnnotation(string_value=message_prettifier(f"{self.message}"))],
            ),
            trusted_packet_sequence_id=1,
        )

    def stringify(self, direction: str) -> str:
        message_pretty = message_prettifier(f"{self.message}")
        return f"[{(self.at - self.callsite.at) / 1000000000:.3f}s] {self.callsite} {direction} ({message_pretty})"


class CallOutput(CallEvent):
    def __str__(self) -> str:
        return "├── " + self.stringify('->')

    def as_trace(self) -> TracePacket:
        return super().as_trace()


class CallInput(CallEvent):
    def __str__(self) -> str:
        return "├── " + self.stringify('<-')

    def as_trace(self) -> TracePacket:
        return super().as_trace()


class CallEnd(CallEvent):
    def __str__(self) -> str:
        return "└── " + self.stringify('->')

    def as_trace(self) -> TracePacket:
        return TracePacket(
            timestamp=self.at,
            track_event=TrackEvent(
                name=self.callsite.name,
                type=TrackEvent.Type.TYPE_SLICE_END,
                track_uuid=device_id(self.callsite.device),
                debug_annotations=None
                if self.message is None
                else [DebugAnnotation(string_value=message_prettifier(f"{self.message}"))],
            ),
            trusted_packet_sequence_id=1,
        )


def message_prettifier(msg: str) -> str:
    msg = msg.replace("{\n", "{").replace("\n", ",").replace(" ", "").replace(",}", "}")
    msg = re.sub(r"{cookie{value:(\"[^\"]+\")}}", lambda m: f":{m.groups()[0]}", msg)

    def repl(addr: re.Match[str]) -> str:
        m = CUnescape(addr.groups()[0])
        if len(m) > 8:
            return ":'...'"
        if len(m) == 4 and m[0] == 0 and m[1] == 0:
            m = m[2:]
        return ":'" + ':'.join([f'{x:02X}' for x in m]) + "'"

    return re.sub(r":\"([^\"]+)\"", repl, msg)[:-1]
