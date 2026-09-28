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
"""Documents Endpoints.

GET  /api/{mode}/v1alpha1/documents
    Returns ``plugin.to_oso()`` with queued framework documents prepended
    (see :class:`~oso.framework.plugin.document.DocumentGenerator`).

POST /api/{mode}/v1alpha1/documents
    Passes ISV documents to ``plugin.to_isv()``, then dispatches framework
    documents to their ``DocumentHandler.on_incoming``.

DELETE /api/{mode}/v1alpha1/documents[?id=<document id>]
    Clears framework-generated documents (see ``POST /generate``): all of
    them, or only the one with the given id. 404 if ``id`` matches nothing.
    ISV documents are not affected.
"""

from flask import jsonify, request
from flask.views import MethodView
from werkzeug.exceptions import NotFound

from oso.framework.auth.extension import RequireAuth
from oso.framework.core.logging import get_logger
from oso.framework.data.types import V1_3
from oso.framework.plugin import current_oso_plugin_app
from oso.framework.plugin.extension import current_oso_plugin

_logger = get_logger("documents-api")


class Api(MethodView):
    """Plugin Documents View."""

    ENDPOINT = "/".join(__name__.split(".")[-2:])

    @RequireAuth("mtls", "component")
    def get(self):
        """GET /v1alpha1/documents endpoint."""
        plugin_ext = current_oso_plugin()

        doc_list = plugin_ext.doc_generator.inject(current_oso_plugin_app().to_oso())

        return doc_list.model_dump_json()

    @RequireAuth("mtls", "component")
    def post(self):
        """POST /v1alpha1/documents endpoint."""
        plugin_app = current_oso_plugin_app()
        raw_docs = V1_3.DocumentList.model_validate_json(request.get_data())

        return jsonify(
            current_oso_plugin().doc_generator.handle_incoming(
                raw_docs, plugin_app.to_isv, plugin_app
            )
        )

    @RequireAuth("mtls", "component")
    def delete(self):
        """DELETE /v1alpha1/documents endpoint."""
        doc_id = request.args.get("id")
        cleared = current_oso_plugin().doc_generator.clear(doc_id)
        if doc_id is not None and not cleared:
            raise NotFound(f"No generated document with id {doc_id!r}")
        return jsonify({"cleared": cleared})
