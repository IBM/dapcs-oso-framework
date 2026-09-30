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
"""Framework-generated documents, carried in ``V1_3.Document.metadata``."""
from __future__ import annotations

import json
from typing import Any, Callable, ClassVar, Iterable

from pydantic import ValidationError
from werkzeug.exceptions import Conflict

from oso.framework.core.logging import get_logger
from oso.framework.data.types import V1_3, DocType, DocumentMetadata

_logger = get_logger("document-generator")


DOC_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"


class DocumentHandler:
    """Base for a document type."""

    doc_type: ClassVar[DocType]
    metadata_model: ClassVar[type[DocumentMetadata]]
    label: ClassVar[str]

    def generate(
        self, gen: DocumentGenerator, key: str, plugin_app: Any = None
    ) -> DocumentMetadata:
        """Create and queue a document of this type."""
        raise NotImplementedError(f"{self.label} documents cannot be generated here")

    def on_incoming(
        self,
        gen: DocumentGenerator,
        key: str,
        meta: DocumentMetadata,
        plugin_app: Any = None,
    ) -> None:
        """React to this type arriving on POST /documents."""


class DocumentGenerator:
    """Queue of framework documents, keyed by ``(DocType, key)``."""

    def __init__(self, mode: str, handlers: Iterable[DocumentHandler]):
        self.mode = mode
        self._handlers = {h.doc_type: h for h in handlers}
        self._queued: dict[tuple[DocType, str], DocumentMetadata] = {}
        self._history: dict[tuple[DocType, str], DocumentMetadata] = {}
        self._resend: set[tuple[DocType, str]] = set()

    def generate(
        self, doc_type: DocType, key: str, plugin_app: Any = None
    ) -> DocumentMetadata:
        """Run the type's ``generate`` handler."""
        return self._handlers[doc_type].generate(self, key, plugin_app)

    def add(
        self,
        key: str,
        metadata: DocumentMetadata,
        *,
        resend: bool = False,
        unique: bool = False,
    ) -> DocumentMetadata:
        """Queue a document for the next GET.

        ``resend`` keeps sending it until removed; ``unique`` rejects it while
        another of its type is pending.
        """
        doc_type = metadata.doc_type
        if unique and any(t is doc_type and k != key for t, k in self._history):
            raise Conflict(
                f"Document already exists for {self._handlers[doc_type].label}"
            )
        self._queued[(doc_type, key)] = metadata
        self._history[(doc_type, key)] = metadata
        if resend:
            self._resend.add((doc_type, key))
        _logger.info(f"Queued {doc_type} key={key}")
        return metadata

    def remove(self, doc_type: DocType, key: str) -> bool:
        """Forget a document. Returns whether it was still queued."""
        self._history.pop((doc_type, key), None)
        self._resend.discard((doc_type, key))
        return self._queued.pop((doc_type, key), None) is not None

    def clear(self, id_: str | None = None) -> list[str]:
        """Forget all generated documents, or only those with id ``id_``."""
        keys = [k for k in self._history if id_ in (None, k[1])]
        for doc_type, key in keys:
            self.remove(doc_type, key)
        _logger.info(f"Cleared {len(keys)} generated document(s)")
        return [key for _, key in keys]

    def generated(self, doc_type: DocType, key: str) -> DocumentMetadata | None:
        """Return a previously added document's metadata, even if already sent."""
        return self._history.get((doc_type, key))

    def inject(self, doc_list: V1_3.DocumentList) -> V1_3.DocumentList:
        """Prepend queued documents and dequeue those not marked ``resend``."""
        for (doc_type, key), meta in self._queued.items():
            doc_list.documents.insert(
                0,
                V1_3.Document(
                    id=key,
                    content="",
                    metadata=meta.model_dump(mode="json"),
                ),
            )
        self._queued = {k: m for k, m in self._queued.items() if k in self._resend}
        doc_list.count = len(doc_list.documents)
        return doc_list

    def handle_incoming(
        self,
        doc_list: V1_3.DocumentList,
        to_isv: Callable[[V1_3.DocumentList], Any],
        plugin_app: Any = None,
    ) -> Any:
        """Pass ISV docs to ``to_isv``, then handle framework docs."""
        kept: list[V1_3.Document] = []
        consumed: list[tuple[DocumentHandler, str, DocumentMetadata]] = []
        for doc in doc_list.documents:
            try:
                meta = self.parse(doc.metadata)
            except ValidationError as exc:
                _logger.warning(f"Malformed framework doc id={doc.id!r}: {exc}")
                if self.mode == "backend":
                    continue
                meta = None
            handler = self._handlers.get(meta.doc_type) if meta else None
            if handler is not None:
                consumed.append((handler, doc.id, meta))  # type: ignore[arg-type]
            else:
                kept.append(doc)
        result = to_isv(V1_3.DocumentList(documents=kept, count=len(kept)))
        for handler, key, meta in consumed:
            handler.on_incoming(self, key, meta, plugin_app)
        return result

    def parse(self, raw: str | None) -> DocumentMetadata | None:
        """Return typed metadata for a framework ``doc_type``, else ``None``."""
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        handler = self._handlers.get(data.get("doc_type"))
        return handler.metadata_model.model_validate(data) if handler else None
