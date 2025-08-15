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
"""Signing Server Addon."""

from __future__ import annotations


import uuid
import logging
import base64
import sqlite3
from pathlib import Path
import pathlib
import shutil
from typing import TYPE_CHECKING, Callable
from pydantic import field_validator

from ..main import AddonProtocol, BaseAddonConfig
from ._key import KeyPair, KeyType
from ._grep11_client import Grep11Client
from oso.framework.data.types import V1_3
from oso.framework.core.logging import get_logger

if TYPE_CHECKING:
    from typing import Any, ClassVar, Literal

NAME: Literal["SigningServer"] = "SigningServer"


def configure(
    framework_config: Any, addon_config: "SigningServerConfig"
) -> "SigningServerAddon":
    return SigningServerAddon(framework_config, addon_config)


class SigningServerConfig(BaseAddonConfig):
    """Signing Server Addon Specific Configuration.

    Attributes
    ----------
    ca_cert: str
        PEM-encoded root certificates as a byte string for gRPC channel
    client_cert: str
        PEM-encoded certificate chain as a byte string for gRPC channel
    client_key: str
        PEM-encoded certificate chain as a byte string for gRPC channel
    grep11_endpoint: str
        Endpoint used to connect to the GREP11 server
    keystore_path: str
        Path of the attached persistent data volume used to store generated
        keys between iterations
    """

    ca_cert: str
    client_cert: str
    client_key: str
    grep11_endpoint: str = "localhost"
    keystore_path: str  # SQLite DB file
    legacy_keystore_dir: str | None = None  # Old filesystem store

    @field_validator("ca_cert", "client_cert", "client_key", mode="before")
    def _decode_base64_fields(cls, v: str) -> str:
        return base64.b64decode(v).decode("utf-8")


