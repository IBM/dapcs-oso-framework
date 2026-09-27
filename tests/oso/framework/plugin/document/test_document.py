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
"""Tests for DocumentGenerator and the MK rotation flow."""

import json

from unittest.mock import MagicMock

import pytest

from pydantic import ValidationError
from werkzeug.exceptions import Conflict

from oso.framework.data.types import V1_3
from oso.framework.plugin.document import DocType, DocumentGenerator, DocumentHandler
from oso.framework.plugin.document.mk_rotation import (
    MkRotation,
    MkRotationDone,
    MkRotationDoneMetadata,
    MkRotationMetadata,
)

HANDLERS = (MkRotation(), MkRotationDone())


def _docs(*docs: V1_3.Document) -> V1_3.DocumentList:
    return V1_3.DocumentList(documents=list(docs), count=len(docs))


def _ids(doc_list: V1_3.DocumentList) -> list[str]:
    return [d.id for d in doc_list.documents]


def _handle(
    gen: DocumentGenerator, doc_list: V1_3.DocumentList, plugin=None
) -> list[str]:
    """Run handle_incoming; return the ids passed to to_isv."""
    return gen.handle_incoming(doc_list, _ids, plugin)


def _rotation_doc(rid: str) -> V1_3.Document:
    meta = MkRotationMetadata(rotation_id=rid)
    return V1_3.Document(
        id=f"mk_rotation_{rid}", content="", metadata=meta.model_dump(mode="json")
    )


def _done_doc(rid: str) -> V1_3.Document:
    meta = MkRotationDoneMetadata(rotation_id=rid, rewrapped_key_ids=[])
    return V1_3.Document(
        id=f"mk_rotation_done_{rid}", content="", metadata=meta.model_dump(mode="json")
    )


def _plugin(key_ids: list[str]) -> MagicMock:
    plugin = MagicMock()
    plugin.rewrap.return_value = MagicMock(rewrapped_key_ids=key_ids)
    return plugin


@pytest.fixture
def fe() -> DocumentGenerator:
    return DocumentGenerator("frontend", HANDLERS)


@pytest.fixture
def be() -> DocumentGenerator:
    return DocumentGenerator("backend", HANDLERS)


# ---------------------------------------------------------------------------
# Schema / generator
# ---------------------------------------------------------------------------


def test_every_doc_type_has_a_handler():
    assert {h.doc_type for h in HANDLERS} == set(DocType)


def test_metadata_parse(fe: DocumentGenerator):
    parse = fe.parse
    assert parse(None) is None
    assert parse("") is None
    assert parse("not json") is None
    assert parse('{"doc_type": "isv_thing"}') is None
    meta = parse(_rotation_doc("r").metadata)
    assert isinstance(meta, MkRotationMetadata)
    assert meta.rotation_id == "r"
    with pytest.raises(ValidationError):
        parse('{"doc_type": "mk_rotation"}')


def test_base_handler_defaults(fe: DocumentGenerator):
    h = DocumentHandler()
    h.label = "x"
    with pytest.raises(NotImplementedError):
        h.generate(fe, "k")
    assert h.consumed_in is None


def test_empty_inject(fe: DocumentGenerator):
    assert _ids(fe.inject(_docs(V1_3.Document(id="d", content="x")))) == ["d"]


def test_non_framework_docs_pass_through(be: DocumentGenerator):
    docs = _docs(
        V1_3.Document(id="a", content="1"),
        V1_3.Document(id="b", content="2", metadata='{"k": 1}'),
    )
    assert _handle(be, docs) == ["a", "b"]


# ---------------------------------------------------------------------------
# MkRotation (frontend)
# ---------------------------------------------------------------------------


def test_frontend_resends_until_acknowledged(fe: DocumentGenerator):
    fe.generate(DocType.MK_ROTATION, "r1")
    injected = fe.inject(_docs(V1_3.Document(id="d", content="x")))
    assert _ids(injected) == ["mk_rotation_r1", "d"]
    assert json.loads(injected.documents[0].metadata) == {
        "doc_type": "mk_rotation",
        "rotation_id": "r1",
    }
    assert _ids(fe.inject(_docs())) == ["mk_rotation_r1"]  # re-sent while pending

    passed = _handle(fe, _docs(_done_doc("r1"), V1_3.Document(id="d", content="x")))
    assert passed == ["d"]  # done doc stripped
    assert fe.generated(DocType.MK_ROTATION, "r1") is None
    assert fe.inject(_docs()).count == 0


def test_frontend_failed_done_ends_rotation(fe: DocumentGenerator):
    fe.generate(DocType.MK_ROTATION, "r1")
    failed = MkRotationDoneMetadata(
        rotation_id="r1", rewrapped_key_ids=[], error="RuntimeError: hsm down"
    )
    doc = V1_3.Document(id="x", content="", metadata=failed.model_dump(mode="json"))
    assert _handle(fe, _docs(doc)) == []
    assert fe.inject(_docs()).count == 0
    fe.generate(DocType.MK_ROTATION, "r1")  # operator retries the same id


def test_duplicate_rotation_blocked_until_acknowledged(fe: DocumentGenerator):
    fe.generate(DocType.MK_ROTATION, "a")
    fe.inject(_docs())  # already sent, still blocks
    fe.generate(DocType.MK_ROTATION, "a")  # same rotation is idempotent
    with pytest.raises(Conflict, match="Document already exists for MK rotation"):
        fe.generate(DocType.MK_ROTATION, "b")
    _handle(fe, _docs(_done_doc("a")))
    fe.generate(DocType.MK_ROTATION, "b")


