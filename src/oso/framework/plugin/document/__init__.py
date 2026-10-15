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
"""Framework-generated documents, carried in ``V1_3.Document.metadata``.

To add a document type, subclass `DocumentGenerator` and implement
`generate` and `on_backend`, then register the instance in
`oso.framework.plugin.extension.PluginExtension`.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, ClassVar, Iterable

from pydantic import BaseModel, ConfigDict, ValidationError
from werkzeug.exceptions import BadRequest, Conflict

from oso.framework.core.logging import get_logger
from oso.framework.data.types import V1_3

_logger = get_logger("document-generator")


class DocType(StrEnum):
    """Framework document types, sent as ``doc_type`` in the metadata."""

    MK_ROTATION = "mk_rotation"


class DocumentMetadata(BaseModel):
    """Base for framework document metadata; ``doc_type`` selects the generator."""

    model_config = ConfigDict(extra="allow")
    doc_type: str


class DocumentGenerator(ABC):
    """Base class for a single framework document type.

    Subclasses own both the generation logic (``generate``) and the backend
    processing logic (``on_backend``).  Shared state — the pending-document
    store and outbox — is managed here so that every subclass gets the same
    queuing, injection, and ejection behaviour for free.

    Flow
    ----
    Frontend
      1. ``POST /generate``  →  :meth:`generate` queues a request via :meth:`add`.
      2. ``GET /documents``  →  :meth:`inject` prepends all pending documents.
      3. ``POST /documents`` →  :meth:`eject` receives results; calls
         :meth:`on_frontend_result` per result, which removes the document on
         success or logs and leaves it pending on failure so it is re-sent.

    Backend
      1. ``GET /documents``  →  :meth:`inject` prepends unsent result documents.
      2. ``POST /documents`` →  :meth:`eject` strips framework documents and calls
         :meth:`on_backend` for each; the remaining documents are returned for
         signing.
    """

    doc_type: ClassVar[str]
    metadata_model: ClassVar[type[DocumentMetadata]]

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self._docs: dict[str, DocumentMetadata] = {}
        self._outbox: set[str] = set()

    # ------------------------------------------------------------------
    # Abstract interface — implement in each subclass
    # ------------------------------------------------------------------

    @abstractmethod
    def generate(self, doc_id: str, plugin_app: Any) -> DocumentMetadata:
        """Frontend: create and queue a document of this type (POST /generate)."""
        ...

    @abstractmethod
    def on_backend(self, doc_id: str, meta: DocumentMetadata, plugin_app: Any) -> None:
        """Backend: process an incoming document of this type (POST /documents)."""
        ...

    # ------------------------------------------------------------------
    # Shared state helpers — used by subclasses and the registry
    # ------------------------------------------------------------------

    def add(self, doc_id: str, metadata: DocumentMetadata) -> DocumentMetadata:
        """Queue a document for the next GET /documents."""
        if self.mode == "frontend" and any(
            m.doc_type == metadata.doc_type and k != doc_id
            for k, m in self._docs.items()
        ):
            raise Conflict(f"A {metadata.doc_type} document is already pending")
        self._docs[doc_id] = metadata
        self._outbox.add(doc_id)
        _logger.info(f"Queued {metadata.doc_type} id={doc_id}")
        return metadata

    def get(self, doc_id: str) -> DocumentMetadata | None:
        """Return stored metadata for ``doc_id``, whether or not already sent."""
        return self._docs.get(doc_id)

    def remove(self, doc_id: str) -> None:
        """Forget a document entirely."""
        self._docs.pop(doc_id, None)
        self._outbox.discard(doc_id)

    def clear(self, doc_id: str | None = None) -> list[str]:
        """Forget all documents, or only the one with id ``doc_id``."""
        ids = [k for k in self._docs if doc_id in (None, k)]
        for k in ids:
            self.remove(k)
        _logger.info(f"Cleared {len(ids)} generated document(s)")
        return ids

    # ------------------------------------------------------------------
    # Shared frontend result handler — subclasses may override
    # ------------------------------------------------------------------

    def on_frontend_result(self, doc_id: str, meta: DocumentMetadata) -> None:
        """Frontend: handle a result arriving for ``doc_id`` on POST /documents.

        The default behaviour removes the pending document on success and
        logs an error (leaving it pending for re-send) on failure.
        Subclasses may override to add custom logic.
        """
        if getattr(meta, "status", None) == "success":
            self.remove(doc_id)
        else:
            _logger.error(
                f"{meta.doc_type} failed on backend id={doc_id}: "
                f"{getattr(meta, 'error', None)}"
            )

    # ------------------------------------------------------------------
    # Inject / eject — called by DocumentGeneratorRegistry
    # ------------------------------------------------------------------

    def inject(self, doc_list: V1_3.DocumentList) -> V1_3.DocumentList:
        """Prepend this generator's pending documents to ``doc_list``.

        Frontend: every pending document is prepended (re-sent until cleared).
        Backend: only documents not yet sent are prepended; the outbox is then
        cleared so each result is delivered exactly once.
        """
        ids = (
            list(self._docs)
            if self.mode == "frontend"
            else [k for k in self._docs if k in self._outbox]
        )
        if self.mode == "backend":
            self._outbox.clear()
        doc_list.documents[:0] = [
            V1_3.Document(
                id=k, content="", metadata=self._docs[k].model_dump(mode="json")
            )
            for k in ids
        ]
        doc_list.count = len(doc_list.documents)
        return doc_list

    def eject(
        self, doc_list: V1_3.DocumentList, plugin_app: Any
    ) -> V1_3.DocumentList:
        """Strip this generator's documents from ``doc_list`` and handle them.

        Non-framework documents and documents belonging to other types are left
        untouched.  Malformed documents are dropped with a warning.
        """
        kept: list[V1_3.Document] = []
        for doc in doc_list.documents:
            try:
                meta = self._parse(doc.metadata)
            except ValidationError as exc:
                _logger.warning(f"Dropped malformed framework doc id={doc.id!r}: {exc}")
                continue
            if meta is None:
                kept.append(doc)
                continue
            if self.mode == "frontend":
                pending = self._docs.get(doc.id)
                if pending is None or pending.doc_type != meta.doc_type:
                    _logger.warning(
                        f"Dropped unsolicited {meta.doc_type} id={doc.id!r}"
                    )
                    continue
                self.on_frontend_result(doc.id, meta)
            else:
                self.on_backend(doc.id, meta, plugin_app)
        doc_list.documents = kept
        doc_list.count = len(kept)
        return doc_list

    def _parse(self, raw: str | None) -> DocumentMetadata | None:
        """Return typed metadata if ``raw`` belongs to this type, else ``None``."""
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or data.get("doc_type") != self.doc_type:
            return None
        return self.metadata_model.model_validate(data)


class DocumentGeneratorRegistry:
    """Orchestrates multiple :class:`DocumentGenerator` instances.

    The registry is the single object held by :class:`PluginExtension`.  It
    routes ``generate``, ``inject``, ``eject``, ``parse``, and ``clear`` calls
    to the correct per-type generator.
    """

    def __init__(
        self, mode: str, generators: Iterable[type[DocumentGenerator]]
    ) -> None:
        self.mode = mode
        self._generators: dict[str, DocumentGenerator] = {
            g.doc_type: g(mode) for g in generators
        }

    def generate(self, doc_type: Any, doc_id: str, plugin_app: Any) -> DocumentMetadata:
        """Queue a new document of ``doc_type`` (POST /generate)."""
        gen = self._get(doc_type)
        if gen is None:
            raise BadRequest(f"Unknown doc_type {doc_type!r}")
        return gen.generate(doc_id, plugin_app)

    def inject(self, doc_list: V1_3.DocumentList) -> V1_3.DocumentList:
        """Prepend all pending framework documents to ``doc_list``."""
        for gen in self._generators.values():
            gen.inject(doc_list)
        return doc_list

    def eject(self, doc_list: V1_3.DocumentList, plugin_app: Any) -> V1_3.DocumentList:
        """Strip and handle framework documents; return the remainder for signing."""
        for gen in self._generators.values():
            gen.eject(doc_list, plugin_app)
        return doc_list

    def parse(self, raw: str | None) -> DocumentMetadata | None:
        """Return typed metadata for any known ``doc_type``, else ``None``."""
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        gen = self._get(data.get("doc_type"))
        return gen.metadata_model.model_validate(data) if gen else None

    def clear(self, doc_id: str | None = None) -> list[str]:
        """Forget documents across all generators."""
        cleared: list[str] = []
        for gen in self._generators.values():
            cleared.extend(gen.clear(doc_id))
        if cleared:
            _logger.info(f"Cleared {len(cleared)} generated document(s)")
        return cleared

    def _get(self, doc_type: Any) -> DocumentGenerator | None:
        # doc_type comes from untrusted JSON and may be unhashable.
        return self._generators.get(doc_type) if isinstance(doc_type, str) else None
