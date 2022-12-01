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
import logging

from contextlib import suppress
from typing import AsyncIterator, Optional

from avatar.bumble_server.utils import address_from_request

from bumble import hci
from bumble.core import BT_BR_EDR_TRANSPORT, BT_LE_TRANSPORT
from bumble.device import Connection as BumbleConnection, Device
from bumble.hci import HCI_Error
from bumble.smp import PairingConfig, PairingDelegate as BasePairingDelegate, Session

from google.protobuf.any_pb2 import Any
from google.protobuf.empty_pb2 import Empty
from google.protobuf.wrappers_pb2 import BoolValue

from pandora.host_pb2 import Connection

from pandora.security_grpc import SecurityServicer, SecurityStorageServicer
from pandora.security_pb2 import (
    SecurityLevel, LESecurityLevel,
    PairingEvent, PairingEventAnswer,
    SecureResponse, WaitSecurityResponse
)


class PairingDelegate(BasePairingDelegate):

    def __init__(self,
        connection: BumbleConnection,
        service: "SecurityService",
        **kwargs
    ):
        self.connection = connection
        self.service = service
        super().__init__(**kwargs)

    async def accept(self):
        return True

    def build_event(self, **kwargs):
        if self.connection.handle is not None:
            kwargs['connection'] = Connection(cookie=Any(value=self.connection.handle.to_bytes(4, 'big')))
        else:
            # In BR/EDR, connection may not be complete,
            # use address instead
            assert self.connection.transport == BT_BR_EDR_TRANSPORT
            kwargs['address'] = bytes(reversed(bytes(self.connection.peer_address)))

        return PairingEvent(**kwargs)

    async def confirm(self):
        logging.info(f"Pairing event: `just_works` (io_capability: {self.io_capability})")

        if not self.service.event_queue:
            return True

        self.service.event_queue.put_nowait((event := self.build_event(just_works=Empty())))
        answer = await anext(self.service.event_answer)
        assert answer.event == event

        return answer.confirm

    async def compare_numbers(self, number, digits=6):
        logging.info(f"Pairing event: `numeric_comparison` (io_capability: {self.io_capability})")

        if not self.service.event_queue:
            raise RuntimeError('security: unhandled number comparison request')

        self.service.event_queue.put_nowait((event := self.build_event(numeric_comparison=number)))
        answer = await anext(self.service.event_answer)
        assert answer.event == event

        return answer.confirm

    async def get_number(self):
        logging.info(f"Pairing event: `passkey_entry_request` (io_capability: {self.io_capability})")

        if not self.service.event_queue:
            raise RuntimeError('security: unhandled number request')

        self.service.event_queue.put_nowait((event := self.build_event(passkey_entry_request=Empty())))
        answer = await anext(self.service.event_answer)
        assert answer.event == event

        return answer.passkey

    async def display_number(self, number, digits=6):
        logging.info(f"Pairing event: `passkey_entry_notification` (io_capability: {self.io_capability})")

        if not self.service.event_queue:
            raise RuntimeError('security: unhandled number display request')

        self.service.event_queue.put_nowait(self.build_event(passkey_entry_notification=number))


