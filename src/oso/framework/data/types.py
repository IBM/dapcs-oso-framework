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
"""OSO Datatypes.

Version history
---------------
V1_3
    Original schema.  ``Document.metadata`` is an opaque ``str``.

V1_5
    Adds a *structured* ``Document`` where ``metadata`` is a typed
    ``dict`` (serialised to/from JSON).  Introduces first-class
    ``DocumentMetadata`` models, including ``MkRotationMetadata`` and
    ``MkRotationDoneMetadata`` for the HSM master-key rotation flow.
    All other types (``DocumentList``, ``Error``, ``ComponentStatus``)
    are inherited unchanged from V1_3.
"""

import json
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# V1_3 — original schema
# ---------------------------------------------------------------------------

class V1_3:
    """Version 1.3."""

    class Document(BaseModel):
        """Document.

        Attributes
        ----------
        id : str
            Document ID.

        content : str
            Document content.

        metadata : str | None, default=None
            Document metadata — opaque string in V1_3.
        """

        id: str
        content: str
        metadata: str | None = None

        @field_validator(
            "metadata",
            mode="before",
        )
        @classmethod
        def validate_metadata(cls, metadata: str | None) -> str:
            """Fill metadata with empty string, if empty."""
            if metadata is None:
                return ""
            if isinstance(metadata, dict):
                return json.dumps(metadata)
            return metadata

    class DocumentList(BaseModel):
        """Document List.

        Attributes
        ----------
        documents : list[`.Document`], default=[]
            A list of `.Document`s.

        count : int
            A count of documents.
        """

        documents: list["Document"] = Field(default_factory=list)
        count: int

    class Error(BaseModel):
        """Error.

        Attributes
        ----------
        code : str
            A searchable code of the error.

        message : str
            A human readable message about the error.
        """

        code: str
        message: str

    class ComponentStatus(BaseModel):
        """Component Status.

        Attributes
        ----------
        status_code : int
            A HTTP status code.

        status : str
            A human readable message about the status.

        errors : list[`.Error`], default=[]
            A list of errors
        """

        status_code: int
        status: str
        errors: list["Error"] = Field(default_factory=list)
        model_config = ConfigDict(extra="allow")


