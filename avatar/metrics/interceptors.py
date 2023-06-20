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

"""Avatar metrics interceptors."""

import grpc
import time

from avatar.metrics.trace import Callsite
from grpc.aio import ClientCallDetails
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
        callsite = Callsite(self.device, client_call_details.method, request)
        response = continuation(client_call_details, request)
        callsite.end(response.result())
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
        callsite = Callsite(self.device, client_call_details.method, request)
        call = continuation(client_call_details, request)
        call.add_callback(lambda: callsite.end(None))  # type: ignore

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


class StreamStreamInterceptor(grpc.StreamStreamClientInterceptor):  # type: ignore[misc]
    def __init__(self, device: PandoraClient) -> None:
        self.device = device

    def intercept_stream_stream(  # type: ignore
        self,
        continuation: Callable[[ClientCallDetails, utils.Sender[_T]], utils.StreamStream[_T, _U]],
        client_call_details: ClientCallDetails,
        request: utils.Sender[_T],
    ) -> utils.StreamStream[_T, _U]:
        callsite = Callsite(self.device, client_call_details.method, None)

        class RequestProxy:
            def __iter__(self) -> Iterator[_T]:
                return self

            def __next__(self) -> _T:
                req = next(request)
                callsite.output(req)
                return req

        call = continuation(client_call_details, RequestProxy())  # type: ignore
        call.add_callback(lambda: callsite.end(None))  # type: ignore

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
        callsite = Callsite(self.device, client_call_details.method, request)
        response = await (await continuation(client_call_details, request))
        callsite.end(response)
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
        # TODO: this is a workaround for https://github.com/grpc/grpc/pull/33951
        #  need to be deleted as soon as `grpcio` contains the fix.
        now = time.time()
        if client_call_details.timeout and client_call_details.timeout > now:
            client_call_details = client_call_details._replace(
                timeout=client_call_details.timeout - now,
            )

        callsite = Callsite(self.device, client_call_details.method, request)
        call = await continuation(client_call_details, request)
        call.add_done_callback(lambda _: callsite.end(None))  # type: ignore
        iter = aiter(call)

        class Proxy:
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

            def add_done_callback(self, callback: Any) -> None:
                return call.add_done_callback(callback)  # type: ignore

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
        # TODO: this is a workaround for https://github.com/grpc/grpc/pull/33951
        #  need to be deleted as soon as `grpcio` contains the fix.
        now = time.time()
        if client_call_details.timeout and client_call_details.timeout > now:
            client_call_details = client_call_details._replace(
                timeout=client_call_details.timeout - now,
            )

        callsite = Callsite(self.device, client_call_details.method, None)

        class RequestProxy:
            def __aiter__(self) -> AsyncIterator[_T]:
                return self

            async def __anext__(self) -> _T:
                req = await anext(request)
                callsite.output(req)
                return req

        call = await continuation(client_call_details, RequestProxy())  # type: ignore
        call.add_done_callback(lambda _: callsite.end(None))  # type: ignore
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

            def add_done_callback(self, callback: Any) -> None:
                return call.add_done_callback(callback)  # type: ignore

        return ResponseProxy()  # type: ignore
