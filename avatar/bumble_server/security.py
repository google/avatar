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
import grpc
import logging

from avatar.bumble_server.utils import BumbleServerLoggerAdapter, address_from_request
from bumble import hci
from bumble.core import ProtocolError, BT_BR_EDR_TRANSPORT, BT_LE_TRANSPORT
from bumble.device import Connection as BumbleConnection, Device
from bumble.hci import HCI_Error
from bumble.smp import PairingConfig, PairingDelegate as BasePairingDelegate
from contextlib import suppress
from google.protobuf import any_pb2, empty_pb2, wrappers_pb2
from google.protobuf.wrappers_pb2 import BoolValue
from pandora.host_grpc import Connection
from pandora.security_grpc import (
    DeleteBondRequest,
    IsBondedRequest,
    LESecurityLevel,
    PairingEvent,
    PairingEventAnswer,
    SecureRequest,
    SecureResponse,
    SecurityLevel,
    WaitSecurityRequest,
    WaitSecurityResponse,
)
from pandora.security_grpc_aio import SecurityServicer, SecurityStorageServicer
from typing import Any, AsyncGenerator, AsyncIterator, Callable, Dict, Optional, Union, cast


class PairingDelegate(BasePairingDelegate):
    def __init__(
        self,
        connection: BumbleConnection,
        service: "SecurityService",
        io_capability: int = BasePairingDelegate.NO_OUTPUT_NO_INPUT,
        local_initiator_key_distribution: int = BasePairingDelegate.DEFAULT_KEY_DISTRIBUTION,
        local_responder_key_distribution: int = BasePairingDelegate.DEFAULT_KEY_DISTRIBUTION,
    ) -> None:
        self.log = BumbleServerLoggerAdapter(
            logging.getLogger(), {'service_name': 'Security', 'device': connection.device}
        )
        self.connection = connection
        self.service = service
        super().__init__(io_capability, local_initiator_key_distribution, local_responder_key_distribution)

    async def accept(self) -> bool:
        return True

    def add_origin(self, ev: PairingEvent) -> PairingEvent:
        if not self.connection.is_incomplete:
            assert ev.connection
            ev.connection.CopyFrom(Connection(cookie=any_pb2.Any(value=self.connection.handle.to_bytes(4, 'big'))))
        else:
            # In BR/EDR, connection may not be complete,
            # use address instead
            assert self.connection.transport == BT_BR_EDR_TRANSPORT
            ev.address = bytes(reversed(bytes(self.connection.peer_address)))

        return ev

    async def confirm(self) -> bool:
        self.log.info(f"Pairing event: `just_works` (io_capability: {self.io_capability})")

        if not self.service.event_queue or not self.service.event_answer:
            return True

        event = self.add_origin(PairingEvent(just_works=empty_pb2.Empty()))
        self.service.event_queue.put_nowait(event)
        answer = await anext(self.service.event_answer)
        assert answer.event == event
        assert answer.confirm
        return answer.confirm

    async def compare_numbers(self, number: int, digits: int = 6) -> bool:
        self.log.info(f"Pairing event: `numeric_comparison` (io_capability: {self.io_capability})")

        if not self.service.event_queue or not self.service.event_answer:
            raise RuntimeError('security: unhandled number comparison request')

        event = self.add_origin(PairingEvent(numeric_comparison=number))
        self.service.event_queue.put_nowait(event)
        answer = await anext(self.service.event_answer)
        assert answer.event == event
        assert answer.confirm
        return answer.confirm

    async def get_number(self) -> int:
        self.log.info(f"Pairing event: `passkey_entry_request` (io_capability: {self.io_capability})")

        if not self.service.event_queue or not self.service.event_answer:
            raise RuntimeError('security: unhandled number request')

        event = self.add_origin(PairingEvent(passkey_entry_request=empty_pb2.Empty()))
        self.service.event_queue.put_nowait(event)
        answer = await anext(self.service.event_answer)
        assert answer.event == event
        assert answer.passkey is not None
        return answer.passkey

    async def display_number(self, number: int, digits: int = 6) -> None:
        self.log.info(f"Pairing event: `passkey_entry_notification` (io_capability: {self.io_capability})")

        if not self.service.event_queue:
            raise RuntimeError('security: unhandled number display request')

        event = self.add_origin(PairingEvent(passkey_entry_notification=number))
        self.service.event_queue.put_nowait(event)


BR_LEVEL_REACHED: Dict[SecurityLevel, Callable[[BumbleConnection], bool]] = {
    SecurityLevel.LEVEL0: lambda connection: True,
    SecurityLevel.LEVEL1: lambda connection: connection.encryption == 0 or connection.authenticated,
    SecurityLevel.LEVEL2: lambda connection: connection.encryption != 0 and connection.authenticated,
    SecurityLevel.LEVEL3: lambda connection: connection.encryption != 0
    and connection.authenticated
    and connection.link_key_type
    in (
        hci.HCI_AUTHENTICATED_COMBINATION_KEY_GENERATED_FROM_P_192_TYPE,
        hci.HCI_AUTHENTICATED_COMBINATION_KEY_GENERATED_FROM_P_256_TYPE,
    ),
    SecurityLevel.LEVEL4: lambda connection: connection.encryption == hci.HCI_Encryption_Change_Event.AES_CCM
    and connection.authenticated
    and connection.link_key_type == hci.HCI_AUTHENTICATED_COMBINATION_KEY_GENERATED_FROM_P_256_TYPE,
}

