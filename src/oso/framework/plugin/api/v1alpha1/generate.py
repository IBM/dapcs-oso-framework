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
"""Generate Endpoint.

POST /api/{mode}/v1alpha1/generate
    Generates a framework document with a random UUID as its id. Body:
    ``{"doc_type": "<DocType>"}``. Returns ``{"id": ..., "metadata": {...}}``;
    the document goes out on the next ``GET /documents``. 400 for an unknown
    ``doc_type`` or one this mode cannot generate; 409 if the type disallows
    duplicates and another is pending.

    Allowed for ``component`` clients and for admins (see
    ``PluginConfig.admin_ca``).
"""

import uuid

from functools import wraps
from typing import Callable

from cryptography.exceptions import InvalidSignature
from flask import g, jsonify, request
from flask.views import MethodView
from werkzeug.exceptions import BadRequest

from oso.framework.auth.common import EXT_NAME
from oso.framework.auth.extension import RequireAuth
from oso.framework.plugin import current_oso_plugin_app
from oso.framework.plugin.document import DocType
from oso.framework.plugin.extension import current_oso_plugin


def _is_admin() -> bool:
    """Whether the mTLS client cert is an allowlisted admin cert from the admin CA."""
    plugin_ext = current_oso_plugin()
    result = getattr(g, EXT_NAME, {}).get("mtls", {})
    cert = result.get("cert")
    if (
        plugin_ext.admin_ca is None
        or cert is None
        or result.get("fingerprint") not in plugin_ext.admin_fingerprints
    ):
        return False
    try:
        cert.verify_directly_issued_by(plugin_ext.admin_ca)
    except (InvalidSignature, TypeError, ValueError):
        return False
    return True


def _require_component_or_admin(f: Callable) -> Callable:
    component_only = RequireAuth("mtls", "component")(f)

    @wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs) if _is_admin() else component_only(*args, **kwargs)

    return decorated


class Api(MethodView):
    """Plugin Generate View."""

    ENDPOINT = "/".join(__name__.split(".")[-2:])

    @_require_component_or_admin
    def post(self):
        """POST /v1alpha1/generate endpoint."""
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise BadRequest("Request body must be a JSON object")
        try:
            doc_type = DocType(body.get("doc_type"))
        except ValueError:
            raise BadRequest(f"Unknown doc_type {body.get('doc_type')!r}")
        key = str(uuid.uuid4())

        meta = current_oso_plugin().doc_generator.generate(
            doc_type, key, current_oso_plugin_app()
        )
        return jsonify({"id": key, "metadata": meta.model_dump(mode="json")})