class SecurityService(SecurityServicer):

    def __init__(self, device: Device, io_capability):
        super().__init__()
        self.event_queue: asyncio.Queue = None
        self.event_answer: Optional[AsyncIterator[PairingEventAnswer]] = None
        self.device = device
        self.device.io_capability = io_capability
        self.device.pairing_config_factory = lambda connection: PairingConfig(
            sc=True, mitm=True, bonding=True,
            delegate=PairingDelegate(
                connection, self,
                io_capability=self.device.io_capability,
            )
        )

    async def OnPairing(self, event_answer, context):
        logging.info('OnPairing')

        if self.event_queue:
            raise RuntimeError('already streaming pairing events')

        if len(self.device.connections):
            raise RuntimeError('the `OnPairing` method shall be initiated before establishing any connections.')

        self.event_queue = asyncio.Queue()
        self.event_answer = event_answer

        try:
            while event := await self.event_queue.get():
                yield event

        finally:
            self.event_queue = None
            self.event_answer = None

    async def Secure(self, request, context):
        connection_handle = int.from_bytes(request.connection.cookie.value, 'big')
        logging.info(f"Secure: {connection_handle}")

        connection: BumbleConnection = self.device.lookup_connection(connection_handle)
        assert connection

        oneof = request.WhichOneof('level')
        level = getattr(request, oneof)
        assert { BT_BR_EDR_TRANSPORT: 'classic', BT_LE_TRANSPORT: 'le' }[connection.transport] == oneof

        # security level already reached
        if self.reached_security_level(connection, level):
            return SecureResponse(success=Empty())

        # trigger pairing if needed
        if self.need_pairing(connection, level):
            try:
                logging.info('Pair...')
                await connection.pair()
                logging.info('Paired')
            except asyncio.CancelledError:
                logging.warning(f"Connection died during encryption")
                return SecureResponse(connection_died=Empty())
            except HCI_Error as e:
                logging.warning(f"Pairing failure: {e}")
                return SecureResponse(pairing_failure=Empty())

        # trigger authentication if needed
        if self.need_authentication(connection, level):
            try:
                logging.info('Authenticate...')
                await connection.authenticate()
                logging.info('Authenticated')
            except asyncio.CancelledError:
                logging.warning(f"Connection died during authentication")
                return SecureResponse(connection_died=Empty())
            except HCI_Error as e:
                logging.warning(f"Authentication failure: {e}")
                return SecureResponse(authentication_failure=Empty())

        # trigger encryption if needed
        if self.need_encryption(connection, level):
            try:
                logging.info('Encrypt...')
                await connection.encrypt()
                logging.info('Encrypted')
            except asyncio.CancelledError:
                logging.warning(f"Connection died during encryption")
                return SecureResponse(connection_died=Empty())
            except HCI_Error as e:
                logging.warning(f"Encryption failure: {e}")
                return SecureResponse(encryption_failure=Empty())

        # security level has been reached ?
        if self.reached_security_level(connection, level):
            return SecureResponse(success=Empty())
        return SecureResponse(not_reached=Empty())


    async def WaitSecurity(self, request, context):
        connection_handle = int.from_bytes(request.connection.cookie.value, 'big')
        logging.info(f"WaitSecurity: {connection_handle}")

        connection: BumbleConnection = self.device.lookup_connection(connection_handle)
        assert connection

        oneof = request.WhichOneof('level')
        level = getattr(request, oneof)
        assert { BT_BR_EDR_TRANSPORT: 'classic', BT_LE_TRANSPORT: 'le' }[connection.transport] == oneof

        wait_for_security = asyncio.get_running_loop().create_future()
        authenticate_task = None

        async def authenticate():
            if (encryption := connection.encryption) != 0:
                logging.debug('Disable encryption...')
                try: await connection.encrypt(enable=0x00)
                except: pass
                logging.debug('Disable encryption: done')

            logging.debug('Authenticate...')
            await connection.authenticate()
            logging.debug('Authenticate: done')

            if encryption != 0 and connection.encryption != encryption:
                logging.debug('Re-enable encryption...')
                await connection.encrypt()
                logging.debug('Re-enable encryption: done')

        def set_failure(name):
            def wrapper(*args):
                logging.info(f'Wait for security: error `{name}`: {args}')
                wait_for_security.set_result(name)
            return wrapper

        def try_set_success(*_):
            if self.reached_security_level(connection, level):
                logging.info(f'Wait for security: done')
                wait_for_security.set_result('success')

        def on_encryption_change(*_):
            if self.reached_security_level(connection, level):
                logging.info(f'Wait for security: done')
                wait_for_security.set_result('success')
            elif connection.transport == BT_BR_EDR_TRANSPORT and self.need_authentication(connection, level):
                nonlocal authenticate_task
                if authenticate_task is None:
                    authenticate_task = asyncio.create_task(authenticate())

        listeners = {
            'disconnection': set_failure('connection_died'),
            'pairing_failure': set_failure('pairing_failure'),
            'connection_authentication_failure': set_failure('authentication_failure'),
            'connection_encryption_failure': set_failure('encryption_failure'),
            'pairing': try_set_success,
            'connection_authentication': try_set_success,
            'connection_encryption_change': on_encryption_change,
        }

        # register event handlers
        for event, listener in listeners.items():
            connection.on(event, listener)

        # security level already reached
        if self.reached_security_level(connection, level):
            return WaitSecurityResponse(success=Empty())

        logging.info('Wait for security...')
        kwargs = {}
        kwargs[await wait_for_security] = Empty()

        # remove event handlers
        for event, listener in listeners.items():
            connection.remove_listener(event, listener)

        # wait for `authenticate` to finish if any
        if authenticate_task is not None:
            try: await authenticate_task
            except: pass

        return WaitSecurityResponse(**kwargs)

    def reached_security_level(self, connection: BumbleConnection, level: int):
        logging.debug(str({
            'level': level,
            'encryption': connection.encryption,
            'authenticated': connection.authenticated,
            'sc': connection.sc,
            'link_key_type': connection.link_key_type
        }))

        if connection.transport == BT_LE_TRANSPORT:
            return {
                LESecurityLevel.LE_LEVEL1: lambda:
                    True,
                LESecurityLevel.LE_LEVEL2: lambda:
                    connection.encryption != 0,
                LESecurityLevel.LE_LEVEL3: lambda:
                    connection.encryption != 0 and
                    connection.authenticated,
                LESecurityLevel.LE_LEVEL4: lambda:
                    connection.encryption != 0 and
                    connection.authenticated and
                    connection.sc,
            }[level]()

        return {
            SecurityLevel.LEVEL0: lambda:
                True,
            SecurityLevel.LEVEL1: lambda:
                connection.encryption == 0 or connection.authenticated,
            SecurityLevel.LEVEL2: lambda:
                connection.encryption != 0 and
                connection.authenticated,
            SecurityLevel.LEVEL3: lambda:
                connection.encryption != 0 and
                connection.authenticated and
                connection.link_key_type in (hci.HCI_AUTHENTICATED_COMBINATION_KEY_GENERATED_FROM_P_192_TYPE, hci.HCI_AUTHENTICATED_COMBINATION_KEY_GENERATED_FROM_P_256_TYPE),
            SecurityLevel.LEVEL4: lambda:
                connection.encryption == hci.HCI_Encryption_Change_Event.AES_CCM and
                connection.authenticated and
                connection.link_key_type == hci.HCI_AUTHENTICATED_COMBINATION_KEY_GENERATED_FROM_P_256_TYPE,
        }[level]()

    def need_pairing(self, connection: BumbleConnection, level: int):
        if connection.transport == BT_LE_TRANSPORT:
            return level >= LESecurityLevel.LE_LEVEL3 and not connection.authenticated
        return False

    def need_authentication(self, connection: BumbleConnection, level: int):
        if connection.transport == BT_LE_TRANSPORT:
            return False
        if level == SecurityLevel.LEVEL2 and connection.encryption != 0:
            return not connection.authenticated
        return level >= SecurityLevel.LEVEL2 and not connection.authenticated

    def need_encryption(self, connection: BumbleConnection, level: int):
        if connection.transport == BT_LE_TRANSPORT:
            return level == LESecurityLevel.LE_LEVEL2 and not connection.encryption
        return level >= SecurityLevel.LEVEL2 and not connection.encryption

class SecurityStorageService(SecurityStorageServicer):

    def __init__(self, device: Device):
        super().__init__()
        self.device = device

    async def IsBonded(self, request, context):
        address = address_from_request(request, request.WhichOneof("address"))
        logging.info(f"IsBonded: {address}")

        if self.device.keystore is not None:
            is_bonded = await self.device.keystore.get(str(address)) is not None
        else:
            is_bonded = False

        return BoolValue(value=is_bonded)

    async def DeleteBond(self, request, context):
        address = address_from_request(request, request.WhichOneof("address"))
        logging.info(f"DeleteBond: {address}")

        if self.device.keystore is not None:
            with suppress(KeyError):
                await self.device.keystore.delete(str(address))

        return Empty()