LE_LEVEL_REACHED: Dict[LESecurityLevel, Callable[[BumbleConnection], bool]] = {
    LESecurityLevel.LE_LEVEL1: lambda connection: True,
    LESecurityLevel.LE_LEVEL2: lambda connection: connection.encryption != 0,
    LESecurityLevel.LE_LEVEL3: lambda connection: connection.encryption != 0 and connection.authenticated,
    LESecurityLevel.LE_LEVEL4: lambda connection: connection.encryption != 0
    and connection.authenticated
    and connection.sc,
}


class SecurityService(SecurityServicer):
    def __init__(self, device: Device, io_capability: int) -> None:
        self.log = BumbleServerLoggerAdapter(logging.getLogger(), {'service_name': 'Security', 'device': device})
        self.event_queue: Optional[asyncio.Queue[PairingEvent]] = None
        self.event_answer: Optional[AsyncIterator[PairingEventAnswer]] = None
        self.device = device

        def pairing_config_factory(connection: BumbleConnection) -> PairingConfig:
            return PairingConfig(
                sc=True,
                mitm=True,
                bonding=True,
                delegate=PairingDelegate(
                    connection, self, io_capability=cast(int, getattr(self.device, 'io_capability'))
                ),
            )

        setattr(device, 'io_capability', io_capability)
        self.device.pairing_config_factory = pairing_config_factory

    async def OnPairing(
        self, request: AsyncIterator[PairingEventAnswer], context: grpc.ServicerContext
    ) -> AsyncGenerator[PairingEvent, None]:
        self.log.info('OnPairing')

        if self.event_queue:
            raise RuntimeError('already streaming pairing events')

        if len(self.device.connections):
            raise RuntimeError('the `OnPairing` method shall be initiated before establishing any connections.')

        self.event_queue = asyncio.Queue()
        self.event_answer = request

        try:
            while event := await self.event_queue.get():
                yield event

        finally:
            self.event_queue = None
            self.event_answer = None

    async def Secure(self, request: SecureRequest, context: grpc.ServicerContext) -> SecureResponse:
        connection_handle = int.from_bytes(request.connection.cookie.value, 'big')
        self.log.info(f"Secure: {connection_handle}")

        connection = self.device.lookup_connection(connection_handle)
        assert connection

        oneof = request.WhichOneof('level')
        level = getattr(request, oneof)
        assert {BT_BR_EDR_TRANSPORT: 'classic', BT_LE_TRANSPORT: 'le'}[connection.transport] == oneof

        # security level already reached
        if self.reached_security_level(connection, level):
            return SecureResponse(success=empty_pb2.Empty())

        # trigger pairing if needed
        if self.need_pairing(connection, level):
            try:
                self.log.info('Pair...')
                await connection.pair()
                self.log.info('Paired')
            except asyncio.CancelledError:
                self.log.warning(f"Connection died during encryption")
                return SecureResponse(connection_died=empty_pb2.Empty())
            except (HCI_Error, ProtocolError) as e:
                self.log.warning(f"Pairing failure: {e}")
                return SecureResponse(pairing_failure=empty_pb2.Empty())

        # trigger authentication if needed
        if self.need_authentication(connection, level):
            try:
                self.log.info('Authenticate...')
                await connection.authenticate()
                self.log.info('Authenticated')
            except asyncio.CancelledError:
                self.log.warning(f"Connection died during authentication")
                return SecureResponse(connection_died=empty_pb2.Empty())
            except (HCI_Error, ProtocolError) as e:
                self.log.warning(f"Authentication failure: {e}")
                return SecureResponse(authentication_failure=empty_pb2.Empty())

        # trigger encryption if needed
        if self.need_encryption(connection, level):
            try:
                self.log.info('Encrypt...')
                await connection.encrypt()
                self.log.info('Encrypted')
            except asyncio.CancelledError:
                self.log.warning(f"Connection died during encryption")
                return SecureResponse(connection_died=empty_pb2.Empty())
            except (HCI_Error, ProtocolError) as e:
                self.log.warning(f"Encryption failure: {e}")
                return SecureResponse(encryption_failure=empty_pb2.Empty())

        # security level has been reached ?
        if self.reached_security_level(connection, level):
            return SecureResponse(success=empty_pb2.Empty())
        return SecureResponse(not_reached=empty_pb2.Empty())

    async def WaitSecurity(self, request: WaitSecurityRequest, context: grpc.ServicerContext) -> WaitSecurityResponse:
        connection_handle = int.from_bytes(request.connection.cookie.value, 'big')
        self.log.info(f"WaitSecurity: {connection_handle}")

        connection = self.device.lookup_connection(connection_handle)
        assert connection

        assert request.level
        level = request.level
        assert {BT_BR_EDR_TRANSPORT: 'classic', BT_LE_TRANSPORT: 'le'}[connection.transport] == request.level_variant()

        wait_for_security: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        authenticate_task: Optional[asyncio.Future[None]] = None

        async def authenticate() -> None:
            assert connection
            if (encryption := connection.encryption) != 0:
                self.log.debug('Disable encryption...')
                try:
                    await connection.encrypt(enable=False)
                except:
                    pass
                self.log.debug('Disable encryption: done')

            self.log.debug('Authenticate...')
            await connection.authenticate()
            self.log.debug('Authenticate: done')

            if encryption != 0 and connection.encryption != encryption:
                self.log.debug('Re-enable encryption...')
                await connection.encrypt()
                self.log.debug('Re-enable encryption: done')

        def set_failure(name: str) -> Callable[..., None]:
            def wrapper(*args: Any) -> None:
                self.log.info(f'Wait for security: error `{name}`: {args}')
                wait_for_security.set_result(name)

            return wrapper

        def try_set_success(*_: Any) -> None:
            assert connection
            if self.reached_security_level(connection, level):
                self.log.info(f'Wait for security: done')
                wait_for_security.set_result('success')

        def on_encryption_change(*_: Any) -> None:
            assert connection
            if self.reached_security_level(connection, level):
                self.log.info(f'Wait for security: done')
                wait_for_security.set_result('success')
            elif connection.transport == BT_BR_EDR_TRANSPORT and self.need_authentication(connection, level):
                nonlocal authenticate_task
                if authenticate_task is None:
                    authenticate_task = asyncio.create_task(authenticate())

        listeners: Dict[str, Callable[..., None]] = {
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
            return WaitSecurityResponse(success=empty_pb2.Empty())

        self.log.info('Wait for security...')
        kwargs = {}
        kwargs[await wait_for_security] = empty_pb2.Empty()

        # remove event handlers
        for event, listener in listeners.items():
            connection.remove_listener(event, listener)  # type: ignore

        # wait for `authenticate` to finish if any
        if authenticate_task is not None:
            self.log.info('Wait for authentication...')
            try:
                await authenticate_task  # type: ignore
            except:
                pass
            self.log.info('Authenticated')

        return WaitSecurityResponse(**kwargs)

    def reached_security_level(
        self, connection: BumbleConnection, level: Union[SecurityLevel, LESecurityLevel]
    ) -> bool:
        self.log.debug(
            str(
                {
                    'level': level,
                    'encryption': connection.encryption,
                    'authenticated': connection.authenticated,
                    'sc': connection.sc,
                    'link_key_type': connection.link_key_type,
                }
            )
        )

        if isinstance(level, LESecurityLevel):
            return LE_LEVEL_REACHED[level](connection)

        return BR_LEVEL_REACHED[level](connection)

    def need_pairing(self, connection: BumbleConnection, level: int) -> bool:
        if connection.transport == BT_LE_TRANSPORT:
            return level >= LESecurityLevel.LE_LEVEL3 and not connection.authenticated
        return False

    def need_authentication(self, connection: BumbleConnection, level: int) -> bool:
        if connection.transport == BT_LE_TRANSPORT:
            return False
        if level == SecurityLevel.LEVEL2 and connection.encryption != 0:
            return not connection.authenticated
        return level >= SecurityLevel.LEVEL2 and not connection.authenticated

    def need_encryption(self, connection: BumbleConnection, level: int) -> bool:
        if connection.transport == BT_LE_TRANSPORT:
            return level == LESecurityLevel.LE_LEVEL2 and not connection.encryption
        return level >= SecurityLevel.LEVEL2 and not connection.encryption


class SecurityStorageService(SecurityStorageServicer):
    def __init__(self, device: Device) -> None:
        self.log = BumbleServerLoggerAdapter(
            logging.getLogger(), {'service_name': 'SecurityStorage', 'device': device}
        )
        self.device = device

    async def IsBonded(self, request: IsBondedRequest, context: grpc.ServicerContext) -> wrappers_pb2.BoolValue:
        address = address_from_request(request, request.WhichOneof("address"))
        self.log.info(f"IsBonded: {address}")

        if self.device.keystore is not None:
            is_bonded = await self.device.keystore.get(str(address)) is not None
        else:
            is_bonded = False

        return BoolValue(value=is_bonded)

    async def DeleteBond(self, request: DeleteBondRequest, context: grpc.ServicerContext) -> empty_pb2.Empty:
        address = address_from_request(request, request.WhichOneof("address"))
        self.log.info(f"DeleteBond: {address}")

        if self.device.keystore is not None:
            with suppress(KeyError):
                await self.device.keystore.delete(str(address))

        return empty_pb2.Empty()
