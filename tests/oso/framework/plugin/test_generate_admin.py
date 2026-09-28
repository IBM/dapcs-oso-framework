#
# (c) Copyright IBM Corp. 2025, 2026
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
"""Tests for admin access to POST /generate."""

import datetime

from types import SimpleNamespace

import pytest

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from flask import Flask, g

from oso.framework.auth.common import EXT_NAME
from oso.framework.auth.mtls import parse_user_fingerprint
from oso.framework.config.models.certs import CertificateConfig
from oso.framework.plugin.api.v1alpha1 import generate


def _cert(name: str, issuer: tuple | None = None) -> tuple:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    issuer_name, issuer_key = (
        (issuer[0].subject, issuer[1]) if issuer else (subject, key)
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(issuer_key, hashes.SHA256())
    )
    return cert, key


@pytest.fixture
def check(monkeypatch):
    admin_ca = _cert("admin-ca")
    admin = _cert("admin", admin_ca)[0]
    plugin_ext = SimpleNamespace(
        admin_ca=admin_ca[0], admin_fingerprints=[parse_user_fingerprint(admin)]
    )
    monkeypatch.setattr(generate, "current_oso_plugin", lambda: plugin_ext)

    def _check(cert) -> bool:
        with Flask(__name__).test_request_context():
            mtls = {"cert": cert, "fingerprint": parse_user_fingerprint(cert)}
            setattr(g, EXT_NAME, {"mtls": mtls})
            return generate._is_admin()

    return _check, admin, admin_ca, plugin_ext


def test_is_admin(check):
    _check, admin, admin_ca, plugin_ext = check
    assert _check(admin)
    # Same CA name, different key: not issued by the admin CA
    forged_ca = _cert("admin-ca")
    forged = _cert("admin", forged_ca)[0]
    plugin_ext.admin_fingerprints.append(parse_user_fingerprint(forged))
    assert not _check(forged)
    # Issued by the admin CA but not allowlisted
    assert not _check(_cert("other", admin_ca)[0])
    with Flask(__name__).test_request_context():  # no mTLS result
        assert not generate._is_admin()
    plugin_ext.admin_ca = None
    assert not _check(admin)


def test_client_ca_bundle(tmp_path):
    certs = CertificateConfig(ca="OSO\n", app_crt="c", app_key="k")
    certs.export(tmp_path)
    assert certs.client_ca_filename.read_text() == "OSO\n"
    certs = CertificateConfig(ca="OSO\n", app_crt="c", app_key="k", admin_ca="ADMIN")
    certs.export(tmp_path)
    assert certs.client_ca_filename.read_text() == "OSO\nADMIN\n"
