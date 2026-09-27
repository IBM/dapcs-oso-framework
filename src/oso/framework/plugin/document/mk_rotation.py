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
"""Master Key (MK) rotation document types.

Frontend: ``PUT /documents`` (``doc_type=mk_rotation``, ``key=<rotation_id>``)
generates an mk_rotation doc. It is re-sent on every GET and stays pending
(blocking another rotation) until an mk_rotation_done doc for the same rotation
arrives on POST, or it is cleared via ``DELETE /documents``. A done doc carrying
an ``error`` also ends the rotation (logged); re-PUT the same id to retry.

Backend: an incoming mk_rotation doc (or ``PUT /documents`` with
``doc_type=mk_rotation_done``) generates an mk_rotation_done doc, calling the
plugin's ``rewrap()`` hook until it succeeds once for the rotation; repeats
re-send the stored result. A failing ``rewrap()`` yields a done doc with
``error`` set. ``rewrap()`` must itself be safe to retry after a partial
failure (``SigningServerAddon.rewrap_keys`` is).

Incoming rotation docs are handled after ``plugin.to_isv()`` has processed the
other documents in the same POST.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from oso.framework.core.logging import get_logger

from . import DocType, DocumentGenerator, DocumentHandler, DocumentMetadata

_logger = get_logger("mk-rotation")

#: Allowed rotation ids; they end up in keystore file names.
ROTATION_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
_RotationId = Field(pattern=f"^{ROTATION_ID_PATTERN}$")


class MkRotationMetadata(DocumentMetadata):
    """Signals an HSM master-key rotation (frontend -> backend).

    Attributes
    ----------
    rotation_id : str
        Opaque identifier for this rotation event, chosen by the
        orchestrator.  Echoed back in ``MkRotationDoneMetadata``.
    """

    doc_type: Literal[DocType.MK_ROTATION] = DocType.MK_ROTATION
    rotation_id: str = _RotationId


class MkRotationDoneMetadata(DocumentMetadata):
    """Confirms a master-key rotation rewrap finished (backend -> frontend).

    Attributes
    ----------
    rotation_id : str
        Must equal the ``rotation_id`` from ``MkRotationMetadata``.

    rewrapped_key_ids : list[str]
        Ordered list of key IDs whose blobs were rewrapped.

    error : str | None
        Set if the rewrap failed; ``rewrapped_key_ids`` is then empty.
    """

    doc_type: Literal[DocType.MK_ROTATION_DONE] = DocType.MK_ROTATION_DONE
    rotation_id: str = _RotationId
    rewrapped_key_ids: list[str]
    error: str | None = None


class MkRotation(DocumentHandler):
    """Signal to rotate the master key (frontend -> backend)."""

    doc_type = DocType.MK_ROTATION
    metadata_model = MkRotationMetadata
    label = "MK rotation"
    allow_duplicates = False
    consumed_in = "backend"
    resend = True

    def generate(
        self, gen: DocumentGenerator, key: str, plugin_app: Any = None
    ) -> MkRotationMetadata:
        """Queue the rotation signal."""
        return gen.add(key, MkRotationMetadata(rotation_id=key))  # type: ignore[return-value]

    def on_incoming(
        self,
        gen: DocumentGenerator,
        meta: DocumentMetadata,
        plugin_app: Any = None,
    ) -> None:
        """Backend: rewrap and queue the (possibly failed) confirmation."""
        gen.generate(DocType.MK_ROTATION_DONE, meta.rotation_id, plugin_app)  # type: ignore[attr-defined]


class MkRotationDone(DocumentHandler):
    """Confirmation that rewrap finished (backend -> frontend)."""

    doc_type = DocType.MK_ROTATION_DONE
    metadata_model = MkRotationDoneMetadata
    label = "MK rotation done"
    consumed_in = "frontend"

    def generate(
        self, gen: DocumentGenerator, key: str, plugin_app: Any = None
    ) -> MkRotationDoneMetadata:
        """Rewrap until it succeeds once per rotation; queue the confirmation.

        A repeated call re-queues a successful confirmation instead of
        rewrapping again, and retries a failed one.
        """
        done = gen.generated(self.doc_type, key)
        if done is None or done.error:  # type: ignore[attr-defined]
            done = self._rewrap(key, plugin_app)
        return gen.add(key, done)  # type: ignore[return-value]

    @staticmethod
    def _rewrap(key: str, plugin_app: Any) -> MkRotationDoneMetadata:
        if not callable(getattr(plugin_app, "rewrap", None)):
            _logger.warning(f"plugin has no rewrap() hook rotation_id={key}")
            return MkRotationDoneMetadata(rotation_id=key, rewrapped_key_ids=[])
        try:
            result = plugin_app.rewrap(rotation_id=key)
        except Exception as exc:
            _logger.exception(f"Rewrap failed rotation_id={key}")
            return MkRotationDoneMetadata(
                rotation_id=key,
                rewrapped_key_ids=[],
                error=f"{type(exc).__name__}: {exc}",
            )
        return MkRotationDoneMetadata(
            rotation_id=key,
            rewrapped_key_ids=list(getattr(result, "rewrapped_key_ids", [])),
        )

    def on_incoming(
        self,
        gen: DocumentGenerator,
        meta: DocumentMetadata,
        plugin_app: Any = None,
    ) -> None:
        """Frontend: the rotation finished (or failed), so forget it."""
        if meta.error:  # type: ignore[attr-defined]
            _logger.error(
                f"MK rotation failed on backend rotation_id={meta.rotation_id}: "  # type: ignore[attr-defined]
                f"{meta.error}"  # type: ignore[attr-defined]
            )
        gen.remove(DocType.MK_ROTATION, meta.rotation_id)  # type: ignore[attr-defined]
