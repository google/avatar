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

import atexit
import time
import types

from avatar.metrics.trace_pb2 import DebugAnnotation
from avatar.metrics.trace_pb2 import ProcessDescriptor
from avatar.metrics.trace_pb2 import ThreadDescriptor
from avatar.metrics.trace_pb2 import Trace
from avatar.metrics.trace_pb2 import TracePacket
from avatar.metrics.trace_pb2 import TrackDescriptor
from avatar.metrics.trace_pb2 import TrackEvent
from google.protobuf import any_pb2
from google.protobuf import message
from mobly.base_test import BaseTestClass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, Tuple, Union

if TYPE_CHECKING:
    from avatar import PandoraDevices
    from avatar.pandora_client import PandoraClient
else:
    PandoraClient = object
    PandoraDevices = object

devices_id: Dict[PandoraClient, int] = {}
devices_process_id: Dict[PandoraClient, int] = {}
packets: List[TracePacket] = []
genesis: int = time.monotonic_ns()
output_path: Optional[Path] = None
id: int = 0


def next_id() -> int:
    global id
    id += 1
    return id


@atexit.register
def dump_trace() -> None:
    global packets, output_path
    if output_path is None:
        return
    trace = Trace(packet=packets)
    with open(output_path / "avatar.trace", "wb") as f:
        f.write(trace.SerializeToString())


def hook_test(test: BaseTestClass, devices: PandoraDevices) -> None:
    global packets, output_path

    if output_path is None:
        mobly_output_path: str = test.current_test_info.output_path  # type: ignore
        output_path = (Path(mobly_output_path) / '..' / '..').resolve()  # skip test class and method name

    original_setup_test = test.setup_test

    def setup_test(self: BaseTestClass) -> None:
        global genesis
        genesis = time.monotonic_ns()
        process_id = next_id()
        packets.append(
            TracePacket(
                track_descriptor=TrackDescriptor(
                    uuid=process_id,
                    process=ProcessDescriptor(
                        pid=process_id, process_name=f"{self.__class__.__name__}.{self.current_test_info.name}"
                    ),
                )
            )
        )

        for device in devices:
            devices_process_id[device] = process_id
            devices_id[device] = next_id()
            descriptor = TrackDescriptor(
                uuid=devices_id[device],
                parent_uuid=process_id,
                thread=ThreadDescriptor(thread_name=device.name, pid=process_id, tid=devices_id[device]),
            )
            packets.append(TracePacket(track_descriptor=descriptor))

        original_setup_test()

    test.setup_test = types.MethodType(setup_test, test)


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
        self.at = time.monotonic_ns() - genesis
        self.name = name if isinstance(name, str) else name.decode('utf-8')
        self.device = device
        self.message = message
        self.events: List[CallEvent] = []
        self.id = Callsite.next_id()

        device.log.info(f"{self}")

    def pretty(self) -> str:
        name_pretty = self.name[1:].split('.')[-1].replace('/', '.')
        if self.message is None:
            return f"%{self.id} {name_pretty}"
        message_pretty, _ = debug_message(self.message)
        return f"{name_pretty}({message_pretty})"

    def __str__(self) -> str:
        return f"{str2color('╭──', self.id)} {self.pretty()}"

    def output(self, message: Any) -> None:
        self.events.append(CallOutput(self, message))

    def input(self, message: Any) -> None:
        self.events.append(CallInput(self, message))

    def end(self, message: Any) -> None:
        global packets
        if self.device not in devices_id:
            return
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
                track_uuid=devices_id[self.device],
                debug_annotations=None
                if self.message is None
                else [
                    DebugAnnotation(name=self.message.__class__.__name__, dict_entries=debug_message(self.message)[1])
                ],
            ),
            trusted_packet_sequence_id=devices_process_id[self.device],
        )


