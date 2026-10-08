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

from . import DocType, DocumentGenerator, DocumentMetadata

_logger = get_logger("mk-rotation")


class MkRotationMetadata(DocumentMetadata):
    """An HSM master-key rotation request, or its result."""

    doc_type: Literal[DocType.MK_ROTATION] = DocType.MK_ROTATION
    status: Literal["success", "error"] | None = None
    rewrapped_key_ids: list[str] | None = None
    error: str | None = None


class MkRotationGenerator(DocumentGenerator):
    """Rotate the master key: request on the frontend, rewrap on the backend.

    The backend calls the plugin's ``rewrap(mk_rotation_request_id=...)`` hook,
    which re-wraps every stored key blob and returns the re-wrapped key ids.
    """

    doc_type = DocType.MK_ROTATION
    metadata_model = MkRotationMetadata

    def generate(self, doc_id: str, plugin_app: Any) -> MkRotationMetadata:
        """Frontend: queue the rotation request."""
        return self.add(doc_id, MkRotationMetadata())

    def on_backend(
        self, doc_id: str, meta: DocumentMetadata, plugin_app: Any
    ) -> None:
        """Backend: rewrap once and queue the result."""
        done = self.get(doc_id)
        # The frontend re-sends the request until it sees a successful result;
        # skip the rewrap if we already completed it.
        if not (isinstance(done, MkRotationMetadata) and done.status == "success"):
            done = self._rewrap(doc_id, plugin_app)
        self.add(doc_id, done)

    @staticmethod
    def _rewrap(doc_id: str, plugin_app: Any) -> MkRotationMetadata:
        try:
            key_ids = list(plugin_app.rewrap(mk_rotation_request_id=doc_id))
        except Exception as exc:
            # Includes a plugin without a rewrap() hook: nothing was rewrapped.
            _logger.exception(f"Rewrap failed id={doc_id}")
            return MkRotationMetadata(
                status="error",
                rewrapped_key_ids=[],
                error=f"{type(exc).__name__}: {exc}",
            )
        return MkRotationMetadata(status="success", rewrapped_key_ids=key_ids)
