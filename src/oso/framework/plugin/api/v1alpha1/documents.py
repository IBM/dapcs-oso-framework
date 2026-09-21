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
    Calls ``plugin.to_oso()`` and returns the document list.

    **Frontend only — mk_rotation injection**
    If a pending mk_rotation state is tracked on the :class:`PluginExtension`
    (set via ``POST /api/frontend/v1alpha1/rewrap`` or by the orchestrator),
    the framework appends a ``V1_5.GeneratedDocument`` with
    ``metadata.doc_type = "mk_rotation"`` *before* returning.  The plugin
    itself does **not** need to know about this.

POST /api/{mode}/v1alpha1/documents
    Calls ``plugin.to_isv()`` with the supplied document list.

    **Backend only — mk_rotation detection**
    Before forwarding to ``plugin.to_isv()``, the framework inspects each
    document's metadata.  If any document has ``doc_type = "mk_rotation"``
    the framework:

    1. Calls
       :meth:`~oso.framework.plugin.addons.signing_server.SigningServerAddon.rewrap_keys`
       directly on the ``SigningServer`` addon (if present).
    2. Stores a ``MkRotationDoneMetadata`` on the extension so the next
       ``GET /documents`` call includes a ``mk_rotation_done`` document.
    3. Strips the mk_rotation document from the list before passing it to
       the plugin, so the plugin never sees it.
"""


from flask import jsonify, request
from flask.views import MethodView

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
        """GET /v1alpha1/documents endpoint.

        Returns the plugin's document list, optionally prepending a
        framework-generated mk_rotation document (frontend) or
        mk_rotation_done document (backend).
        """
        plugin_ext = current_oso_plugin()

        # Obtain the plugin's own documents.
        doc_list: V1_3.DocumentList = current_oso_plugin_app().to_oso()

        doc_list = plugin_ext.mk_rotation_addon.inject_documents(
            doc_list=doc_list,
            mode=plugin_ext.config.mode,
        )

        return doc_list.model_dump_json()

    @RequireAuth("mtls", "component")
    def post(self):
        """POST /v1alpha1/documents endpoint.

        On the **backend**: detects mk_rotation documents, drives rewrap
        automatically via the SigningServer addon, then strips those
        documents before calling ``plugin.to_isv()``.

        On the **frontend**: passes the document list straight to
        ``plugin.to_isv()``, which handles mk_rotation_done confirmation
        docs as it sees fit (typically just logging them).
        """
        plugin_ext = current_oso_plugin()
        raw_docs = V1_3.DocumentList.model_validate_json(request.get_data())

        if plugin_ext.config.mode == "backend":
            signing_server = plugin_ext.addons.get("SigningServer")
            raw_docs = plugin_ext.mk_rotation_addon.process_backend_documents(
                doc_list=raw_docs,
                signing_server_addon=signing_server,
            )

        return jsonify(current_oso_plugin_app().to_isv(raw_docs))
