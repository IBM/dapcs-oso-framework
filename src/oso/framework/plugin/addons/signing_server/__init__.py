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
import pathlib
import base64

from typing import TYPE_CHECKING
from typing import Callable
from pydantic import field_validator

from ..main import AddonProtocol, BaseAddonConfig

from ._key import KeyPair, KeyType
from ._grep11_client import Grep11Client

from oso.framework.data.types import V1_3
from oso.framework.core.logging import get_logger

if TYPE_CHECKING:
    from typing import Any, Callable, ClassVar, Literal

NAME: Literal["SigningServer"] = "SigningServer"


def configure(
    framework_config: Any, addon_config: SigningServerConfig
) -> SigningServerAddon:
    """Return the addon instance."""
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
    keystore_path: str

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

        self._keystore = pathlib.Path(self._config.keystore_path)

        self._grep11_client = Grep11Client(self._config)
        self._grep11_client.health_check()

    def generate_key_pair(self, key_type: KeyType) -> tuple[str, str]:
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
            - pub_key_pem : str
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
        key_id_list = []

        key_type_dir = self._keystore / key_type.name

        if key_type_dir.exists():
            if not key_type_dir.is_dir():
                raise Exception(
                    f"{key_type_dir} is an existing file, it should be a directory"
                )

            for key_file in key_type_dir.glob("*.key"):
                key_id = key_file.stem

                if key_file.with_suffix(".pub").exists():
                    key_id_list.append(key_id)

                else:
                    self._logger.info(
                        f"Corresponding public key does not exist for {key_file}"
                    )

        else:
            self._logger.debug(f"'{key_type.name}' dir does not exist in the key store")

        return key_id_list

    def get_key_pem(self, key_id: str) -> str | None:
        """Get the public key PEM for a given key ID.

        Parameters
        ----------
        key_id : str
            The unique identifier of the key for which the public PEM is requested.

        Returns
        -------
        str | None
            The PEM-encoded public key str if the key is found and conversion
            succeeds, otherwise None.
        """
        keys = self._find_keys(key_id=key_id)

        if not keys:
            self._logger.info(f"Could not find key pair for key id: '{key_id}'")
            return None

        key_type, key_pair = keys

        pub_key_pem = self._grep11_client.serialized_key_to_pem(
            key_type=key_type, pub_key_bytes=key_pair.PublicKey
        )

        return pub_key_pem

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
        for priv_key_file in self._keystore.glob("*/*.key"):
            file_id = priv_key_file.stem

            if key_id == file_id:
                pub_key_file = priv_key_file.with_suffix(".pub")

                if not priv_key_file.is_file():
                    raise FileNotFoundError(
                        f"Private key path '{priv_key_file}' is not a valid file"
                    )

                if not pub_key_file.is_file():
                    raise FileNotFoundError(
                        f"Corresponding public key for '{priv_key_file}' does not exist"
                    )

                key_type_name = priv_key_file.parent.name

                key_type = self._get_key_type(key_type_name=key_type_name)

                if key_type is None:
                    self._logger.info("Key ID does not match with known key type")
                    self._logger.debug(f"Key ID: {key_id}")
                    return None

                key_pair = KeyPair(
                    PrivateKey=priv_key_file.read_bytes(),
                    PublicKey=pub_key_file.read_bytes(),
                )

                return key_type, key_pair

        return None

    def _get_key_type(self, key_type_name: str) -> KeyType | None:
        key_type = None

        for kt in KeyType:
            if kt.name == key_type_name:
                key_type = kt

        return key_type

    def _save_key_pair(self, key_type: KeyType, key_pair: KeyPair) -> str:
        key_type_dir = self._keystore / key_type.name

        if key_type_dir.exists():
            if not key_type_dir.is_dir():
                raise NotADirectoryError(
                    f"{key_type_dir} exists but is not a directory."
                )
        else:
            key_type_dir.mkdir(parents=True, exist_ok=True)

        key_id = str(uuid.uuid4())

        self._logger.info(f"Writing {key_type.name} key with key ID: '{key_id}'")

        priv_key_filename = key_type_dir / f"{key_id}.key"
        priv_key_filename.write_bytes(key_pair.PrivateKey)

        pub_key_filename = key_type_dir / f"{key_id}.pub"
        pub_key_filename.write_bytes(key_pair.PublicKey)

        self._logger.debug(
            f"Wrote priv key to {priv_key_filename} and pub key to {pub_key_filename}"
        )

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
        keys = self._find_keys(key_id=key_id)

        if not keys:
            self._logger.info(f"Could not find key pair for key id: '{key_id}'")
            raise Exception(f"Could not find key pair for key id: '{key_id}'")

        key_type, key_pair = keys

        return self._grep11_client.sign(
            key_type=key_type, priv_key_bytes=key_pair.PrivateKey, data=data
        )

    def health_check(self) -> V1_3.ComponentStatus:
        """Check the GREP11 server health status.

        Returns
        -------
        `oso.framework.data.types.ComponentStatus`
            OSO component status.
        """
        return self._grep11_client.health_check()
