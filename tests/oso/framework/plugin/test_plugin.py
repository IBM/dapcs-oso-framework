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


import copy
import json

import pytest

from oso.framework.data.types import V1_3
from oso.framework.plugin import PluginProtocol, create_app, current_oso_plugin_app


class _BasePluginTests:
    @pytest.fixture(scope="function")
    def _setup_app(self, ConfigManager, LoggingFactory):
        def _fn():
            from oso.framework.auth.common import AuthConfig  # noqa: F401
            from oso.framework.config.models.logging import LoggingConfig  # noqa: F401
            from oso.framework.plugin.extension import PluginConfig  # noqa: F401

            config = ConfigManager.reload()
            LoggingFactory(**config.logging.model_dump())

        return _fn

    @pytest.fixture(scope="function")
    def _enable_mtls(self, monkeypatch, _setup_app):
        """
        Override the mTLS parser to use the headers ``X-TEST-SSL-VERIFY`` and
        ``X-TEST-SSL-FINGERPRINT`` to authenticate the user. A fingerprint value of
        ``VALID`` will allow the request to go through.
        """
        monkeypatch.setenv(
            "AUTH__PARSERS__0__TYPE",
            "oso.framework.auth.mtls",
        )
        monkeypatch.setenv(
            "AUTH__PARSERS__0__ALLOWLIST",
            json.dumps({"component": ["VALID", "ALSO_VALID"]}),
        )

        def _fn():
            import oso.framework.auth.mtls

            def _parse_allowlist(x):
                return x

            monkeypatch.setattr(
                oso.framework.auth.mtls,
                "parse_allowlist",
                _parse_allowlist,
            )

            def _parse(x):
                return dict(
                    authorized=bool(x.headers.get("X-TEST-SSL-VERIFY", "False")),
                    errors=[],
                    fingerprint=x.headers.get("X-TEST-SSL-FINGERPRINT", "NOT_VALID"),
                    _user=x.headers.get("X-TEST-SSL-FINGERPRINT", "NOT_VALID"),
                )

            monkeypatch.setattr(
                oso.framework.auth.mtls,
                "parse",
                _parse,
            )

        return _fn


class TestStartup(_BasePluginTests):
    @pytest.mark.parametrize("mode", ["frontend", "backend"])
    def test_plugin_modes(
        self,
        monkeypatch,
        mode,
        _setup_app,
        _enable_mtls,
    ):
        monkeypatch.setenv("PLUGIN__MODE", mode)
        monkeypatch.setenv(
            "PLUGIN__APPLICATION",
            "oso.framework.plugin.test.isv_cls:TestISVApp",
        )

        _enable_mtls()
        _setup_app()

        app = create_app()
        assert app is not None
        with app.app_context():
            assert isinstance(current_oso_plugin_app(), PluginProtocol)


