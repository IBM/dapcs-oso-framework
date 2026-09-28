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

from pathlib import Path

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

    admin_ca : str | None, envvar=CERTS__ADMIN_CA
        Extra CA the proxy trusts for client certificates, so admin clients
        can reach endpoints that allow them (see ``PluginConfig.admin_ca``).
    """

    ca: str
    app_crt: str
    app_key: str
    """
    The private key for this application.

    :Required: ``True``
    :envvar: CERTS__APP_KEY
    """

    admin_ca: str | None = None

    _loc: Path | None = None

    def export(self, root: Path):
        """Export certificates to filesystem."""
        self._loc = root / "certificates"
        self._loc.mkdir(mode=0o700, exist_ok=True)

        self.ca_filename.write_text(self.ca)
        self.crt_filename.write_text(self.app_crt)
        self.key_filename.write_text(self.app_key)
        self.client_ca_filename.write_text(
            "\n".join(ca.strip() for ca in (self.ca, self.admin_ca) if ca) + "\n"
        )

    @property
    def ca_filename(self) -> Path:
        """CA filename."""
        return self._loc / "oso-ca.crt"

    @property
    def client_ca_filename(self) -> Path:
        """CA bundle trusted for client certificates (CA plus admin CA)."""
        return self._loc / "client-ca.crt"

    @property
    def crt_filename(self) -> Path:
        """Cert filename."""
        return self._loc / "server.crt"

    @property
    def key_filename(self) -> Path:
        """Key filename."""
        return self._loc / "server.key"
