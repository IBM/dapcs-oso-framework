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

import base64
import textwrap

from .pyep11 import Mechanism,Attribute, HsmInit, GetMechanismList, GenerateKeyPair, SignSingle, VerifySingle
from .ep11constants import *
from asn1crypto import core as asn1_core
from pyasn1.codec.der.decoder import decode
from pyasn1.codec.der.encoder import encode
from pyasn1.type.univ import Any
from pyasn1.type import univ,namedtype


from ._key import KeyPair, KeyType, SupportedMechanism

from oso.framework.data.types import V1_3
from oso.framework.core.logging import get_logger

class AlgorithmIdentifier(univ.Sequence):
    componentType = namedtype.NamedTypes(
        namedtype.NamedType("algorithm", univ.ObjectIdentifier()),
        # RFC 8410: Ed25519 AlgorithmIdentifier has **no parameters**
    )

class SubjectPublicKeyInfo(univ.Sequence):
    componentType = namedtype.NamedTypes(
        namedtype.NamedType("algorithm", univ.Any()),  # RawValue equivalent
        namedtype.NamedType("subjectPublicKey", univ.BitString()),
    )


class EP11Client:
    def __init__(self, signing_server_config) -> None:
        super().__init__()

        self.logger = get_logger("ep11-client")

        self.logger.info("Initializing ep11 client")

        self.target=HsmInit(signing_server_config.hsms)


    def generate_key_pair(self, key_type: KeyType) -> KeyPair:
        self.logger.info("Generating new key pair")
        self.logger.debug(f"Generating key pair of type: {key_type.name}")

        ecParameters = bytes.fromhex(key_type.value.Oid)
    
        key_gen_mechanism = Mechanism(CKM_EC_KEY_PAIR_GEN,None)
        pub_key_template = [
             Attribute(CKA_EC_PARAMS, ecParameters),
             Attribute(CKA_VERIFY, True),
        ]
        priv_key_template = [
            Attribute(CKA_SIGN, True),
            Attribute(CKA_EXTRACTABLE, False),
        ]
        PubKeyBytes, PrivKeyBytes ,error= GenerateKeyPair(self.target, key_gen_mechanism, pub_key_template, priv_key_template)
        # Check if there was an error
        if error:
            print(f"Error: {error}")
        else:
       # Print the hexadecimal string representation of the key
            print(f"Generated Private key: {PrivKeyBytes.hex()}")
            print(f"Generated Public key: {PubKeyBytes.hex()}")

        spki, rest = decode(PubKeyBytes, asn1Spec=Any())

        key_pair = KeyPair(
            PrivateKey=PrivKeyBytes,
            PublicKey=encode(spki)
        )
        #S=self.sign( key_type, key_pair.PrivateKey,  b"helloworld")
        #print(self.verify(key_type, key_pair.PublicKey,b"helloworld",S))
        #print(self.serialized_key_to_pem(key_type,key_pair.PublicKey))
        return key_pair

    def health_check(self) -> V1_3.ComponentStatus:
        self.logger.info("Running health check")

        try:
            Mechs, error = GetMechanismList(self.target)

            errors = []

            for mechanism in SupportedMechanism:
                if mechanism.name not in Mechs:
                    errors.append(
                        V1_3.Error(
                            code="1",
                            message=f"EP11 HSM does not support {mechanism.name}",
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
        self.logger.debug(
            f"Signing data: '{data.hex()}' with key type: '{key_type.name}'"
        )

        mech = Mechanism(key_type.value.Mechanism,None)
        signature , error = SignSingle(self.target, mech, priv_key_bytes, data)
        if error:
            print(f"Error: {error}")
            return None
        else:
            print(f"Signature: {signature.hex()}")
            self.logger.info("Completed Signing")
    
            self.logger.debug(f"Created signature: {signature=}")
  
            return signature.hex()
    
    def verify(self, key_type: KeyType, pub_key_bytes: bytes, data: bytes, signature: str) -> bool:
        """
        Verify a signature using the GREP11 server.
    
        Parameters
        ----------
        key_type : KeyType
            The type of key (should match the key used for signing).
        pub_key_bytes : bytes
            The public key in raw bytes.
        data : bytes
            The original data that was signed.
        signature : str
            Hex-encoded signature to verify.
    
        Returns
        -------
        bool
            True if the signature is valid, False otherwise.
        """
        self.logger.info("Performing signature verification")
        self.logger.debug(
            f"Verifying signature: '{signature}' for data: '{data.hex()}' with key type: '{key_type.name}'"
        )
        mech = Mechanism(key_type.value.Mechanism,None)
        error = VerifySingle(self.target, mech ,pub_key_bytes,data, bytes.fromhex(signature))
        if error:
            self.logger.error(f"Signature verification failed: {error}")
            return False
        else:
            self.logger.info("Completed verification")
            return True

    def serialized_key_to_pem(self, key_type: KeyType, pub_key_bytes: bytes) -> str:
#        self.logger.info("Converting Public Key Blob to PEM")
#        self.logger.debug(f"KeyType: '{key_type.name}'")
        if key_type == KeyType.ED25519:
            try:
                spki, rest = decode(pub_key_bytes, asn1Spec=SubjectPublicKeyInfo())
                bitstr = spki["subjectPublicKey"]

                # pyasn1 bitstring .asOctets() returns raw bytes
        
                if len(bitstr.asOctets()) == 32:
                    raw_key = bitstr.asOctets()
                else:
                    raise ValueError("Not a valid SPKI Ed25519 key")

            except Exception:
                # Otherwise must be raw 32-byte key
                if len(PubKeyBytes) != 32:
                    raise ValueError("Input is not SPKI and not a 32-byte Ed25519 raw key")
                raw_key = input_bytes

            # RFC 8410 Ed25519 OID
            ed25519_oid = univ.ObjectIdentifier("1.3.101.112")

            # Build AlgorithmIdentifier (OID only, no params)
            alg = AlgorithmIdentifier()
            alg["algorithm"] = ed25519_oid
            alg_der = encode(alg)

            # Create final SPKI
            spki = SubjectPublicKeyInfo()
            spki["algorithm"] = univ.Any(alg_der)
            spki["subjectPublicKey"] = univ.BitString.fromOctetString(raw_key)
            pub_key_bytes=encode(spki)
        
        b64_encoded = base64.b64encode(pub_key_bytes).decode("ascii")
        wrapped = "\n".join(textwrap.wrap(b64_encoded, 64))

        pem_encoded_pub_key = (
            f"-----BEGIN PUBLIC KEY-----\n{wrapped}\n-----END PUBLIC KEY-----\n"
        )

#        self.logger.debug(
#            f"key type: '{key_type.name}', PUBLIC KEY: {pem_encoded_pub_key}"
#        )

        return pem_encoded_pub_key
