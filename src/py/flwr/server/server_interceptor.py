# Copyright 2024 Flower Labs GmbH. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Flower server interceptor."""

import base64
import threading
from logging import INFO
from typing import Any, Callable, Sequence, Set, Tuple, Union

import grpc
from cryptography.hazmat.primitives.asymmetric import ec

from flwr.common.logger import log
from flwr.common.secure_aggregation.crypto.symmetric_encryption import (
    bytes_to_public_key,
    generate_shared_key,
    public_key_to_bytes,
    verify_hmac,
)
from flwr.proto.fleet_pb2 import (  # pylint: disable=E0611
    CreateNodeRequest,
    CreateNodeResponse,
    DeleteNodeRequest,
    DeleteNodeResponse,
    PullTaskInsRequest,
    PullTaskInsResponse,
    PushTaskResRequest,
    PushTaskResResponse,
)
from flwr.server.superlink.state import StateFactory

_PUBLIC_KEY_HEADER = "public-key"
_AUTH_TOKEN_HEADER = "auth-token"

Request = Union[
    CreateNodeRequest, DeleteNodeRequest, PullTaskInsRequest, PushTaskResRequest
]

Response = Union[
    CreateNodeResponse,
    DeleteNodeResponse,
    PullTaskInsResponse,
    PushTaskResResponse,
]


def _get_value_from_tuples(
    key_string: str, tuples: Sequence[Tuple[str, Union[str, bytes]]]
) -> bytes:
    value = next((value for key, value in tuples if key == key_string), "")
    if isinstance(value, str):
        return value.encode()

    return value


class AuthenticateServerInterceptor(grpc.ServerInterceptor):  # type: ignore
    """Server interceptor for client authentication."""

    def __init__(
        self,
        state_factory: StateFactory,
        client_public_keys: Set[bytes],
        private_key: ec.EllipticCurvePrivateKey,
        public_key: ec.EllipticCurvePublicKey,
    ):
        self._lock = threading.Lock()
        self.server_private_key = private_key
        self.server_public_key = public_key
        self.state = state_factory.state()
        self.state.store_client_public_keys(client_public_keys)
        log(
            INFO,
            "Client authentication enabled with %d known public keys",
            len(client_public_keys),
        )

    def intercept_service(
        self,
        continuation: Callable[[Any], Any],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler:
        """Flower server interceptor authentication logic."""
        message_handler: grpc.RpcMethodHandler = continuation(handler_call_details)
        return self._generic_auth_unary_method_handler(message_handler)

    def _generic_auth_unary_method_handler(
        self, message_handler: grpc.RpcMethodHandler
    ) -> grpc.RpcMethodHandler:
        def _generic_method_handler(
            request: Request,
            context: grpc.ServicerContext,
        ) -> Any:
            with self._lock:
                client_public_key_bytes = base64.urlsafe_b64decode(
                    _get_value_from_tuples(
                        _PUBLIC_KEY_HEADER, context.invocation_metadata()
                    )
                )
                is_public_key_known = (
                    client_public_key_bytes in self.state.get_client_public_keys()
                )
                if is_public_key_known:
                    if isinstance(request, CreateNodeRequest):
                        context.send_initial_metadata(
                            (
                                (
                                    _PUBLIC_KEY_HEADER,
                                    base64.urlsafe_b64encode(
                                        public_key_to_bytes(self.server_public_key)
                                    ),
                                ),
                            )
                        )
                    elif isinstance(
                        request,
                        (DeleteNodeRequest, PullTaskInsRequest, PushTaskResRequest),
                    ):
                        hmac_value = base64.urlsafe_b64decode(
                            _get_value_from_tuples(
                                _AUTH_TOKEN_HEADER, context.invocation_metadata()
                            )
                        )
                        client_public_key = bytes_to_public_key(client_public_key_bytes)
                        shared_secret = generate_shared_key(
                            self.server_private_key,
                            client_public_key,
                        )
                        verify = verify_hmac(
                            shared_secret, request.SerializeToString(True), hmac_value
                        )
                        if not verify:
                            context.abort(
                                grpc.StatusCode.UNAUTHENTICATED, "Access denied!"
                            )
                    else:
                        context.abort(grpc.StatusCode.UNAUTHENTICATED, "Access denied!")
                else:
                    context.abort(grpc.StatusCode.UNAUTHENTICATED, "Access denied!")

                return message_handler.unary_unary(request, context)

        return grpc.unary_unary_rpc_method_handler(
            _generic_method_handler,
            request_deserializer=message_handler.request_deserializer,
            response_serializer=message_handler.response_serializer,
        )