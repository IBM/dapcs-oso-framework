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
import json
import os
import subprocess
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509 import NameOID
from flask import Flask, g
from werkzeug.exceptions import Forbidden, Unauthorized


class TestMtlsMisconfigured:
    @pytest.fixture()
    def _env(monkeypatch):
        pass


class TestMtlsConfigured:
    @pytest.fixture(scope="class", autouse=True)
    def _tmpdir(self, tmp_path_factory):
        return tmp_path_factory.mktemp(self.__class__.__name__.split(".")[-1])

    @pytest.fixture(scope="class", autouse=True)
    def _gen(self, _tmpdir):
        for t in ("py_allowed", "py_not"):
            one_day = datetime.timedelta(1, 0, 0)
            private_key = Ed25519PrivateKey.generate()
            with open(_tmpdir / f"id_{t}", "wb") as f:
                f.write(
                    private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.OpenSSH,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )
            public_key = private_key.public_key()
            public_key_path = _tmpdir / f"id_{t}.pub"
            with open(public_key_path, "wb") as f:
                f.write(
                    public_key.public_bytes(
                        encoding=serialization.Encoding.OpenSSH,
                        format=serialization.PublicFormat.OpenSSH,
                    )
                )
            cert = (
                x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, t)]))
                .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, t)]))
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.today() - one_day)
                .not_valid_after(datetime.datetime.today() + one_day)
                .public_key(public_key)
                .sign(private_key=private_key, algorithm=None)
            )
            with open(_tmpdir / f"{t}.crt", "wb") as f:
                f.write(
                    cert.public_bytes(
                        encoding=serialization.Encoding.PEM,
                    )
                )
            sshkeygen_fingerprint = (
                subprocess.run(
                    ["ssh-keygen", "-l", "-f", str(public_key_path)],
                    capture_output=True,
                )
                .stdout.split(b" ")[1]
                .decode()
            )
            with open(_tmpdir / f"{t}.fingerprint", "w") as f:
                f.write(sshkeygen_fingerprint)

    @pytest.fixture(scope="class", autouse=True)
    def allowed_cert(self, _tmpdir, _gen):
        cert = ""
        with open(_tmpdir / "py_allowed.crt", "r") as f:
            for line in f:
                cert += line
        return quote(cert)

    @pytest.fixture(scope="class", autouse=True)
    def not_allowed_cert(self, _tmpdir, _gen):
        cert = ""
        with open(_tmpdir / "py_not.crt", "r") as f:
            for line in f:
                cert += line
        return quote(cert)

    @pytest.fixture(scope="class", autouse=True)
    def allowed_fp(self, _tmpdir, _gen):
        with open(_tmpdir / "py_allowed.fingerprint", "r") as f:
            return f.readline()

    @pytest.fixture(scope="class")
    def _env(self, allowed_fp):
        os.environ.update(
            {
                "AUTH__PARSERS__0__TYPE": "oso.framework.auth.mtls",
                "AUTH__PARSERS__0__ALLOWLIST": json.dumps({"test": [allowed_fp]}),
            }
        )
        yield
        del os.environ["AUTH__PARSERS__0__TYPE"]
        del os.environ["AUTH__PARSERS__0__ALLOWLIST"]

    @pytest.fixture(scope="function")
    def AuthExtension(self, _env, ConfigManager):
        from oso.framework.auth.extension import AuthExtension

        return AuthExtension(ConfigManager.reload().auth)

    @pytest.fixture(scope="function")
    def RequireAuth(self, _env, AuthExtension):
        from oso.framework.auth.extension import RequireAuth

        return RequireAuth

    @pytest.fixture(scope="function")
    def app(self, monkeypatch, AuthExtension, RequireAuth):
        app = Flask(__name__)
        app.config.update(
            {
                "TESTING": True,
            }
        )

        AuthExtension.init_app(app)

        @RequireAuth("mtls", "test")
        def fn(*args, **kwargs):
            return 200

        app.add_url_rule("/", view_func=fn)  # type: ignore
        app.register_error_handler(401, Unauthorized)
        app.register_error_handler(403, Forbidden)

        yield app

    @pytest.fixture(scope="function", autouse=True)
    def client(self, app):
        return app.test_client()

    def test_app_ext(self, app, AuthExtension):
        assert AuthExtension.NAME in app.extensions
        assert app.extensions[AuthExtension.NAME]["self"] is AuthExtension
        assert "mtls" in AuthExtension.parsers

    def test_same_type_parsers_merge_allowlists(
        self, monkeypatch, _env, allowed_fp, ConfigManager
    ):
        from oso.framework.auth.extension import AuthExtension

        monkeypatch.setenv("AUTH__PARSERS__1__TYPE", "oso.framework.auth.mtls")
        monkeypatch.setenv(
            "AUTH__PARSERS__1__ALLOWLIST",
            json.dumps({"test": [allowed_fp], "admin": [allowed_fp]}),
        )
        allowlist = AuthExtension(ConfigManager.reload().auth).allowlist["mtls"]
        assert len(allowlist["test"]) == 2
        assert len(allowlist["admin"]) == 1

    def test_parse_no_headers(self, AuthExtension):
        request = SimpleNamespace(
            headers=dict(),
        )
        auth = AuthExtension.parsers["mtls"].parse(request)
        assert auth["authorized"] is False

        from oso.framework.auth import mtls

        assert auth["authorized_header"] is mtls.SSL_VERIFY_MISSING

    def test_parse_headers_no_cert(self):
        from oso.framework.auth import mtls

        request = SimpleNamespace(
            headers=dict(
                [
                    (mtls.HEADER_SSL_VERIFY, mtls.SSL_VERIFY_SUCCESS),
                ]
            ),
        )
        auth = mtls.parse(request)  # type: ignore
        assert auth["authorized"] is True
        assert auth["authorized_header"] is mtls.SSL_VERIFY_SUCCESS

    @pytest.mark.parametrize("which", ["py_allowed", "py_not"])
    def test_parse_headers_cert(self, _tmpdir, which):
        from oso.framework.auth import mtls

        cert = ""
        with open(_tmpdir / f"{which}.crt", "r") as f:
            for line in f:
                cert += line
        cert = quote(cert)
        with open(_tmpdir / f"{which}.fingerprint", "r") as f:
            expected_fp = mtls.load_fingerprint(f.readline())

        request = SimpleNamespace(
            headers=dict(
                [
                    (mtls.HEADER_SSL_VERIFY, mtls.SSL_VERIFY_SUCCESS),
                    (mtls.HEADER_SSL_CERT, cert),
                ]
            ),
        )
        auth = mtls.parse(request)  # type: ignore
        assert auth["authorized"]
        assert auth["authorized_header"] is mtls.SSL_VERIFY_SUCCESS
        assert auth["cert"] is not None
        assert auth["fingerprint"] == expected_fp
        assert auth["subject"] == f"CN={which}"

    def test_required(self, app, allowed_cert, allowed_fp):
        from oso.framework.auth import mtls
        from oso.framework.auth.extension import EXT_NAME

        with app.test_request_context(
            "/",
            headers={
                mtls.HEADER_SSL_VERIFY: mtls.SSL_VERIFY_SUCCESS,
                mtls.HEADER_SSL_CERT: allowed_cert,
            },
        ):
            app.preprocess_request()
            auth = getattr(g, EXT_NAME, {})
            assert auth[mtls.NAME]["authorized"]
            assert auth[mtls.NAME]["fingerprint"] == mtls.load_fingerprint(allowed_fp)
            rv = app.dispatch_request()
            assert rv == 200

    def test_required_not_verified(self, app, client):
        with app.app_context():
            response = client.get("/")
            assert response.status_code == 401

    def test_required_missing_cert(self, app, client):
        from oso.framework.auth import mtls

        with app.app_context():
            response = client.get(
                "/",
                headers={
                    mtls.HEADER_SSL_VERIFY: mtls.SSL_VERIFY_SUCCESS,
                },
            )
            assert response.status_code == 403

    def test_required_not_allowed_cert(self, app, client, not_allowed_cert):
        from oso.framework.auth import mtls

        with app.app_context():
            response = client.get(
                "/",
                headers={
                    mtls.HEADER_SSL_VERIFY: mtls.SSL_VERIFY_SUCCESS,
                    mtls.HEADER_SSL_CERT: not_allowed_cert,
                },
            )
            assert response.status_code == 403
