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
import functools
import threading

from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Iterator, TypeVar

_T = TypeVar('_T')


class AsyncQueue(asyncio.Queue[_T], Iterable[_T]):
    def __aiter__(self) -> AsyncIterator[_T]:
        return self

    def __iter__(self) -> Iterator[_T]:
        return self

    async def __anext__(self) -> _T:
        return await self.get()

    def __next__(self) -> _T:
        return run_until_complete(self.__anext__())


# Keep running an event loop is a separate thread,
# which is then used to:
#   * Schedule Bumble(s) IO & gRPC server.
#   * Schedule asynchronous tests.
loop = asyncio.new_event_loop()


def thread_loop() -> None:
    loop.run_forever()
    loop.run_until_complete(loop.shutdown_asyncgens())


thread = threading.Thread(target=thread_loop, daemon=True)
thread.start()


# run coroutine into our loop until complete
def run_until_complete(coro: Awaitable[_T]) -> _T:
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


# Convert an asynchronous function to a synchronous one by
# executing it's code within our loop
def asynchronous(func: Callable[..., Awaitable[_T]]) -> Callable[..., _T]:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> _T:
        return run_until_complete(func(*args, **kwargs))

    return wrapper
