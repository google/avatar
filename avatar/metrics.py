""" Avatar metrics """

import grpc
import json
import logging
import time

from grpc import ClientCallDetails
from grpc._typing import RequestType, ResponseType
from grpc.aio._call import StreamStreamCall, UnaryStreamCall, UnaryUnaryCall
from grpc.aio._interceptor import ClientCallDetails
from time import localtime, strftime
from typing import Any, Callable, List, Coroutine, Union, Type, AsyncIterable
from google.protobuf.empty_pb2 import Empty

from grpc.aio._typing import RequestIterableType, ResponseIterableType, Sequence

from mobly import base_test

ClientInterceptor = Union[
    grpc.UnaryUnaryClientInterceptor,
    grpc.UnaryStreamClientInterceptor,
    grpc.StreamUnaryClientInterceptor,
    grpc.StreamStreamClientInterceptor,
]


class Call:
    def __init__(self, method_name: str, elapsed: int, start: str, stop: str, request: str, response: str) -> None:
        self.name = method_name
        self.elapsed = elapsed
        self.start = start
        self.stop = stop
        self.request = request
        self.response = response

    @classmethod
    def compute_call(cls, name: str, start: float, stop: float, request: str, response: str) -> 'Call':
        elapsed = int((stop - start) * 1000)
        cstart: str = strftime("%d-%m-%Y %H:%M:%S", localtime(start))
        cstop: str = strftime("%d-%m-%Y %H:%M:%S", localtime(stop))

        return cls(name, elapsed, cstart, cstop, request, response)


class Device:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: List[Call] = []


class Test:
    def __init__(self, name: str) -> None:
        self.name = name
        self.devices: dict[str, Device] = {}


class TestClass:
    def __init__(self, name: str) -> None:
        self.name = name
        self.tests: List[Test] = []


class MetricJsonEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Call) or isinstance(o, Device):
            return o.__dict__
        if isinstance(o, Test):

            class JsonTest:
                def __init__(self, name: str, devices: List[Device]) -> None:
                    self.name = name
                    self.devices = devices

            jsonTest = JsonTest(o.name, [d for d in o.devices.values()])
            return jsonTest.__dict__
        if isinstance(o, bytes):
            return o.decode('utf-8')
        if isinstance(o, Empty):
            return "Empty".encode('utf-8')
        return super().default(o)


test_classes: List[TestClass] = []


def append_call(device_name: str, call: Call) -> None:
    test_classes[-1].tests[-1].devices[device_name].calls.append(call)


# Class decorator to enable metrics for a specific test_bed
# Current limitation: It assumes the attributes "devices" exist in the testbed class.
def metrics(cls: Type[base_test.BaseTestClass]) -> Type[base_test.BaseTestClass]:
    original_setup_class = cls.setup_class
    original_setup_test = cls.setup_test

    def setup_class(self: base_test.BaseTestClass) -> Any:
        global test_classes
        test_classes.append(TestClass(cls.__name__))
        return original_setup_class(self)

    def setup_test(self: base_test.BaseTestClass) -> Any:
        assert hasattr(self, "devices")
        devices = getattr(self, "devices", [])
        devices[-1].metric.append_test(self.current_test_info.name)  # type: ignore
        for device in getattr(self, "devices", []):
            device.metric.setup_test(self.current_test_info.name)  # type: ignore
        return original_setup_test(self)

    cls.setup_class = setup_class
    cls.setup_test = setup_test

    return cls


class Metric:
    def __init__(self, device_name: str) -> None:
        self.log = logging.getLogger()
        self._device_name = device_name
        self._interceptors: Sequence[ClientInterceptor] = [UnaryUnaryInterceptor(device_name)]
        self._aio_interceptors: List[grpc.aio.ClientInterceptor] = [
            AioUnaryUnaryInterceptor(device_name),
            AioUnaryStreamInterceptor(device_name),
            AioStreamStreamInterceptor(device_name),
        ]

    def __del__(self) -> None:
        with open("metrics.json", "w") as f:
            end_d = [t.__dict__ for t in test_classes]
            f.write(json.dumps(end_d, indent=2, cls=MetricJsonEncoder))

    @property
    def interceptors(
        self,
    ) -> Sequence[ClientInterceptor]:
        return self._interceptors

    @property
    def aio_interceptors(self) -> List[grpc.aio.ClientInterceptor]:
        return self._aio_interceptors

    def append_test(self, test_name: str) -> None:
        test_classes[-1].tests.append(Test(test_name))

    def setup_test(self, test_name: str) -> None:
        global test_classes

        devices = test_classes[-1].tests[-1].devices
        # Append device if needed
        if self._device_name not in devices.keys():
            devices[self._device_name] = Device(self._device_name)


