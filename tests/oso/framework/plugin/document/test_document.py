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
from werkzeug.exceptions import BadRequest, Conflict

from oso.framework.data.types import V1_3
from oso.framework.plugin.document import (
    DocumentGenerator,
    DocumentHandler,
    DocumentMetadata,
)
from oso.framework.plugin.document.mk_rotation import (
    MK_ROTATION,
    MkRotation,
    MkRotationMetadata,
)

HANDLERS = (MkRotation(),)

BAD = '{"doc_type": "mk_rotation", "rewrapped_key_ids": "x"}'


def _docs(*docs: V1_3.Document) -> V1_3.DocumentList:
    return V1_3.DocumentList(documents=list(docs), count=len(docs))


def _ids(doc_list: V1_3.DocumentList) -> list[str]:
    return [d.id for d in doc_list.documents]


def _handle(gen: DocumentGenerator, doc_list: V1_3.DocumentList, plugin=None):
    """Run eject; return the ids left for to_isv."""
    return _ids(gen.eject(doc_list, plugin))


def _meta_doc(rid: str, **fields) -> V1_3.Document:
    meta = MkRotationMetadata(**fields).model_dump(mode="json")
    return V1_3.Document(id=rid, content="", metadata=meta)


def _plugin(key_ids: list[str]) -> MagicMock:
    plugin = MagicMock()
    plugin.rewrap.return_value = key_ids
    return plugin


def _rotate(be: DocumentGenerator, rid: str, plugin) -> dict:
    """Deliver a rotation request to the backend; return the queued reply."""
    _handle(be, _docs(_meta_doc(rid)), plugin)
    return json.loads(be.inject(_docs()).documents[0].metadata)


@pytest.fixture
def fe() -> DocumentGenerator:
    return DocumentGenerator("frontend", HANDLERS)


@pytest.fixture
def be() -> DocumentGenerator:
    return DocumentGenerator("backend", HANDLERS)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


def test_metadata_parse(fe: DocumentGenerator):
    parse = fe.parse
    assert parse(None) is None
    assert parse("") is None
    assert parse("not json") is None
    assert parse('{"doc_type": "isv_thing"}') is None
    assert isinstance(parse(_meta_doc("r").metadata), MkRotationMetadata)
    with pytest.raises(ValidationError):
        parse(BAD)


def test_generate_unknown_type(fe: DocumentGenerator):
    for doc_type in ("nope", None):
        with pytest.raises(BadRequest):
            fe.generate(doc_type, "k", None)
    with pytest.raises(TypeError):
        DocumentHandler()  # abstract


def test_inject_keeps_queue_order(fe: DocumentGenerator):
    fe.add("a", MkRotationMetadata())
    fe.add("b", DocumentMetadata(doc_type="other"))
    assert _ids(fe.inject(_docs(V1_3.Document(id="d", content="x")))) == [
        "a",
        "b",
        "d",
    ]


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
    fe.generate(MK_ROTATION, "r1", None)
    injected = fe.inject(_docs(V1_3.Document(id="d", content="x")))
    assert _ids(injected) == ["r1", "d"]
    assert json.loads(injected.documents[0].metadata) == {
        "doc_type": "mk_rotation",
        "status": None,
        "rewrapped_key_ids": None,
        "error": None,
    }
    assert _ids(fe.inject(_docs())) == ["r1"]  # re-sent while pending

    done = _meta_doc("r1", status="success", rewrapped_key_ids=[])
    assert _handle(fe, _docs(done, V1_3.Document(id="d", content="x"))) == ["d"]
    assert fe.get("r1") is None
    assert fe.inject(_docs()).count == 0


def test_frontend_failed_done_ends_rotation(fe: DocumentGenerator):
    fe.generate(MK_ROTATION, "r1", None)
    failed = _meta_doc("r1", status="error", rewrapped_key_ids=[], error="hsm down")
    assert _handle(fe, _docs(failed)) == []
    assert fe.inject(_docs()).count == 0
    fe.generate(MK_ROTATION, "r2", None)  # operator retries


def test_duplicate_rotation_blocked_until_acknowledged(fe: DocumentGenerator):
    fe.generate(MK_ROTATION, "a", None)
    fe.inject(_docs())  # already sent, still blocks
    fe.generate(MK_ROTATION, "a", None)  # same rotation is idempotent
    with pytest.raises(Conflict, match="already pending"):
        fe.generate(MK_ROTATION, "b", None)
    _handle(fe, _docs(_meta_doc("a", status="success")))
    fe.generate(MK_ROTATION, "b", None)