class CallEvent(AsTrace):
    def __init__(self, callsite: Callsite, message: Any) -> None:
        self.at = time.monotonic_ns() - genesis
        self.callsite = callsite
        self.message = message

        callsite.device.log.info(f"{self}")

    def __str__(self) -> str:
        return f"{str2color('╰──', self.callsite.id)} {self.stringify('⟶ ')}"

    def as_trace(self) -> TracePacket:
        return TracePacket(
            timestamp=self.at,
            track_event=TrackEvent(
                name=self.callsite.name,
                type=TrackEvent.Type.TYPE_INSTANT,
                track_uuid=devices_id[self.callsite.device],
                debug_annotations=None
                if self.message is None
                else [
                    DebugAnnotation(name=self.message.__class__.__name__, dict_entries=debug_message(self.message)[1])
                ],
            ),
            trusted_packet_sequence_id=devices_process_id[self.callsite.device],
        )

    def stringify(self, direction: str) -> str:
        message_pretty = "" if self.message is None else debug_message(self.message)[0]
        return (
            str2color(f"[{(self.at - self.callsite.at) / 1000000000:.3f}s]", self.callsite.id)
            + f" {self.callsite.pretty()} {str2color(direction, self.callsite.id)} ({message_pretty})"
        )


class CallOutput(CallEvent):
    def __str__(self) -> str:
        return f"{str2color('├──', self.callsite.id)} {self.stringify('⟶ ')}"

    def as_trace(self) -> TracePacket:
        return super().as_trace()


class CallInput(CallEvent):
    def __str__(self) -> str:
        return f"{str2color('├──', self.callsite.id)} {self.stringify('⟵ ')}"

    def as_trace(self) -> TracePacket:
        return super().as_trace()


class CallEnd(CallEvent):
    def __str__(self) -> str:
        return f"{str2color('╰──', self.callsite.id)} {self.stringify('⟶ ')}"

    def as_trace(self) -> TracePacket:
        return TracePacket(
            timestamp=self.at,
            track_event=TrackEvent(
                name=self.callsite.name,
                type=TrackEvent.Type.TYPE_SLICE_END,
                track_uuid=devices_id[self.callsite.device],
                debug_annotations=None
                if self.message is None
                else [
                    DebugAnnotation(name=self.message.__class__.__name__, dict_entries=debug_message(self.message)[1])
                ],
            ),
            trusted_packet_sequence_id=devices_process_id[self.callsite.device],
        )


def debug_value(v: Any) -> Tuple[Any, Dict[str, Any]]:
    if isinstance(v, any_pb2.Any):
        return '...', {'string_value': f'{v}'}
    elif isinstance(v, message.Message):
        json, entries = debug_message(v)
        return json, {'dict_entries': entries}
    elif isinstance(v, bytes):
        return (v if len(v) < 16 else '...'), {'string_value': f'{v!r}'}
    elif isinstance(v, bool):
        return v, {'bool_value': v}
    elif isinstance(v, int):
        return v, {'int_value': v}
    elif isinstance(v, float):
        return v, {'double_value': v}
    elif isinstance(v, str):
        return v, {'string_value': v}
    try:
        return v, {'array_values': [DebugAnnotation(**debug_value(x)[1]) for x in v]}  # type: ignore
    except:
        return v, {'string_value': f'{v}'}


def debug_message(msg: message.Message) -> Tuple[Dict[str, Any], List[DebugAnnotation]]:
    json: Dict[str, Any] = {}
    dbga: List[DebugAnnotation] = []
    for f, v in msg.ListFields():
        if (
            isinstance(v, bytes)
            and len(v) == 6
            and ('address' in f.name or (f.containing_oneof and 'address' in f.containing_oneof.name))
        ):
            addr = ':'.join([f'{x:02X}' for x in v])
            json[f.name] = addr
            dbga.append(DebugAnnotation(name=f.name, string_value=addr))
        else:
            json_entry, dbga_entry = debug_value(v)
            json[f.name] = json_entry
            dbga.append(DebugAnnotation(name=f.name, **dbga_entry))
    return json, dbga


def str2color(s: str, id: int) -> str:
    CSI = "\x1b["
    CSI_RESET = CSI + "0m"
    CSI_BOLD = CSI + "1m"
    color = ((id * 10) % (230 - 17)) + 17
    return CSI + ("1;38;5;%dm" % color) + CSI_BOLD + s + CSI_RESET
