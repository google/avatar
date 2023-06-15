from google.protobuf import descriptor as _descriptor, message as _message
from google.protobuf.internal import containers as _containers, enum_type_wrapper as _enum_type_wrapper
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Trace(_message.Message):
    __slots__ = ["packet"]
    PACKET_FIELD_NUMBER: _ClassVar[int]
    packet: _containers.RepeatedCompositeFieldContainer[TracePacket]
    def __init__(self, packet: _Optional[_Iterable[TracePacket]] = ...) -> None: ...

class TracePacket(_message.Message):
    __slots__ = ["timestamp", "track_event", "track_descriptor"]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    TRACK_EVENT_FIELD_NUMBER: _ClassVar[int]
    TRACK_DESCRIPTOR_FIELD_NUMBER: _ClassVar[int]
    timestamp: int
    track_event: TrackEvent
    track_descriptor: TrackDescriptor
    def __init__(
        self,
        timestamp: _Optional[int] = ...,
        track_event: _Optional[TrackEvent] = ...,
        track_descriptor: _Optional[TrackDescriptor] = ...,
    ) -> None: ...

class TrackDescriptor(_message.Message):
    __slots__ = ["uuid", "parent_uuid", "name", "process"]
    UUID_FIELD_NUMBER: _ClassVar[int]
    PARENT_UUID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    PROCESS_FIELD_NUMBER: _ClassVar[int]
    uuid: int
    parent_uuid: int
    name: str
    process: ProcessDescriptor
    def __init__(
        self,
        uuid: _Optional[int] = ...,
        parent_uuid: _Optional[int] = ...,
        name: _Optional[str] = ...,
        process: _Optional[ProcessDescriptor] = ...,
    ) -> None: ...

class TrackEvent(_message.Message):
    __slots__ = ["name", "type", "track_uuid", "debug_annotations"]

    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):  # type: ignore
        __slots__ = []  # type: ignore
        TYPE_UNSPECIFIED: _ClassVar[TrackEvent.Type]
        TYPE_SLICE_BEGIN: _ClassVar[TrackEvent.Type]
        TYPE_SLICE_END: _ClassVar[TrackEvent.Type]
        TYPE_INSTANT: _ClassVar[TrackEvent.Type]
        TYPE_COUNTER: _ClassVar[TrackEvent.Type]
    TYPE_UNSPECIFIED: TrackEvent.Type
    TYPE_SLICE_BEGIN: TrackEvent.Type
    TYPE_SLICE_END: TrackEvent.Type
    TYPE_INSTANT: TrackEvent.Type
    TYPE_COUNTER: TrackEvent.Type
    NAME_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    TRACK_UUID_FIELD_NUMBER: _ClassVar[int]
    DEBUG_ANNOTATIONS_FIELD_NUMBER: _ClassVar[int]
    name: str
    type: TrackEvent.Type
    track_uuid: int
    debug_annotations: _containers.RepeatedCompositeFieldContainer[DebugAnnotation]
    def __init__(
        self,
        name: _Optional[str] = ...,
        type: _Optional[_Union[TrackEvent.Type, str]] = ...,
        track_uuid: _Optional[int] = ...,
        debug_annotations: _Optional[_Iterable[DebugAnnotation]] = ...,
    ) -> None: ...

class ProcessDescriptor(_message.Message):
    __slots__ = ["process_name", "process_labels"]
    PROCESS_NAME_FIELD_NUMBER: _ClassVar[int]
    PROCESS_LABELS_FIELD_NUMBER: _ClassVar[int]
    process_name: str
    process_labels: _containers.RepeatedScalarFieldContainer[str]
    def __init__(
        self, process_name: _Optional[str] = ..., process_labels: _Optional[_Iterable[str]] = ...
    ) -> None: ...

class DebugAnnotation(_message.Message):
    __slots__ = ["string_value"]
    STRING_VALUE_FIELD_NUMBER: _ClassVar[int]
    string_value: str
    def __init__(self, string_value: _Optional[str] = ...) -> None: ...