class TestApp(_BasePluginTests):
    @pytest.fixture(params=["frontend", "backend"])
    def mode(self, request):
        return request.param

    @pytest.fixture()
    def app(self, mode, monkeypatch, document_set, event_set, _setup_app, _enable_mtls):
        monkeypatch.setenv("PLUGIN__MODE", mode)
        monkeypatch.setenv(
            "PLUGIN__APPLICATION",
            "oso.framework.plugin.test.isv_cls:TestISVApp",
        )

        _enable_mtls()
        _setup_app()

        app = create_app()
        app.config.update(
            {
                "TESTING": True,
            }
        )
        with app.app_context():
            plugin = current_oso_plugin_app()
            plugin._set_test_documents(copy.deepcopy(document_set["isv"]))  # type: ignore
            yield app

    @pytest.fixture()
    def client(self, app):
        return app.test_client()

    def test_isv2oso(self, mode, client, document_set):
        isv2oso = client.get(
            f"/api/{mode}/v1alpha1/documents",
            headers={
                "X-TEST-SSL-VERIFY": "True",
                "X-TEST-SSL-FINGERPRINT": "VALID",
            },
        )
        assert isv2oso.status_code == 200
        assert (
            V1_3.DocumentList.model_validate_json(isv2oso.data) == document_set["oso"]
        )

    def test_oso2isv(self, mode, client, document_set):
        oso2isv = client.post(
            f"/api/{mode}/v1alpha1/documents",
            data=document_set["oso"].model_dump_json(),
            content_type="application/json",
            headers={
                "X-TEST-SSL-VERIFY": "True",
                "X-TEST-SSL-FINGERPRINT": "VALID",
            },
        )
        assert oso2isv.status_code == 200
        assert oso2isv.get_json() == document_set["isv"]

    def test_events(self, mode, client, event_set):
        response = client.post(
            f"/api/{mode}/v1alpha1/events",
            data=event_set["oso"].model_dump_json(),
            content_type="application/json",
            headers={
                "X-TEST-SSL-VERIFY": "True",
                "X-TEST-SSL-FINGERPRINT": "VALID",
            },
        )
        assert response.status_code == 200
        # stub returns EventResponse() — no holds → empty object
        assert V1_3.EventResponse.model_validate_json(response.data) == V1_3.EventResponse()  # noqa: E501
        assert response.get_json() == {}

    def test_status(self, mode, client, document_set):
        current_oso_plugin_app()._set_status(200, "OK")  # type: ignore
        status = client.get(
            f"/api/{mode}/v1alpha1/status",
            data=document_set["oso"].model_dump_json(),
            content_type="application/json",
            headers={
                "X-TEST-SSL-VERIFY": "True",
                "X-TEST-SSL-FINGERPRINT": "VALID",
            },
        )
        assert status.status_code == 200
        assert V1_3.ComponentStatus.model_validate_json(
            status.data
        ) == V1_3.ComponentStatus(status_code=200, status="OK")