class UnaryUnaryInterceptor(grpc.UnaryUnaryClientInterceptor):  # type: ignore
    def __init__(self, device_name: str) -> None:
        super().__init__()
        self.device_name = device_name
        self.log = logging.getLogger()

    def intercept_unary_unary(
        self,
        continuation: Callable[[ClientCallDetails, RequestType], Any],
        client_call_details: ClientCallDetails,
        request: RequestType,
    ) -> Any:
        start = time.perf_counter()
        response = continuation(client_call_details, request)

        call = Call.compute_call(
            client_call_details.method, start, time.perf_counter(), f'{request}', f'{response.result()}'
        )
        append_call(self.device_name, call)

        return response  # type: ignore


class AioUnaryUnaryInterceptor(grpc.aio.UnaryUnaryClientInterceptor):  # type: ignore
    def __init__(self, device_name: str) -> None:
        self.device_name = device_name
        self.log = logging.getLogger()

    async def intercept_unary_unary(
        self,
        continuation: Callable[[ClientCallDetails, RequestType], UnaryUnaryCall | ResponseType],
        client_call_details: ClientCallDetails,
        request: RequestType,
    ) -> Coroutine[Any, Any, UnaryUnaryCall | ResponseType]:
        start = time.perf_counter()
        call = await continuation(client_call_details, request)  # type: ignore
        response = await call  # type: ignore
        call = Call.compute_call(client_call_details.method, start, time.perf_counter(), f'{request}', f'{response}')
        append_call(self.device_name, call)

        return response  # type: ignore


class AioUnaryStreamInterceptor(grpc.aio.UnaryStreamClientInterceptor):  # type: ignore
    def __init__(self, device_name: str) -> None:
        self.device_name = device_name

    async def intercept_unary_stream(
        self,
        continuation: Callable[[ClientCallDetails, RequestType], UnaryStreamCall],
        client_call_details: ClientCallDetails,
        request: RequestType,
    ) -> Union[ResponseIterableType, UnaryStreamCall]:
        start = time.perf_counter()
        unary_stream_call = await continuation(client_call_details, request)  # type: ignore

        async def response_iterator() -> ResponseIterableType:
            nonlocal start, unary_stream_call
            async for response in unary_stream_call:  # type: ignore
                call = Call.compute_call(
                    client_call_details.method, start, time.perf_counter(), f'{request}', f'{response}'
                )
                append_call(self.device_name, call)

                yield response

        return response_iterator()


class AioStreamStreamInterceptor(grpc.aio.StreamStreamClientInterceptor):  # type: ignore
    def __init__(self, device_name: str) -> None:
        self.device_name = device_name
        self.log = logging.getLogger()

    async def intercept_stream_stream(
        self,
        continuation: Callable[[ClientCallDetails, RequestIterableType], StreamStreamCall],
        client_call_details: ClientCallDetails,
        request_iterator: RequestIterableType,
    ) -> Union[ResponseIterableType, StreamStreamCall]:
        async def requestor() -> RequestIterableType:  # type: ignore
            assert isinstance(request_iterator, AsyncIterable)
            async for request in request_iterator:
                call = Call.compute_call(
                    client_call_details.method, time.perf_counter(), time.perf_counter(), f'{request}', ""
                )
                append_call(self.device_name, call)
                yield request

        stream_stream_call = await continuation(client_call_details, requestor())  # type: ignore

        async def response_iterator() -> ResponseIterableType:
            nonlocal stream_stream_call
            async for response in stream_stream_call:  # type: ignore
                call = Call.compute_call(
                    client_call_details.method, time.perf_counter(), time.perf_counter(), "", f'{response}'
                )
                append_call(self.device_name, call)

                yield response

        return response_iterator()
