#
# (c) Copyright IBM Corp. 2026
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
"""Generate Endpoint."""

import uuid

from flask import jsonify, request
from flask.views import MethodView

from oso.framework.auth.extension import RequireAuth
from oso.framework.plugin import current_oso_plugin_app
from oso.framework.plugin.extension import current_oso_plugin


class Api(MethodView):
    """Plugin Generate View."""

    ENDPOINT = "/".join(__name__.split(".")[-2:])

    @RequireAuth("mtls", "component", "admin")
    def post(self):
        """POST /v1alpha1/generate endpoint.

        Parameters
        ----------
        doc_type : str
            JSON body field. The framework document type to generate.

        Returns
        -------
        body : dict
            ``{"id": ..., "metadata": {...}}`` of the queued document, with a 200
            HTTP response code.

        Raises
        ------
        BadRequest
            If ``doc_type`` is missing or unknown.
        """
        body = request.get_json(silent=True)
        doc_type = body.get("doc_type") if isinstance(body, dict) else None
        doc_id = str(uuid.uuid4())
        meta = current_oso_plugin().doc_generator.generate(
            doc_type, doc_id, current_oso_plugin_app()
        )
        return jsonify({"id": doc_id, "metadata": meta.model_dump(mode="json")})
