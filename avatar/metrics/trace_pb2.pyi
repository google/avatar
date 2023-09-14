from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from typing import ClassVar as _ClassVar
from typing import Iterable as _Iterable
from typing import Optional as _Optional
from typing import Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Trace(_message.Message):
    __slots__ = ["packet"]
    PACKET_FIELD_NUMBER: _ClassVar[int]
    packet: _containers.RepeatedCompositeFieldContainer[TracePacket]
    def __init__(self, packet: _Optional[_Iterable[TracePacket]] = ...) -> None: ...

class TracePacket(_message.Message):
    __slots__ = ["timestamp", "track_event", "track_descriptor", "trusted_packet_sequence_id"]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    TRACK_EVENT_FIELD_NUMBER: _ClassVar[int]
    TRACK_DESCRIPTOR_FIELD_NUMBER: _ClassVar[int]
    TRUSTED_PACKET_SEQUENCE_ID_FIELD_NUMBER: _ClassVar[int]
    timestamp: int
    track_event: TrackEvent
    track_descriptor: TrackDescriptor
    trusted_packet_sequence_id: int
    def __init__(
        self,
        timestamp: _Optional[int] = ...,
        track_event: _Optional[TrackEvent] = ...,
        track_descriptor: _Optional[TrackDescriptor] = ...,
        trusted_packet_sequence_id: _Optional[int] = ...,
    ) -> None: ...

class TrackDescriptor(_message.Message):
    __slots__ = ["uuid", "parent_uuid", "name", "process", "thread"]
    UUID_FIELD_NUMBER: _ClassVar[int]
    PARENT_UUID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    PROCESS_FIELD_NUMBER: _ClassVar[int]
    THREAD_FIELD_NUMBER: _ClassVar[int]
    uuid: int
    parent_uuid: int
    name: str
    process: ProcessDescriptor
    thread: ThreadDescriptor
    def __init__(
        self,
        uuid: _Optional[int] = ...,
        parent_uuid: _Optional[int] = ...,
        name: _Optional[str] = ...,
        process: _Optional[ProcessDescriptor] = ...,
        thread: _Optional[ThreadDescriptor] = ...,
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
    __slots__ = ["pid", "process_name", "process_labels"]
    PID_FIELD_NUMBER: _ClassVar[int]
    PROCESS_NAME_FIELD_NUMBER: _ClassVar[int]
    PROCESS_LABELS_FIELD_NUMBER: _ClassVar[int]
    pid: int
    process_name: str
    process_labels: _containers.RepeatedScalarFieldContainer[str]
    def __init__(
        self,
        pid: _Optional[int] = ...,
        process_name: _Optional[str] = ...,
        process_labels: _Optional[_Iterable[str]] = ...,
    ) -> None: ...

class ThreadDescriptor(_message.Message):
    __slots__ = ["pid", "tid", "thread_name"]
    PID_FIELD_NUMBER: _ClassVar[int]
    TID_FIELD_NUMBER: _ClassVar[int]
    THREAD_NAME_FIELD_NUMBER: _ClassVar[int]
    pid: int
    tid: int
    thread_name: str
    def __init__(
        self, pid: _Optional[int] = ..., tid: _Optional[int] = ..., thread_name: _Optional[str] = ...
    ) -> None: ...

class DebugAnnotation(_message.Message):
    __slots__ = [
        "name",
        "bool_value",
        "uint_value",
        "int_value",
        "double_value",
        "string_value",
        "dict_entries",
        "array_values",
    ]
    NAME_FIELD_NUMBER: _ClassVar[int]
    BOOL_VALUE_FIELD_NUMBER: _ClassVar[int]
    UINT_VALUE_FIELD_NUMBER: _ClassVar[int]
    INT_VALUE_FIELD_NUMBER: _ClassVar[int]
    DOUBLE_VALUE_FIELD_NUMBER: _ClassVar[int]
    STRING_VALUE_FIELD_NUMBER: _ClassVar[int]
    DICT_ENTRIES_FIELD_NUMBER: _ClassVar[int]
    ARRAY_VALUES_FIELD_NUMBER: _ClassVar[int]
    name: str
    bool_value: bool
    uint_value: int
    int_value: int
    double_value: float
    string_value: str
    dict_entries: _containers.RepeatedCompositeFieldContainer[DebugAnnotation]
    array_values: _containers.RepeatedCompositeFieldContainer[DebugAnnotation]
    def __init__(
        self,
        name: _Optional[str] = ...,
        bool_value: bool = ...,
        uint_value: _Optional[int] = ...,
        int_value: _Optional[int] = ...,
        double_value: _Optional[float] = ...,
        string_value: _Optional[str] = ...,
        dict_entries: _Optional[_Iterable[DebugAnnotation]] = ...,
        array_values: _Optional[_Iterable[DebugAnnotation]] = ...,
    ) -> None: ...
