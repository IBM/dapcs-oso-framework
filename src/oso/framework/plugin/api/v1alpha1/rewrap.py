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
"""Rewrap Endpoint.

``POST /api/frontend/v1alpha1/rewrap``
    Schedules an mk_rotation event on the *frontend* plugin.  The next
    ``GET /api/frontend/v1alpha1/documents`` call will include a
    ``V1_5.GeneratedDocument`` with ``metadata.doc_type = "mk_rotation"`` so the
    OSO orchestrator can tunnel it to the backend.

``POST /api/backend/v1alpha1/rewrap``
    Directly drives master-key rotation rewrap on the *backend* plugin:

    1. Calls
       :meth:`~oso.framework.plugin.addons.signing_server.SigningServerAddon.rewrap_keys`
       via the ``SigningServer`` addon (framework handles this — no plugin
       involvement required).
    2. If the plugin also defines a ``rewrap(rotation_id)`` method, calls
       it so ISV-specific post-rewrap actions (e.g. publishing new public
       keys to Fireblocks) can be performed.
    3. Returns the ``MkRotationDoneMetadata`` as JSON.
"""

import uuid

from flask import jsonify, request
from flask.views import MethodView
from werkzeug.exceptions import BadRequest

from oso.framework.auth.extension import RequireAuth
from oso.framework.core.logging import get_logger
from oso.framework.plugin import current_oso_plugin_app
from oso.framework.plugin.extension import current_oso_plugin

_logger = get_logger("rewrap-api")


class Api(MethodView):
    """Plugin Rewrap View.

    Request body (JSON, optional)::

        {"rotation_id": "<uuid>"}

    If ``rotation_id`` is omitted a random UUID is generated.

    **Frontend response** (202 Accepted)::

        {"rotation_id": "<uuid>", "status": "scheduled"}

    **Backend response** (200 OK)::

        {
            "doc_type": "mk_rotation_done",
            "rotation_id": "<uuid>",
            "rewrapped_key_ids": ["<key-id>", ...]
        }
    """

    ENDPOINT = "/".join(__name__.split(".")[-2:])

    @RequireAuth("mtls", "component")
    def post(self):
        """POST /v1alpha1/rewrap endpoint."""
        rotation_id = _parse_rotation_id()
        plugin_ext = current_oso_plugin()

        if plugin_ext.config.mode == "frontend":
            return _handle_frontend_rewrap(rotation_id, plugin_ext)

        return _handle_backend_rewrap(rotation_id, plugin_ext)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_rotation_id() -> str:
    raw = request.get_data()
    if raw:
        try:
            body = request.get_json(force=True)
            rid = body.get("rotation_id") if body else None
        except Exception:
            raise BadRequest("Request body must be valid JSON or empty")
    else:
        rid = None
    return rid or str(uuid.uuid4())


def _handle_frontend_rewrap(rotation_id: str, plugin_ext) -> tuple:
    """Schedule the mk_rotation event; it will be injected on next GET /documents."""
    res = plugin_ext.mk_rotation_addon.handle_frontend_rewrap(rotation_id)
    return jsonify(res), 202


def _handle_backend_rewrap(rotation_id: str, plugin_ext) -> tuple:
    """Drive rewrap directly on the backend via the MkRotation addon."""
    signing_server = plugin_ext.addons.get("SigningServer")
    plugin = current_oso_plugin_app()
    done_meta = plugin_ext.mk_rotation_addon.handle_backend_rewrap(
        rotation_id=rotation_id,
        signing_server_addon=signing_server,
        plugin_app=plugin,
    )
    return jsonify(done_meta.model_dump()), 200