class TestModule(_BasePluginTests):
    @pytest.fixture(params=["frontend", "backend"])
    def mode(self, request):
        return request.param

    @pytest.fixture()
    def app(self, mode, monkeypatch, document_set, event_set, _setup_app, _enable_mtls):
        monkeypatch.setenv("PLUGIN__MODE", mode)
        monkeypatch.setenv(
            "PLUGIN__APPLICATION",
            "oso.framework.plugin.test.isv_mod",
        )

        _enable_mtls()
        _setup_app()

        app = create_app()
        app.config.update(
            {
                "TESTING": True,
            }
        )
        with app.app_context():
            plugin = current_oso_plugin_app()
            plugin._set_test_documents(copy.deepcopy(document_set["isv"]))  # type: ignore
            yield app

    @pytest.fixture()
    def client(self, app):
        return app.test_client()

    def test_isv2oso(self, mode, client, document_set):
        isv2oso = client.get(
            f"/api/{mode}/v1alpha1/documents",
            headers={
                "X-TEST-SSL-VERIFY": "True",
                "X-TEST-SSL-FINGERPRINT": "VALID",
            },
        )
        assert isv2oso.status_code == 200
        assert (
            V1_3.DocumentList.model_validate_json(isv2oso.data) == document_set["oso"]
        )

    def test_oso2isv(self, mode, client, document_set):
        oso2isv = client.post(
            f"/api/{mode}/v1alpha1/documents",
            data=document_set["oso"].model_dump_json(),
            content_type="application/json",
            headers={
                "X-TEST-SSL-VERIFY": "True",
                "X-TEST-SSL-FINGERPRINT": "VALID",
            },
        )
        assert oso2isv.status_code == 200
        assert oso2isv.get_json() == document_set["isv"]

    def test_status(self, mode, client, document_set):
        current_oso_plugin_app()._set_status(200, "OK")  # type: ignore
        status = client.get(
            f"/api/{mode}/v1alpha1/status",
            data=document_set["oso"].model_dump_json(),
            content_type="application/json",
            headers={
                "X-TEST-SSL-VERIFY": "True",
                "X-TEST-SSL-FINGERPRINT": "VALID",
            },
        )
        assert status.status_code == 200
        assert V1_3.ComponentStatus.model_validate_json(
            status.data
        ) == V1_3.ComponentStatus(status_code=200, status="OK")

    def test_events(self, mode, client, event_set):
        response = client.post(
            f"/api/{mode}/v1alpha1/events",
            data=event_set["oso"].model_dump_json(),
            content_type="application/json",
            headers={
                "X-TEST-SSL-VERIFY": "True",
                "X-TEST-SSL-FINGERPRINT": "VALID",
            },
        )
        assert response.status_code == 200
        # stub returns EventResponse() — no holds → empty object
        assert V1_3.EventResponse.model_validate_json(response.data) == V1_3.EventResponse()  # noqa: E501
        assert response.get_json() == {}

    def test_events_with_hold(self, mode, client, event_set):
        """EventResponse with hold list serialises as {"hold": [id1, id2]}."""
        import json

        event_ids = [e.eventId for e in event_set["oso"].events]
        resp = V1_3.EventResponse(hold=event_ids)
        serialised = resp.model_dump_json(exclude_defaults=True)
        # must deserialise to exactly {"hold": [id1, id2, ...]}
        assert json.loads(serialised) == {"hold": event_ids}
        # round-trip must be lossless
        assert V1_3.EventResponse.model_validate_json(serialised) == resp

    def test_404(self, mode, client, document_set):
        status = client.get(
            f"/api/{mode}/v1alpha1/test",
            data=document_set["oso"].model_dump_json(),
            content_type="application/json",
            headers={
                "X-TEST-SSL-VERIFY": "True",
                "X-TEST-SSL-FINGERPRINT": "VALID",
            },
        )
        assert status.status_code == 404
        data = status.get_json()
        assert "Not Found" in data["name"]

    def test_403(self, mode, client, document_set):
        status = client.get(
            f"/api/{mode}/v1alpha1/status",
            data=document_set["oso"].model_dump_json(),
            content_type="application/json",
            headers={
                "X-TEST-SSL-VERIFY": "True",
            },
        )
        assert status.status_code == 403
        data = status.get_json()
        assert "Forbidden" in data["name"]

        status = client.get(
            f"/api/{mode}/v1alpha1/status",
            data=document_set["oso"].model_dump_json(),
            content_type="application/json",
            headers={},
        )
        assert status.status_code == 403
        data = status.get_json()
        assert "Forbidden" in data["name"]

    def test_405(self, mode, client, document_set):
        status = client.post(
            f"/api/{mode}/v1alpha1/status",
            data=document_set["oso"].model_dump_json(),
            content_type="application/json",
            headers={
                "X-TEST-SSL-VERIFY": "True",
                "X-TEST-SSL-FINGERPRINT": "VALID",
            },
        )
        assert status.status_code == 405
        data = status.get_json()
        assert "Method Not Allowed" in data["name"]

        # /events only accepts POST — GET must return 405
        status = client.get(
            f"/api/{mode}/v1alpha1/events",
            headers={
                "X-TEST-SSL-VERIFY": "True",
                "X-TEST-SSL-FINGERPRINT": "VALID",
            },
        )
        assert status.status_code == 405
        data = status.get_json()
        assert "Method Not Allowed" in data["name"]

    def test_events_403(self, mode, client, event_set):
        # missing fingerprint → 403
        response = client.post(
            f"/api/{mode}/v1alpha1/events",
            data=event_set["oso"].model_dump_json(),
            content_type="application/json",
            headers={"X-TEST-SSL-VERIFY": "True"},
        )
        assert response.status_code == 403
        assert "Forbidden" in response.get_json()["name"]

        # no headers at all → 403
        response = client.post(
            f"/api/{mode}/v1alpha1/events",
            data=event_set["oso"].model_dump_json(),
            content_type="application/json",
            headers={},
        )
        assert response.status_code == 403
        assert "Forbidden" in response.get_json()["name"]