class SigningServerAddon(AddonProtocol):
    """Signing Server.

    Parameters
    ----------
    framework_config:
        Whole application configuration.

    plugin_config:
        Configuration specific to this addon.

    Attributes
    ----------
    config
    """

    NAME: ClassVar[str] = NAME
    configure: ClassVar[Callable] = configure

    def __init__(self, framework_config: Any, addon_config: SigningServerConfig):
        self._config = addon_config
        self._logger = get_logger(name="signing_server")

        # Ensure directory exists
        db_path = Path(self._config.keystore_path)

        if db_path.is_dir():
            db_file = db_path / "keystore.db"
        else:
            # If path given is a file, use it directly
            db_file = db_path

        db_file.parent.mkdir(parents=True, exist_ok=True)

        # SQLite connection
        self._conn = sqlite3.connect(str(db_file))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS keys (
                id TEXT PRIMARY KEY,
                key_type TEXT NOT NULL,
                private_key TEXT NOT NULL,
                public_key TEXT NOT NULL
            )
        """)
        self._conn.commit()

        # Migrate and delete old filesystem keystore
        if self._config.legacy_keystore_dir:
            self._migrate_and_cleanup_legacy(self._config.legacy_keystore_dir)

        self._grep11_client = Grep11Client(self._config)
        self._grep11_client.health_check()

    def _migrate_and_cleanup_legacy(self, legacy_dir: str):
        legacy_path = pathlib.Path(legacy_dir)
        if not legacy_path.exists():
            self._logger.debug(f"No legacy keystore found at {legacy_dir}")
            return

        migrated_count = 0
        for key_type_dir in legacy_path.iterdir():
            if not key_type_dir.is_dir():
                continue

            key_type = self._get_key_type(key_type_dir.name)
            if key_type is None:
                continue

            for priv_file in key_type_dir.glob("*.key"):
                pub_file = priv_file.with_suffix(".pub")
                if not pub_file.exists():
                    continue

                key_id = priv_file.stem
                # Skip if already in DB
                cur = self._conn.execute("SELECT 1 FROM keys WHERE id = ?", (key_id,))
                if cur.fetchone():
                    continue

                priv_bytes = priv_file.read_bytes()
                pub_bytes = pub_file.read_bytes()

                self._conn.execute(
                    "INSERT INTO keys (id, key_type, private_key, public_key) VALUES (?, ?, ?, ?)",
                    (key_id, key_type.name, priv_bytes.hex(), pub_bytes.hex()),
                )
                migrated_count += 1

        self._conn.commit()

        # Log migration result
        if migrated_count > 0:
            self._logger.info(
                f"Migrated {migrated_count} key(s) from filesystem to SQLite"
            )
        else:
            self._logger.debug("No keys migrated from filesystem")

        # Delete legacy directory tree
        deleted_count = 0
        for key_file in legacy_path.glob("**/*.key"):
            try:
                key_file.unlink()
                pub_file = key_file.with_suffix(".pub")
                if pub_file.exists():
                    pub_file.unlink()
                deleted_count += 1
            except Exception as e:
                self._logger.error(f"Failed to delete legacy key '{key_file}': {e}")

        if deleted_count > 0:
            self._logger.info(
                f"Deleted {deleted_count} legacy key file(s) from '{legacy_dir}'"
            )

    def generate_key_pair(self, key_type: KeyType) -> tuple[str, bytes]:
        """Generate a new key pair.

        Parameters
        ----------
        key_type : KeyType
            The type of key to generate.

        Returns
        -------
        tuple[str, bytes]
            - key_id : str
                The unique identifier for the generated key.
            - pub_key_pem : bytes
                The public key in PEM format.
        """
        logging.info(f"Generating new key pair of type {key_type.name}")
        key_pair = self._grep11_client.generate_key_pair(key_type=key_type)
        key_id = self._save_key_pair(key_type, key_pair)
        pub_key_pem = self._grep11_client.serialized_key_to_pem(
            key_type=key_type, pub_key_bytes=key_pair.PublicKey
        )
        self._logger.info("Finished generating a new key pair")
        self._logger.debug(f"New key id: '{key_id}'")
        return key_id, pub_key_pem

    def list_keys(self, key_type: KeyType) -> list[str]:
        """Find the existing keys of the specified type in the keystore.

        Parameters
        ----------
        key_type : KeyType
            The type of keys to find.

        Returns
        -------
        list[str]
            List of key ids of the given key type.
        """
        cur = self._conn.execute(
            "SELECT id FROM keys WHERE key_type = ?", (key_type.name,)
        )
        return [row[0] for row in cur.fetchall()]

    def get_key_pem(self, key_id: str) -> bytes | None:
        """Get the public key PEM for a given key ID.

        Parameters
        ----------
        key_id : str
            The unique identifier of the key for which the public PEM is requested.

        Returns
        -------
        bytes | None
            The PEM-encoded public key as bytes if the key is found and conversion
            succeeds, otherwise None.
        """
        keys = self._find_keys(key_id)
        if not keys:
            self._logger.info(f"Could not find key pair for key id: '{key_id}'")
            return None
        key_type, key_pair = keys
        return self._grep11_client.serialized_key_to_pem(
            key_type=key_type, pub_key_bytes=key_pair.PublicKey
        )

    def _find_keys(self, key_id: str) -> tuple[KeyType, KeyPair] | None:
        """Find private and public keys for the given key ID.

        Parameters
        ----------
        key_id : str
            The ID of the key to find.

        Returns
        -------
        tuple[KeyType, KeyPair] | None
            - KeyType: The resolved type of the key.
            - KeyPair: A container holding the deserialized private
                and public keys.

            Returns None if the key is not found or if the type cannot be resolved.

        Raises
        ------
        FileNotFoundError
            If either the private or public key file exists but is not a valid file.
        """
        row = self._conn.execute(
            "SELECT key_type, private_key, public_key FROM keys WHERE id = ?", (key_id,)
        ).fetchone()

        if not row:
            return None

        key_type_name, priv_hex, pub_hex = row
        key_type = self._get_key_type(key_type_name)
        if key_type is None:
            return None

        key_pair = KeyPair(
            PrivateKey=bytes.fromhex(priv_hex), PublicKey=bytes.fromhex(pub_hex)
        )
        return key_type, key_pair

    def _get_key_type(self, key_type_name: str) -> KeyType | None:
        for kt in KeyType:
            if kt.name == key_type_name:
                return kt
        return None

    def _save_key_pair(self, key_type: KeyType, key_pair: KeyPair) -> str:
        key_id = str(uuid.uuid4())
        self._logger.info(
            f"Saving {key_type.name} key with key ID: '{key_id}' to SQLite"
        )
        self._conn.execute(
            "INSERT INTO keys (id, key_type, private_key, public_key) VALUES (?, ?, ?, ?)",
            (
                key_id,
                key_type.name,
                key_pair.PrivateKey.hex(),
                key_pair.PublicKey.hex(),
            ),
        )
        self._conn.commit()
        return key_id

    def sign(self, key_id: str, data: bytes) -> str:
        """Sign data using GREP11 server.

        Parameters
        ----------
        key_id : str
            Key ID used to find stored key, prefixed with key type OID
        data : bytes
            Data to be signed.

        Returns
        -------
        str
            Signature as a string.
        """
        keys = self._find_keys(key_id)
        if not keys:
            raise Exception(f"Could not find key pair for key id: '{key_id}'")
        key_type, key_pair = keys
        return self._grep11_client.sign(
            key_type=key_type, priv_key_bytes=key_pair.PrivateKey, data=data
        )

    def count_keys(self, key_type: KeyType | None = None) -> int:
        """
        Return the number of keys stored in the database.

        Parameters
        ----------
        key_type : KeyType | None
            If provided, count only keys of this type. Otherwise, count all keys.

        Returns
        -------
        int
            Number of keys.
        """
        if key_type is not None:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM keys WHERE key_type = ?", (key_type.name,)
            )
        else:
            cur = self._conn.execute("SELECT COUNT(*) FROM keys")
        row = cur.fetchone()
        return row[0] if row else 0

    def health_check(self) -> V1_3.ComponentStatus:
        """Check the GREP11 server health status.

        Returns
        -------
        `oso.framework.data.types.ComponentStatus`
            OSO component status.
        """
        return self._grep11_client.health_check()

    def verify(self, key_id: str, data: bytes, signature: str) -> bool:
        """
        Verify a signature using the public key stored in the keystore.

        Parameters
        ----------
        key_id : str
            The ID of the key used to generate the signature.
        data : bytes
            The original data that was signed.
        signature : str
            The signature to verify.

        Returns
        -------
        bool
            True if the signature is valid, False otherwise.
        """
        keys = self._find_keys(key_id)
        if not keys:
            self._logger.info(f"Could not find key pair for key id: '{key_id}'")
            return False

        key_type, key_pair = keys

        try:
            return self._grep11_client.verify(
                key_type=key_type,
                pub_key_bytes=key_pair.PublicKey,
                data=data,
                signature=signature,
            )
        except Exception as e:
            self._logger.error(f"Signature verification failed for key '{key_id}': {e}")
            return False
