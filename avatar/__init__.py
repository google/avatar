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

"""
Avatar is a scalable multi-platform Bluetooth testing tool capable of running
any Bluetooth test cases virtually and physically.
"""

__version__ = "0.0.1"


import asyncio
import functools

from threading import Thread


# Keep running an event loop is a separate thread,
# which is then used to:
#   * Schedule Bumble(s) IO & gRPC server.
#   * Schedule asynchronous tests.
loop = asyncio.new_event_loop()

def thread_loop():
    loop.run_forever()
    loop.run_until_complete(loop.shutdown_asyncgens())

thread = Thread(target=thread_loop, daemon=True)
thread.start()


# run coroutine into our loop until complete
def run_until_complete(coro):
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


# Convert an asynchronous function to a synchronous one by
# executing it's code within our loop
def asynchronous(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return run_until_complete(func(*args, **kwargs))
    return wrapper


# Multiply the same function from `inputs` parameters
def parameterized(inputs):
    class wrapper(object):
        def __init__(self, func):
            self.func = func

        def __set_name__(self, owner, name):
            for input in inputs:
                if type(input) != tuple:
                    raise ValueError(f'input type {type(input)} shall be a tuple')

                def decorate(input):
                    @functools.wraps(self.func)
                    def wrapper(*args, **kwargs):
                        return self.func(*args, *input, **kwargs)
                    return wrapper

                # we need to pass `input` here, otherwise it will be set to the value
                # from the last iteration of `inputs`
                setattr(owner, f"{name}{input}", decorate(input))

    return wrapper
