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

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, IntEnum, StrEnum
from typing import ClassVar

from .ep11constants import CKM_ECDSA, CKM_IBM_ED25519_SHA512

class SupportedMechanism(IntEnum):
    ECDSA = CKM_ECDSA
    ED25519_SHA512 = CKM_IBM_ED25519_SHA512

class SupportedOID(StrEnum):
    SECP256K1 = "06052b8104000a"
    ED25519 = "06032b6570"


class Key(ABC):
    Oid: ClassVar[SupportedOID]
    Mechanism: ClassVar[SupportedMechanism]

    @abstractmethod
    def LoadPubKeyFn(self, encoded_point: bytes):
        pass


class SECP256K1_Key(Key):
    Oid = SupportedOID.SECP256K1
    Mechanism = SupportedMechanism.ECDSA

    def LoadPubKeyFn(self, ec_point: bytes):
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), ec_point)


class ED25519_Key(Key):
    Oid = SupportedOID.ED25519
    Mechanism = SupportedMechanism.ED25519_SHA512

    def LoadPubKeyFn(self, ec_point: bytes):
        return ed25519.Ed25519PublicKey.from_public_bytes(ec_point)


class KeyType(Enum):
    SECP256K1 = SECP256K1_Key()
    ED25519 = ED25519_Key()


@dataclass
class KeyPair:
    PrivateKey: bytes
    PublicKey: bytes

    def to_hex(self) -> dict[str, str]:
        """Convert keys to hex strings and return as a dictionary."""
        return {
            "PrivateKey": self.PrivateKey.hex(),
            "PublicKey": self.PublicKey.hex(),
        }

    @classmethod
    def from_hex(cls, private_key_hex: str, public_key_hex: str) -> "KeyPair":
        """Create a KeyPair instance from hex strings."""
        return cls(
            PrivateKey=bytes.fromhex(private_key_hex),
            PublicKey=bytes.fromhex(public_key_hex),
        )