class V1_5:
    """Version 1.5."""

    class DocumentEvent(BaseModel):
        """Document Event.

        Attributes
        ----------
        eventType : str
            The type of event (e.g. ``DocumentEvent``).

        eventId : str
            A UUID uniquely identifying the event.

        eventTimestamp : datetime
            ISO-8601 timestamp at which the event occurred.

        docId : str
            UUID of the document this event relates to.

        user : str
            Distinguished name or identifier of the actor that triggered the
            event (e.g. ``CN=user1,O=EXAMPLE,C=US`` or ``System``).

        operationType : str
            The operation that occurred (e.g. ``approvedBy``, ``toApproved``).

        queueType : str
            The queue in which the operation took place
            (e.g. ``POST_CONFIRMATION``).

        metadata : str | None, default=None
            JSON-encoded string of additional event metadata.
        """

        eventType: str
        eventId: str
        eventTimestamp: datetime
        docId: str
        user: str
        operationType: str
        queueType: str
        metadata: str | None = None

    class EventList(BaseModel):
        r"""Event List.

        Attributes
        ----------
        events : list[`.DocumentEvent`], default=[]
            A list of `.DocumentEvent`\\ s.

        count : int
            A count of events.
        """

        events: list["DocumentEvent"] = Field(default_factory=list)
        count: int

    class EventResponse(BaseModel):
        """Response body returned by the POST /events endpoint.

        Attributes
        ----------
        hold : list[str], default=[]
            Event IDs that the plugin requests OSO to hold (defer).
            When empty the response serialises as ``{}``.
        """

        hold: list[str] = Field(default_factory=list)

    class DocumentMetadata(BaseModel):
        """Base class for all structured document metadata.

        Every metadata object carries a ``doc_type`` discriminator so
        consumers can deserialise the correct subclass without inspecting
        ``content``.

        Attributes
        ----------
        doc_type : str
            Free-form type tag.  Framework-defined values are declared
            as ``TYPE`` class variables on each concrete subclass.
        """

        model_config = ConfigDict(extra="allow")

        doc_type: str

    class MkRotationMetadata(BaseModel):
        """Metadata attached to a document that signals an HSM master-key rotation.

        The frontend plugin includes one ``V1_5.Document`` with this
        metadata in the document list returned by ``to_oso()``.  The
        framework backend detects it, drives
        :meth:`~oso.framework.plugin.addons.signing_server.SigningServerAddon.rewrap_keys`
        automatically, and returns a ``MkRotationDoneMetadata`` document
        on the next ``to_oso()`` call.

        Attributes
        ----------
        doc_type : Literal["mk_rotation"]
            Discriminator tag (always ``"mk_rotation"``).

        rotation_id : str
            Opaque identifier for this rotation event, chosen by the
            orchestrator.  Echoed back in ``MkRotationDoneMetadata``.
        """

        TYPE: ClassVar[str] = "mk_rotation"

        doc_type: Literal["mk_rotation"] = "mk_rotation"
        rotation_id: str

    class MkRotationDoneMetadata(BaseModel):
        """Backend metadata emitted after a successful master-key rotation rewrap.

        Attributes
        ----------
        doc_type : Literal["mk_rotation_done"]
            Discriminator tag (always ``"mk_rotation_done"``).

        rotation_id : str
            Must equal the ``rotation_id`` from ``MkRotationMetadata``.

        rewrapped_key_ids : list[str]
            Ordered list of key IDs whose blobs were rewrapped.
        """

        TYPE: ClassVar[str] = "mk_rotation_done"

        doc_type: Literal["mk_rotation_done"] = "mk_rotation_done"
        rotation_id: str
        rewrapped_key_ids: list[str]

    class Document(BaseModel):
        """V1_5 Document — metadata is a structured dict.

        Attributes
        ----------
        id : str
            Document ID.

        content : str
            Document content (opaque, ISV-defined serialisation).

        metadata : dict[str, Any], default={}
            Structured metadata.  The ``doc_type`` key identifies the
            shape; use the ``*Metadata`` inner classes of ``V1_5`` to
            serialise / deserialise.
        """

        id: str
        content: str
        metadata: dict[str, Any] = Field(default_factory=dict)

        @field_validator("metadata", mode="before")
        @classmethod
        def _coerce_metadata(cls, v: Any) -> dict[str, Any]:
            """Accept a JSON string, a dict, or None."""
            if v is None:
                return {}
            if isinstance(v, str):
                if v == "":
                    return {}
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, dict):
                        return parsed
                    raise ValueError(
                        f"metadata JSON must be an object, got {type(parsed).__name__}"
                    )
                except json.JSONDecodeError as exc:
                    raise ValueError(f"metadata is not valid JSON: {exc}") from exc
            if isinstance(v, dict):
                return v
            raise ValueError(
                f"metadata must be a dict or a JSON string, got {type(v).__name__}"
            )

        # Convenience helpers

        @classmethod
        def with_metadata(
            cls,
            id: str,
            content: str,
            metadata: "V1_5.DocumentMetadata",
        ) -> "V1_5.Document":
            """Construct a ``V1_5.Document`` from a typed metadata object.

            Parameters
            ----------
            id : str
            content : str
            metadata : V1_5.DocumentMetadata
                Any ``DocumentMetadata`` subclass instance.

            Returns
            -------
            V1_5.Document
            """
            return cls(
                id=id,
                content=content,
                metadata=metadata.model_dump(),
            )

        def get_metadata_type(self) -> str | None:
            """Return the ``doc_type`` tag from metadata, or ``None``."""
            return self.metadata.get("doc_type")

        def is_mk_rotation(self) -> bool:
            """Return ``True`` if this document carries an mk_rotation signal."""
            return self.get_metadata_type() == V1_5.MkRotationMetadata.TYPE

        def is_mk_rotation_done(self) -> bool:
            """Return ``True`` if this document carries an mk_rotation_done signal."""
            return self.get_metadata_type() == V1_5.MkRotationDoneMetadata.TYPE

        def parse_mk_rotation_metadata(self) -> "V1_5.MkRotationMetadata":
            """Deserialise the metadata as ``MkRotationMetadata``.

            Raises
            ------
            pydantic.ValidationError
                If metadata does not conform to ``MkRotationMetadata``.
            """
            return V1_5.MkRotationMetadata.model_validate(self.metadata)

        def parse_mk_rotation_done_metadata(self) -> "V1_5.MkRotationDoneMetadata":
            """Deserialise the metadata as ``MkRotationDoneMetadata``.

            Raises
            ------
            pydantic.ValidationError
                If metadata does not conform to ``MkRotationDoneMetadata``.
            """
            return V1_5.MkRotationDoneMetadata.model_validate(self.metadata)

    class GeneratedDocumentList(BaseModel):
        """V1_5 Document List.

        Defined outside V1_5 so Pydantic can resolve ``V1_5.Document`` at
        class-body evaluation time.

        Attributes
        ----------
        documents : list[V1_5.Document], default=[]
        count : int
        """

        documents: list[V1_5.Document] = Field(default_factory=list)
        count: int


# Define latest
Document = V1_3.Document
DocumentList = V1_3.DocumentList
Error = V1_3.Error
ComponentStatus = V1_3.ComponentStatus
DocumentEvent = V1_5.DocumentEvent
EventList = V1_5.EventList
EventResponse = V1_5.EventResponse
DocumentMetadata = V1_5.DocumentMetadata
MkRotationMetadata = V1_5.MkRotationMetadata
MkRotationDoneMetadata = V1_5.MkRotationDoneMetadata
MkRotationDocument = V1_5.MkRotationMetadata          # type: ignore[assignment]
MkRotationDoneDocument = V1_5.MkRotationDoneMetadata  # type: ignore[assignment]
GeneratedDocumentList = V1_5.GeneratedDocumentList
