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
"""Master Key (MK) rotation document type."""

from __future__ import annotations

from typing import Any, Literal

from oso.framework.core.logging import get_logger

from . import DocumentGenerator, DocumentHandler, DocumentMetadata

_logger = get_logger("mk-rotation")

MK_ROTATION = "mk_rotation"


class MkRotationMetadata(DocumentMetadata):
    """An HSM master-key rotation request, or its result."""

    doc_type: Literal["mk_rotation"] = MK_ROTATION
    status: Literal["success", "error"] | None = None
    rewrapped_key_ids: list[str] | None = None
    error: str | None = None


class MkRotation(DocumentHandler):
    """Rotate the master key: request on the frontend, rewrap on the backend.

    The backend calls the plugin's ``rewrap(rotation_id=...) -> list[str]`` hook,
    which re-wraps every stored key blob and returns the re-wrapped key ids.
    """

    doc_type = MK_ROTATION
    metadata_model = MkRotationMetadata

    def generate(
        self, gen: DocumentGenerator, doc_id: str, plugin_app: Any
    ) -> MkRotationMetadata:
        """Frontend: queue the rotation request."""
        gen.add(doc_id, request := MkRotationMetadata())
        return request

    def on_incoming(
        self,
        gen: DocumentGenerator,
        doc_id: str,
        meta: DocumentMetadata,
        plugin_app: Any,
    ) -> None:
        """Backend: rewrap once and queue the result. Frontend: end the rotation."""
        if gen.mode == "backend":
            done = gen.get(doc_id)
            # The frontend re-sends until it sees the result; rewrap only once.
            if not (isinstance(done, MkRotationMetadata) and done.status == "success"):
                done = self._rewrap(doc_id, plugin_app)
            gen.add(doc_id, done)
            return
        if isinstance(meta, MkRotationMetadata) and meta.status == "error":
            _logger.error(f"MK rotation failed on backend id={doc_id}: {meta.error}")
        gen.remove(doc_id)

    @staticmethod
    def _rewrap(doc_id: str, plugin_app: Any) -> MkRotationMetadata:
        try:
            key_ids = list(plugin_app.rewrap(rotation_id=doc_id))
        except Exception as exc:
            # Includes a plugin without a rewrap() hook: nothing was rewrapped.
            _logger.exception(f"Rewrap failed id={doc_id}")
            return MkRotationMetadata(
                status="error",
                rewrapped_key_ids=[],
                error=f"{type(exc).__name__}: {exc}",
            )
        return MkRotationMetadata(status="success", rewrapped_key_ids=key_ids)
