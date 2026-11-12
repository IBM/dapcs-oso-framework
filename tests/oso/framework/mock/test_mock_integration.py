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


import datetime
import logging
import os
import sys
import threading
import time

import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from urllib3 import disable_warnings, exceptions

from oso.framework.entrypoint.mock import MockOSO
from tests.oso.framework.mock.mock_endpoints import make_app

disable_warnings(exceptions.InsecureRequestWarning)

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../src")),
)


@pytest.fixture(scope="session")
def tls_certs(tmp_path_factory):
    """
    Generate a temp root CA key + self-signed cert, and server key + cert for
    the local backend server
    """
    td = tmp_path_factory.mktemp("certs")

    # generate CA key + self-signed cert
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_cert_pem = td / "ca.pem"
    ca_key_pem = td / "ca.key"
    ca_cert_pem.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    ca_key_pem.write_bytes(
        ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )

    # generate server key + CSR + sign it with CA
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(server_name)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        )
        .sign(server_key, hashes.SHA256())
    )
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(ca_name)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_cert_pem = td / "server.pem"
    server_key_pem = td / "server.key"
    server_cert_pem.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    server_key_pem.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )

    return str(ca_cert_pem), str(server_cert_pem), str(server_key_pem)


def test_mockoso_integration(tls_certs):
    ca_pem, server_cert, server_key = tls_certs

    sample = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "data",
            "v1.3",
            "valid-DocumentList-0.json",
        )
    )

    fe_port, be_port = 8081, 8082

    # build our two Flask apps
    fe_app = make_app("frontend", sample)
    be_app = make_app("backend", sample)

    def run(app, port):
        app.run(
            host="localhost",
            port=port,
            ssl_context=(server_cert, server_key),
            debug=False,
            use_reloader=False,
        )

    threading.Thread(
        target=lambda: run(fe_app, fe_port),
        daemon=True,
    ).start()
    threading.Thread(
        target=lambda: run(be_app, be_port),
        daemon=True,
    ).start()

    time.sleep(0.5)

    # configure MockOSO to point at our local servers
    class IntConfig:
        class Certs:
            def export(self, path):
                pass

            crt_filename = ""
            key_filename = ""
            ca_filename = ""

        certs = Certs()

        class Mock:
            frontend_endpoint = f"https://localhost:{fe_port}/api/frontend/v1alpha1"
            backend_endpoint = f"https://localhost:{be_port}/api/backend/v1alpha1"
            max_retries = 1

        mock = Mock()

        class Logging:
            level_as_int = logging.DEBUG

        logging = Logging()

    cfg = IntConfig()
    m = MockOSO(cfg)

    # disable server‐cert verification and clear out any client cert
    m.verify = ca_pem
    m.cert = None
    m.requests = requests

    m.phase1()
    m.phase2()

    assert True
