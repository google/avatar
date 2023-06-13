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


"""Avatar metrics"""

import grpc
import re
import time

from google.protobuf.text_encoding import CUnescape
from pandora import _utils as utils
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Generic,
    Iterator,
    Protocol,
    Sequence,
    TypeVar,
    Union,
)

if TYPE_CHECKING:
    from avatar.pandora_client import PandoraClient
else:
    PandoraClient = object


_T = TypeVar('_T')
_U = TypeVar('_U')
_T_co = TypeVar('_T_co', covariant=True)


ClientInterceptor = Union[
    grpc.UnaryUnaryClientInterceptor,
    grpc.UnaryStreamClientInterceptor,
    grpc.StreamStreamClientInterceptor,
]


def interceptors(device: PandoraClient) -> Sequence[ClientInterceptor]:
    return [UnaryUnaryInterceptor(device), UnaryStreamInterceptor(device), StreamStreamInterceptor(device)]


def aio_interceptors(device: PandoraClient) -> Sequence[grpc.aio.ClientInterceptor]:
    return [AioUnaryUnaryInterceptor(device), AioUnaryStreamInterceptor(device), AioStreamStreamInterceptor(device)]


class CallSite(Generic[_T]):
    id_counter = 0

    @classmethod
    def next_id(cls) -> int:
        cls.id_counter += 1
        return cls.id_counter

    def __init__(self, device: PandoraClient, name: Union[bytes, str], message: _T) -> None:
        self.id = CallSite.next_id()
        self.at = time.perf_counter()
        self.name = name if isinstance(name, str) else name.decode('utf-8')
        self.device = device
        self.message = message

        device.log.info(f"{self}")

    def __str__(self) -> str:
        name_pretty = self.name[1:].replace('/', '.')
        if self.message is None:
            return f"%{self.id} {name_pretty}"
        message_pretty = message_prettifier(f"{self.message}")
        return f"%{self.id} {name_pretty}({message_pretty})"

    def complete(self, message: _U) -> "CallCompletion[_T, _U]":
        return CallCompletion(self, message)

    def output(self: "CallSite[None]", message: _U) -> "CallOutput[_U]":
        return CallOutput(self, message)

    def input(self: "CallSite[None]", message: _U) -> "CallInput[_U]":
        return CallInput(self, message)


class CallCompletion(Generic[_T, _U]):
    def __init__(self, callsite: CallSite[_T], message: _U) -> None:
        self.at = time.perf_counter()
        self.callsite = callsite
        self.message = message

        callsite.device.log.info(f"{self}")

    def __str__(self) -> str:
        return "└── " + self.stringify('->')

    def stringify(self, direction: str) -> str:
        message_pretty = message_prettifier(f"{self.message}")
        return f"[{self.at - self.callsite.at:.3f}s] {self.callsite} {direction} ({message_pretty})"


class CallOutput(Generic[_T], CallCompletion[None, _T]):
    def __str__(self) -> str:
        return "├── " + self.stringify('->')


class CallInput(Generic[_T], CallCompletion[None, _T]):
    def __str__(self) -> str:
        return "├── " + self.stringify('<-')


class ClientCallDetails(Protocol):
    method: Union[bytes, str]


class UnaryOutcome(Protocol, Generic[_T_co]):
    def result(self) -> _T_co:
        ...


class UnaryUnaryInterceptor(grpc.UnaryUnaryClientInterceptor):  # type: ignore[misc]
    def __init__(self, device: PandoraClient) -> None:
        self.device = device

    def intercept_unary_unary(
        self,
        continuation: Callable[[ClientCallDetails, _T], UnaryOutcome[_U]],
        client_call_details: ClientCallDetails,
        request: _T,
    ) -> UnaryOutcome[_U]:
        callsite = CallSite(self.device, client_call_details.method, request)
        response = continuation(client_call_details, request)
        callsite.complete(response.result())
        return response


class UnaryStreamInterceptor(grpc.UnaryStreamClientInterceptor):  # type: ignore[misc]
    def __init__(self, device: PandoraClient) -> None:
        self.device = device

    def intercept_unary_stream(  # type: ignore
        self,
        continuation: Callable[[ClientCallDetails, _T], utils.Stream[_U]],
        client_call_details: ClientCallDetails,
        request: _T,
    ) -> utils.Stream[_U]:
        callsite = CallSite(self.device, client_call_details.method, request)
        call = continuation(client_call_details, request)

        class Proxy:
            def __iter__(self) -> Iterator[_U]:
                return self

            def __next__(self) -> _U:
                res = next(call)
                callsite.complete(res)
                return res

            def is_active(self) -> bool:
                return call.is_active()  # type: ignore

            def time_remaining(self) -> float:
                return call.time_remaining()  # type: ignore

            def cancel(self) -> None:
                return call.cancel()  # type: ignore

            def add_callback(self, callback: Any) -> None:
                return call.add_callback(callback)  # type: ignore

        return Proxy()  # type: ignore


