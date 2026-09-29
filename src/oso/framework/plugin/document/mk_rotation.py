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
"""Master Key (MK) rotation document type.

A single ``mk_rotation`` document carries both the request (frontend ->
backend) and its result (backend -> frontend). A rotation is identified by its
document id, a UUID shared by request and result, and passed to ``rewrap()``
as ``rotation_id``.

Frontend: ``POST /generate`` (``doc_type=mk_rotation``) generates a request. It
is re-sent on every GET and stays pending (blocking another rotation) until a
result with the same id arrives on ``POST /documents``, or it is cleared via
``DELETE /documents``. A result with ``status="error"`` also ends the rotation
(logged); generate a new one to retry.

Backend: an incoming request (or ``POST /generate``) generates a result,
calling the plugin's ``rewrap()`` hook until it succeeds once for the rotation;
repeats re-send the stored result. A failing ``rewrap()`` yields a result with
``status="error"`` and the message in ``error``. ``rewrap()`` must itself be safe
to retry after a partial failure (``SigningServerAddon.rewrap_keys`` is).

Incoming rotation docs are handled after ``plugin.to_isv()`` has processed the
other documents in the same POST.
"""

from __future__ import annotations

from typing import Any, Literal

from oso.framework.core.logging import get_logger

from . import DocType, DocumentGenerator, DocumentHandler, DocumentMetadata

_logger = get_logger("mk-rotation")

#: Allowed rotation ids; they end up in keystore file names.
ROTATION_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"


class MkRotationMetadata(DocumentMetadata):
    """An HSM master-key rotation request, or its result.

    Attributes
    ----------
    status : "success" | "error" | None
        Result only: outcome of the rewrap; ``None`` on a request.

    rewrapped_key_ids : list[str] | None
        Result only: ordered list of key IDs whose blobs were rewrapped.

    error : str | None
        Result only: the error message when ``status`` is ``"error"``;
        ``rewrapped_key_ids`` is then empty.
    """

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
        """Frontend: queue the request. Backend: rewrap and queue the result.

        On the backend a repeated call re-queues a successful result instead
        of rewrapping again, and retries a failed one.
        """
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
