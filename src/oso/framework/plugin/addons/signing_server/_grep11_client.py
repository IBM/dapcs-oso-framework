#
# (c) Copyright IBM Corp. 2025
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
from typing import cast
import grpc

from pkcs11 import Mechanism, Attribute
from asn1crypto import core as asn1_core
from cryptography.hazmat.primitives import serialization

from ._key import KeyPair, KeyType, SupportedMechanism
from .generated import server_pb2, server_pb2_grpc

from oso.framework.data.types import V1_3
from oso.framework.core.logging import get_logger


class Grep11Client:
    def __init__(self, signing_server_config) -> None:
        super().__init__()

        self.logger = get_logger("grep11-client")

        self.logger.info("Initializing grep11 client")

        self._set_channel_and_stub(
            ca_cert=signing_server_config.ca_cert.encode(),
            client_key=signing_server_config.client_key.encode(),
            client_cert=signing_server_config.client_cert.encode(),
            endpoint=signing_server_config.grep11_endpoint,
        )

    def _set_channel_and_stub(
        self, ca_cert: bytes, client_key: bytes, client_cert: bytes, endpoint: str
    ) -> None:
        self.logger.info("Setting channel and stub")

        channel_credential = grpc.ssl_channel_credentials(
            root_certificates=ca_cert,
            private_key=client_key,
            certificate_chain=client_cert,
        )

        channel = grpc.secure_channel(target=endpoint, credentials=channel_credential)

        self.stub = server_pb2_grpc.CryptoStub(channel)

    def generate_key_pair(self, key_type: KeyType) -> KeyPair:
        self.logger.info("Generating new key pair")
        self.logger.debug(f"Generating key pair of type: {key_type.name}")

        key_gen_mechanism = server_pb2.Mechanism(Mechanism=Mechanism.EC_KEY_PAIR_GEN)

        pub_key_template = {
            Attribute.EC_PARAMS: server_pb2.AttributeValue(
                AttributeB=bytes.fromhex(key_type.value.Oid)
            ),
            Attribute.VERIFY: server_pb2.AttributeValue(AttributeTF=True),
            Attribute.TOKEN: server_pb2.AttributeValue(AttributeTF=True),
        }

        priv_key_template = {
            Attribute.SIGN: server_pb2.AttributeValue(AttributeTF=True),
            Attribute.EXTRACTABLE: server_pb2.AttributeValue(AttributeTF=False),
            Attribute.TOKEN: server_pb2.AttributeValue(AttributeTF=True),
        }

        request = server_pb2.GenerateKeyPairRequest(
            Mech=key_gen_mechanism,
            PrivKeyTemplate=priv_key_template,
            PubKeyTemplate=pub_key_template,
        )

        self.logger.debug(f"GenerateKeyPairRequest: {request}")

        response = self.stub.GenerateKeyPair(request)
        assert isinstance(response, server_pb2.GenerateKeyPairResponse)

        self.logger.info("Received GenerateKeyPair response")

        key_pair = KeyPair(
            PrivateKey=response.PrivKey.SerializeToString(),
            PublicKey=response.PubKey.SerializeToString(),
        )

        self.logger.debug(f"Key Pair Generated: {key_pair.to_base64()=}")

        return key_pair

    def health_check(self) -> V1_3.ComponentStatus:
        self.logger.info("Running health check")

        try:
            request = server_pb2.GetMechanismListRequest()
            response = self.stub.GetMechanismList(request)
            assert isinstance(response, server_pb2.GetMechanismListResponse)

            errors = []

            for mechanism in SupportedMechanism:
                if mechanism not in response.Mechs:
                    errors.append(
                        V1_3.Error(
                            code="1",
                            message=f"GREP11 server does not support {mechanism.name}",
                        )
                    )

            if not errors:
                return V1_3.ComponentStatus(status_code=200, status="OK", errors=[])

            else:
                return V1_3.ComponentStatus(
                    status_code=500, status="Internal Server Error", errors=errors
                )

        except Exception as e:
            self.logger.debug(f"Health check error: {e}")
            raise e

    def sign(self, key_type: KeyType, priv_key_bytes: bytes, data: bytes) -> str:
        self.logger.info("Performing a signing")
        self.logger.debug(f"Signing data: '{data}' with key type: '{key_type.name}'")

        sign_request = server_pb2.SignSingleRequest(
            Mech=server_pb2.Mechanism(Mechanism=key_type.value.Mechanism),
            Data=data,
            PrivKey=server_pb2.KeyBlob.FromString(priv_key_bytes),
        )

        sign_response = self.stub.SignSingle(sign_request)
        assert isinstance(sign_response, server_pb2.SignSingleResponse)

        self.logger.info("Completed Signing")
        self.logger.debug(f"Received SignSingleResponse: {sign_response=}")

        signature = sign_response.Signature.hex()

        self.logger.debug(f"Created signature: {signature=}")

        return signature

    def serialized_key_to_pem(self, key_type: KeyType, pub_key_bytes: bytes) -> bytes:
        self.logger.info("Converting Public Key Blob to PEM")
        self.logger.debug(f"KeyType: '{key_type.name}'")

        pub_key_blob = server_pb2.KeyBlob.FromString(pub_key_bytes)

        ec_point_attr = pub_key_blob.Attributes[Attribute.EC_POINT]

        ec_point_octet_string = asn1_core.OctetString.load(ec_point_attr.AttributeB)
        assert isinstance(ec_point_octet_string, asn1_core.OctetString)

        ec_point_bytes = ec_point_octet_string.native

        public_key = key_type.value.LoadPubKeyFn(cast(bytes, ec_point_bytes))

        pem_encoded_pub_key = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        self.logger.debug(
            f"key type: '{key_type.name}', PUBLIC KEY: {pem_encoded_pub_key.decode()}"
        )

        return pem_encoded_pub_key