def test_frontend_ignores_unknown_and_malformed_done(fe: DocumentGenerator):
    fe.generate(DocType.MK_ROTATION, "keep")
    docs = _docs(
        _done_doc("other"),
        V1_3.Document(
            id="bad", content="", metadata='{"doc_type": "mk_rotation_done"}'
        ),
        V1_3.Document(id="d", content="x"),
    )
    assert _handle(fe, docs) == ["bad", "d"]
    assert fe.generated(DocType.MK_ROTATION, "keep") is not None


# ---------------------------------------------------------------------------
# MkRotationDone (backend)
# ---------------------------------------------------------------------------


def test_backend_rewrap_once_per_rotation(be: DocumentGenerator):
    plugin = _plugin(["k1", "k2"])
    first = be.generate(DocType.MK_ROTATION_DONE, "r1", plugin)
    assert first.rewrapped_key_ids == ["k1", "k2"]
    assert json.loads(be.inject(_docs()).documents[0].metadata) == {
        "doc_type": "mk_rotation_done",
        "rotation_id": "r1",
        "rewrapped_key_ids": ["k1", "k2"],
        "error": None,
    }
    assert be.inject(_docs()).count == 0  # sent once

    # Re-sent signal re-queues the done doc without rewrapping again.
    assert be.generate(DocType.MK_ROTATION_DONE, "r1", plugin) == first
    plugin.rewrap.assert_called_once_with(rotation_id="r1")
    assert _ids(be.inject(_docs())) == ["mk_rotation_done_r1"]


def test_backend_rewrap_without_hook_or_key_ids(be: DocumentGenerator):
    assert be.generate(DocType.MK_ROTATION_DONE, "r1").rewrapped_key_ids == []
    plugin = MagicMock()
    plugin.rewrap.return_value = object()
    assert be.generate(DocType.MK_ROTATION_DONE, "r2", plugin).rewrapped_key_ids == []


def test_backend_strips_rotation_docs_and_rewraps(be: DocumentGenerator):
    plugin = _plugin(["k1"])
    docs = _docs(
        _rotation_doc("r1"), _rotation_doc("r2"), V1_3.Document(id="d", content="x")
    )
    assert _handle(be, docs, plugin) == ["d"]
    assert plugin.rewrap.call_count == 2
    assert sorted(_ids(be.inject(_docs()))) == [
        "mk_rotation_done_r1",
        "mk_rotation_done_r2",
    ]


def test_framework_docs_handled_after_to_isv(be: DocumentGenerator):
    calls: list[str] = []
    plugin = MagicMock()
    plugin.rewrap.side_effect = lambda **_: calls.append("rewrap")
    docs = _docs(_rotation_doc("r"), V1_3.Document(id="d", content="x"))
    be.handle_incoming(docs, lambda dl: calls.append(f"to_isv:{_ids(dl)}"), plugin)
    assert calls == ["to_isv:['d']", "rewrap"]


def test_backend_rewrap_failure_reported_then_retried(be: DocumentGenerator):
    plugin = MagicMock()
    plugin.rewrap.side_effect = RuntimeError("hsm down")
    docs = _docs(_rotation_doc("r"), V1_3.Document(id="d", content="x"))
    assert _handle(be, docs, plugin) == ["d"]
    failed = json.loads(be.inject(_docs()).documents[0].metadata)
    assert failed["error"] == "RuntimeError: hsm down"
    assert failed["rewrapped_key_ids"] == []

    plugin.rewrap.side_effect = None
    plugin.rewrap.return_value = MagicMock(rewrapped_key_ids=["k1"])
    _handle(be, _docs(_rotation_doc("r")), plugin)
    done = json.loads(be.inject(_docs()).documents[0].metadata)
    assert (done["error"], done["rewrapped_key_ids"]) == (None, ["k1"])
    assert plugin.rewrap.call_count == 2


def test_rotation_id_validated():
    with pytest.raises(ValidationError):
        MkRotationMetadata(rotation_id="../etc")


def test_backend_drops_malformed_rotation_doc(be: DocumentGenerator):
    bad = V1_3.Document(id="bad", content="", metadata='{"doc_type": "mk_rotation"}')
    docs = _docs(bad, V1_3.Document(id="d", content="x"))
    assert _handle(be, docs) == ["d"]
    assert be.inject(_docs()).count == 0


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_clear_one_and_all(be: DocumentGenerator):
    for rid in ("r1", "r2", "r3"):
        be.generate(DocType.MK_ROTATION_DONE, rid, _plugin([]))
    assert be.clear("mk_rotation_done_r1") == ["mk_rotation_done_r1"]
    assert be.clear("nope") == []
    assert _ids(be.inject(_docs())) == ["mk_rotation_done_r3", "mk_rotation_done_r2"]
    assert sorted(be.clear()) == ["mk_rotation_done_r2", "mk_rotation_done_r3"]
    assert be.clear() == []


def test_clear_unblocks_stuck_rotation(fe: DocumentGenerator):
    fe.generate(DocType.MK_ROTATION, "stuck")
    fe.inject(_docs())
    with pytest.raises(Conflict):
        fe.generate(DocType.MK_ROTATION, "next")
    assert fe.clear("mk_rotation_stuck") == ["mk_rotation_stuck"]
    fe.generate(DocType.MK_ROTATION, "next")
