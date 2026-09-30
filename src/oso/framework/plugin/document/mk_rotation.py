#
# (c) Copyright IBM Corp. 2025, 2026
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

from . import DocType, DocumentGenerator, DocumentHandler, DocumentMetadata

_logger = get_logger("mk-rotation")


class MkRotationMetadata(DocumentMetadata):
    """An HSM master-key rotation request, or its result."""

    doc_type: Literal[DocType.MK_ROTATION] = DocType.MK_ROTATION
    status: Literal["success", "error"] | None = None
    rewrapped_key_ids: list[str] | None = None
    error: str | None = None


class MkRotation(DocumentHandler):
    """Rotate the master key: request on the frontend, rewrap on the backend."""

    doc_type = DocType.MK_ROTATION
    metadata_model = MkRotationMetadata
    label = "MK rotation"

    def generate(
        self, gen: DocumentGenerator, key: str, plugin_app: Any = None
    ) -> MkRotationMetadata:
        """Frontend: queue the request. Backend: rewrap and queue the result."""
        if gen.mode == "frontend":
            return gen.add(  # type: ignore[return-value]
                key, MkRotationMetadata(), resend=True, unique=True
            )
        done = gen.generated(self.doc_type, key)
        if done is None or done.status == "error":  # type: ignore[attr-defined]
            done = self._rewrap(key, plugin_app)
        return gen.add(key, done)  # type: ignore[return-value]

    @staticmethod
    def _rewrap(key: str, plugin_app: Any) -> MkRotationMetadata:
        if not callable(getattr(plugin_app, "rewrap", None)):
            _logger.warning(f"plugin has no rewrap() hook rotation_id={key}")
            return MkRotationMetadata(status="success", rewrapped_key_ids=[])
        try:
            result = plugin_app.rewrap(rotation_id=key)
        except Exception as exc:
            _logger.exception(f"Rewrap failed rotation_id={key}")
            return MkRotationMetadata(
                status="error",
                rewrapped_key_ids=[],
                error=f"{type(exc).__name__}: {exc}",
            )
        return MkRotationMetadata(
            status="success",
            rewrapped_key_ids=list(getattr(result, "rewrapped_key_ids", [])),
        )

    def on_incoming(
        self,
        gen: DocumentGenerator,
        key: str,
        meta: DocumentMetadata,
        plugin_app: Any = None,
    ) -> None:
        """Backend: rewrap and queue the result. Frontend: forget the rotation."""
        if gen.mode == "backend":
            gen.generate(self.doc_type, key, plugin_app)
            return
        if meta.status == "error":  # type: ignore[attr-defined]
            _logger.error(
                f"MK rotation failed on backend rotation_id={key}: {meta.error}"  # type: ignore[attr-defined]
            )
        gen.remove(self.doc_type, key)