def test_frontend_ignores_unknown_and_drops_malformed_done(fe: DocumentGenerator):
    fe.generate(MK_ROTATION, "keep", None)
    docs = _docs(
        _meta_doc("other", status="success"),
        V1_3.Document(id="bad", content="", metadata=BAD),
        V1_3.Document(id="d", content="x"),
    )
    assert _handle(fe, docs) == ["d"]
    assert fe.get("keep") is not None


def test_frontend_handles_only_pending_ids(fe: DocumentGenerator, monkeypatch):
    on_incoming = MagicMock()
    monkeypatch.setattr(MkRotation, "on_incoming", on_incoming)
    fe.generate(MK_ROTATION, "r1", None)
    _handle(fe, _docs(_meta_doc("other", status="success")))
    on_incoming.assert_not_called()
    _handle(fe, _docs(_meta_doc("r1", status="success")))
    on_incoming.assert_called_once()


# ---------------------------------------------------------------------------
# MkRotation (backend)
# ---------------------------------------------------------------------------


def test_backend_rewrap_once_per_rotation(be: DocumentGenerator):
    plugin = _plugin(["k1", "k2"])
    assert _rotate(be, "r1", plugin) == {
        "doc_type": "mk_rotation",
        "status": "success",
        "rewrapped_key_ids": ["k1", "k2"],
        "error": None,
    }
    assert be.inject(_docs()).count == 0  # sent once

    # Re-sent request re-queues the result without rewrapping again.
    assert _rotate(be, "r1", plugin)["rewrapped_key_ids"] == ["k1", "k2"]
    plugin.rewrap.assert_called_once_with(rotation_id="r1")


def test_backend_without_rewrap_hook_fails(be: DocumentGenerator):
    reply = _rotate(be, "r1", object())
    assert reply["status"] == "error"
    assert reply["error"].startswith("AttributeError")


def test_backend_strips_rotation_docs_and_rewraps(be: DocumentGenerator):
    plugin = _plugin(["k1"])
    docs = _docs(_meta_doc("r1"), _meta_doc("r2"), V1_3.Document(id="d", content="x"))
    assert _handle(be, docs, plugin) == ["d"]
    assert plugin.rewrap.call_count == 2
    assert _ids(be.inject(_docs())) == ["r1", "r2"]


def test_backend_rewrap_failure_reported_then_retried(be: DocumentGenerator):
    plugin = MagicMock()
    plugin.rewrap.side_effect = RuntimeError("hsm down")
    failed = _rotate(be, "r", plugin)
    assert (failed["status"], failed["error"], failed["rewrapped_key_ids"]) == (
        "error",
        "RuntimeError: hsm down",
        [],
    )

    plugin.rewrap.side_effect = None
    plugin.rewrap.return_value = ["k1"]
    done = _rotate(be, "r", plugin)
    assert (done["status"], done["error"], done["rewrapped_key_ids"]) == (
        "success",
        None,
        ["k1"],
    )
    assert plugin.rewrap.call_count == 2


def test_backend_drops_malformed_framework_doc(be: DocumentGenerator):
    docs = _docs(
        V1_3.Document(id="bad", content="", metadata=BAD),
        V1_3.Document(id="d", content="x"),
    )
    assert _handle(be, docs) == ["d"]
    assert be.inject(_docs()).count == 0


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_clear_one_and_all(be: DocumentGenerator):
    for rid in ("r1", "r2", "r3"):
        _rotate(be, rid, _plugin([]))
    assert be.clear("r1") == ["r1"]
    assert be.clear("nope") == []
    assert sorted(be.clear()) == ["r2", "r3"]
    assert be.clear() == []


def test_clear_unblocks_stuck_rotation(fe: DocumentGenerator):
    fe.generate(MK_ROTATION, "stuck", None)
    fe.inject(_docs())
    with pytest.raises(Conflict):
        fe.generate(MK_ROTATION, "next", None)
    assert fe.clear("stuck") == ["stuck"]
    fe.generate(MK_ROTATION, "next", None)


def test_non_string_doc_type_is_not_a_framework_doc(fe: DocumentGenerator):
    assert fe.parse(json.dumps({"doc_type": ["mk_rotation"]})) is None
    with pytest.raises(BadRequest):
        fe.generate(["mk_rotation"], "r1", None)