class StreamStreamInterceptor(grpc.StreamStreamClientInterceptor):  # type: ignore[misc]
    def __init__(self, device: PandoraClient) -> None:
        self.device = device

    def intercept_stream_stream(  # type: ignore
        self,
        continuation: Callable[[ClientCallDetails, utils.Sender[_T]], utils.StreamStream[_T, _U]],
        client_call_details: ClientCallDetails,
        request: utils.Sender[_T],
    ) -> utils.StreamStream[_T, _U]:
        callsite = CallSite(self.device, client_call_details.method, None)

        class RequestProxy:
            def __iter__(self) -> Iterator[_T]:
                return self

            def __next__(self) -> _T:
                req = next(request)
                callsite.output(req)
                return req

        call = continuation(client_call_details, RequestProxy())  # type: ignore

        class Proxy:
            def __iter__(self) -> Iterator[_U]:
                return self

            def __next__(self) -> _U:
                res = next(call)
                callsite.input(res)
                return res

            def is_active(self) -> bool:
                return call.is_active()  # type: ignore

            def time_remaining(self) -> float:
                return call.time_remaining()  # type: ignore

            def cancel(self) -> None:
                return call.cancel()  # type: ignore

            def add_callback(self, callback: Any) -> None:
                return call.add_callback(callback)  # type: ignore

        return Proxy()  # type: ignore


class AioUnaryUnaryInterceptor(grpc.aio.UnaryUnaryClientInterceptor):  # type: ignore[misc]
    def __init__(self, device: PandoraClient) -> None:
        self.device = device

    async def intercept_unary_unary(  # type: ignore
        self,
        continuation: Callable[[ClientCallDetails, _T], Awaitable[Awaitable[_U]]],
        client_call_details: ClientCallDetails,
        request: _T,
    ) -> _U:
        callsite = CallSite(self.device, client_call_details.method, request)
        response = await (await continuation(client_call_details, request))
        callsite.complete(response)
        return response


class AioUnaryStreamInterceptor(grpc.aio.UnaryStreamClientInterceptor):  # type: ignore[misc]
    def __init__(self, device: PandoraClient) -> None:
        self.device = device

    async def intercept_unary_stream(  # type: ignore
        self,
        continuation: Callable[[ClientCallDetails, _T], Awaitable[utils.AioStream[_U]]],
        client_call_details: ClientCallDetails,
        request: _T,
    ) -> utils.AioStream[_U]:
        callsite = CallSite(self.device, client_call_details.method, request)
        call = await continuation(client_call_details, request)
        iter = aiter(call)

        class Proxy:
            def __aiter__(self) -> AsyncIterator[_U]:
                return self

            async def __anext__(self) -> _U:
                res = await anext(iter)
                callsite.complete(res)
                return res

            def is_active(self) -> bool:
                return call.is_active()  # type: ignore

            def time_remaining(self) -> float:
                return call.time_remaining()  # type: ignore

            def cancel(self) -> None:
                return call.cancel()  # type: ignore

            def add_callback(self, callback: Any) -> None:
                return call.add_callback(callback)  # type: ignore

        return Proxy()  # type: ignore


class AioStreamStreamInterceptor(grpc.aio.StreamStreamClientInterceptor):  # type: ignore[misc]
    def __init__(self, device: PandoraClient) -> None:
        self.device = device

    async def intercept_stream_stream(  # type: ignore
        self,
        continuation: Callable[[ClientCallDetails, utils.AioSender[_T]], Awaitable[utils.AioStreamStream[_T, _U]]],
        client_call_details: ClientCallDetails,
        request: utils.AioSender[_T],
    ) -> utils.AioStreamStream[_T, _U]:
        callsite = CallSite(self.device, client_call_details.method, None)

        class RequestProxy:
            def __aiter__(self) -> AsyncIterator[_T]:
                return self

            async def __anext__(self) -> _T:
                req = await anext(request)
                callsite.output(req)
                return req

        call = await continuation(client_call_details, RequestProxy())  # type: ignore
        iter = aiter(call)

        class ResponseProxy:
            def __aiter__(self) -> AsyncIterator[_U]:
                return self

            async def __anext__(self) -> _U:
                res = await anext(iter)
                callsite.input(res)
                return res

            def is_active(self) -> bool:
                return call.is_active()  # type: ignore

            def time_remaining(self) -> float:
                return call.time_remaining()  # type: ignore

            def cancel(self) -> None:
                return call.cancel()  # type: ignore

            def add_callback(self, callback: Any) -> None:
                return call.add_callback(callback)  # type: ignore

        return ResponseProxy()  # type: ignore


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
