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

To add a document type, subclass `DocumentMetadata` and `DocumentHandler`, and
register the handler in `oso.framework.plugin.extension.PluginExtension`.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Iterable

from pydantic import BaseModel, ConfigDict, ValidationError
from werkzeug.exceptions import BadRequest, Conflict

from oso.framework.core.logging import get_logger
from oso.framework.data.types import V1_3

_logger = get_logger("document-generator")


class DocumentMetadata(BaseModel):
    """Base for framework document metadata; ``doc_type`` selects the handler."""

    model_config = ConfigDict(extra="allow")
    doc_type: str


class DocumentHandler:
    """Base for a document type."""

    doc_type: ClassVar[str]
    metadata_model: ClassVar[type[DocumentMetadata]]

    def generate(
        self, gen: DocumentGenerator, doc_id: str, plugin_app: Any
    ) -> DocumentMetadata:
        """Create and queue a document of this type (POST /generate)."""
        raise NotImplementedError(f"{type(self).__name__} cannot generate documents")

    def on_incoming(
        self,
        gen: DocumentGenerator,
        doc_id: str,
        meta: DocumentMetadata,
        plugin_app: Any,
    ) -> None:
        """React to this type arriving on POST /documents."""


class DocumentGenerator:
    """Framework documents, keyed by document id.

    Frontend documents are requests: one pending per type, re-sent on every
    GET until removed. Backend documents are replies: sent on the next GET only.
    """

    def __init__(self, mode: str, handlers: Iterable[DocumentHandler]):
        self.mode = mode
        self._handlers = {h.doc_type: h for h in handlers}
        self._docs: dict[str, DocumentMetadata] = {}
        self._outbox: set[str] = set()

    def generate(self, doc_type: Any, doc_id: str, plugin_app: Any) -> DocumentMetadata:
        """Run the type's ``generate`` handler."""
        handler = self._handler(doc_type)
        if handler is None:
            raise BadRequest(f"Unknown doc_type {doc_type!r}")
        return handler.generate(self, doc_id, plugin_app)

    def add(self, doc_id: str, metadata: DocumentMetadata) -> DocumentMetadata:
        """Queue a document for the next GET."""
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
        """Return a previously added document's metadata, even if already sent."""
        return self._docs.get(doc_id)

    def remove(self, doc_id: str) -> None:
        """Forget a document."""
        self._docs.pop(doc_id, None)
        self._outbox.discard(doc_id)

    def clear(self, doc_id: str | None = None) -> list[str]:
        """Forget all generated documents, or only the one with id ``doc_id``."""
        ids = [k for k in self._docs if doc_id in (None, k)]
        for k in ids:
            self.remove(k)
        _logger.info(f"Cleared {len(ids)} generated document(s)")
        return ids

    def inject(self, doc_list: V1_3.DocumentList) -> V1_3.DocumentList:
        """Prepend queued documents; the opposite of ``eject``."""
        doc_list.documents[:0] = [
            V1_3.Document(id=k, content="", metadata=m.model_dump(mode="json"))
            for k, m in self._docs.items()
            if k in self._outbox
        ]
        if self.mode == "backend":
            self._outbox.clear()
        doc_list.count = len(doc_list.documents)
        return doc_list

    def eject(self, doc_list: V1_3.DocumentList, plugin_app: Any) -> V1_3.DocumentList:
        """Remove generated documents and handle them; the opposite of ``inject``."""
        kept: list[V1_3.Document] = []
        for doc in doc_list.documents:
            try:
                meta = self.parse(doc.metadata)
            except ValidationError as exc:
                _logger.warning(f"Dropped malformed framework doc id={doc.id!r}: {exc}")
                continue
            if meta is None:
                kept.append(doc)
                continue
            self._handlers[meta.doc_type].on_incoming(self, doc.id, meta, plugin_app)
        doc_list.documents = kept
        doc_list.count = len(kept)
        return doc_list

    def parse(self, raw: str | None) -> DocumentMetadata | None:
        """Return typed metadata for a framework ``doc_type``, else ``None``."""
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        handler = self._handler(data.get("doc_type"))
        return handler.metadata_model.model_validate(data) if handler else None

    def _handler(self, doc_type: Any) -> DocumentHandler | None:
        # doc_type comes from untrusted JSON and may be unhashable.
        return self._handlers.get(doc_type) if isinstance(doc_type, str) else None
