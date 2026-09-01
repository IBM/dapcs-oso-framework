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
    the framework appends a ``V1_5.Document`` with
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
from oso.framework.data.types import V1_5
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
        doc_list: V1_5.DocumentList = current_oso_plugin_app().to_oso()

        # --- Frontend: inject pending mk_rotation sentinel ---
        if plugin_ext.config.mode == "frontend":
            pending = plugin_ext.pop_pending_mk_rotation()
            if pending is not None:
                mk_doc = V1_5.Document.with_metadata(
                    id=f"mk_rotation_{pending.rotation_id}",
                    content="",
                    metadata=pending,
                )
                doc_list.documents.insert(0, mk_doc)
                doc_list.count = len(doc_list.documents)
                _logger.info(
                    f"Injected mk_rotation doc rotation_id={pending.rotation_id}"
                )

        # --- Backend: inject pending mk_rotation_done confirmation ---
        if plugin_ext.config.mode == "backend":
            pending_done = plugin_ext.pop_pending_mk_rotation_done()
            if pending_done is not None:
                done_doc = V1_5.Document.with_metadata(
                    id=f"mk_rotation_done_{pending_done.rotation_id}",
                    content="",
                    metadata=pending_done,
                )
                doc_list.documents.insert(0, done_doc)
                doc_list.count = len(doc_list.documents)
                _logger.info(
                    f"Injected mk_rotation_done doc "
                    f"rotation_id={pending_done.rotation_id}"
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
        raw_docs = V1_5.DocumentList.model_validate_json(request.get_data())

        if plugin_ext.config.mode == "backend":
            raw_docs = _handle_backend_mk_rotation(raw_docs, plugin_ext)

        return jsonify(current_oso_plugin_app().to_isv(raw_docs))


# ---------------------------------------------------------------------------
# Framework-internal mk_rotation handler (backend)
# ---------------------------------------------------------------------------

def _handle_backend_mk_rotation(
    doc_list: V1_5.DocumentList,
    plugin_ext,
) -> V1_5.DocumentList:
    """Strip mk_rotation documents, drive rewrap, schedule done confirmation.

    Parameters
    ----------
    doc_list : V1_5.DocumentList
        The full document list received from the orchestrator.
    plugin_ext : PluginExtension
        Current extension instance (carries addon registry and state).

    Returns
    -------
    V1_5.DocumentList
        The filtered list with mk_rotation documents removed.
    """
    regular_docs: list[V1_5.Document] = []

    for doc in doc_list.documents:
        if not doc.is_mk_rotation():
            regular_docs.append(doc)
            continue

        # Found an mk_rotation document — drive rewrap in the framework.
        try:
            meta = doc.parse_mk_rotation_metadata()
        except Exception as exc:
            _logger.warning(
                f"Skipping malformed mk_rotation doc id={doc.id!r}: {exc}"
            )
            continue

        _logger.info(
            f"mk_rotation detected rotation_id={meta.rotation_id}. "
            "Driving rewrap via SigningServer addon."
        )

        rewrapped_ids = _drive_rewrap(plugin_ext)

        done_meta = V1_5.MkRotationDoneMetadata(
            rotation_id=meta.rotation_id,
            rewrapped_key_ids=rewrapped_ids,
        )
        plugin_ext.set_pending_mk_rotation_done(done_meta)

        _logger.info(
            f"Rewrap complete rotation_id={meta.rotation_id} "
            f"rewrapped={rewrapped_ids}"
        )

    return V1_5.DocumentList(
        documents=regular_docs,
        count=len(regular_docs),
    )


def _drive_rewrap(plugin_ext) -> list[str]:
    """Invoke rewrap_keys on the SigningServer addon if present.

    If no SigningServer addon is registered the function returns an empty
    list and logs a warning — this allows plugins that use a different
    key-management backend to still receive the mk_rotation document
    through their own ``to_isv()`` path (they just won't see the filtered
    version).

    Parameters
    ----------
    plugin_ext : PluginExtension

    Returns
    -------
    list[str]
        Rewrapped key IDs, or ``[]`` if no SigningServer addon found.
    """
    signing_server = plugin_ext.addons.get("SigningServer")
    if signing_server is None:
        _logger.warning(
            "mk_rotation received but no SigningServer addon is configured. "
            "Rewrap skipped."
        )
        return []

    return signing_server.rewrap_keys()
