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
"""Certificate Configuration."""


import base64

from pathlib import Path

from pydantic import field_validator

from .. import AutoLoadConfig


class CertificateConfig(AutoLoadConfig, _config_prefix="certs"):
    """Certificate Configuration Set.

    An application that requires loading of certificates can import this model to
    notify the `..ConfigManager` that these fields are required. Picked from the
    environment variables prefixed with ``CERTS__``.

    Attributes
    ----------
    ca : str, envvar=CERTS__CA
        The Certificate Authority for all of the components.

    app_crt : str, envvar=CERTS__APP_CRT
        The certificate for this application.

    app_key : str, envvar=CERTS__APP_KEY
        The private key for this application.

    client_ca_extra : str, optional, envvar=CERTS__CLIENT_CA_EXTRA
        Additional Certificate Authority appended to the exported client CA
        bundle, so the TLS terminator can also verify clients that are not
        OSO components (e.g. approver certificates calling ISV-supplied
        endpoints). Accepts PEM or base64-encoded PEM.
    """

    ca: str
    app_crt: str
    app_key: str
    """
    The private key for this application.

    :Required: ``True``
    :envvar: CERTS__APP_KEY
    """

    client_ca_extra: str = ""

    _loc: Path | None = None

    @field_validator("client_ca_extra", mode="before")
    def _decode_client_ca_extra(cls, v: str) -> str:
        if v and not v.lstrip().startswith("-----BEGIN"):
            return base64.b64decode(v).decode("utf-8")
        return v

    def export(self, root: Path):
        """Export certificates to filesystem."""
        self._loc = root / "certificates"
        self._loc.mkdir(mode=0o700, exist_ok=True)

        ca_bundle = (
            self.ca
            if not self.client_ca_extra
            else self.ca.rstrip() + "\n" + self.client_ca_extra
        )
        self.ca_filename.write_text(ca_bundle)
        self.crt_filename.write_text(self.app_crt)
        self.key_filename.write_text(self.app_key)

    @property
    def ca_filename(self) -> Path:
        """CA filename."""
        return self._loc / "oso-ca.crt"

    @property
    def crt_filename(self) -> Path:
        """Cert filename."""
        return self._loc / "server.crt"

    @property
    def key_filename(self) -> Path:
        """Key filename."""
        return self._loc / "server.key"
