"""Pure candidate/provenance boundaries; actual bytes come from synthetic OOXML."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from test_authoring_docx_import_parser import (
    heading,
    image_package,
    image_paragraph,
    merged_table,
    paragraph,
)

from packages.authoring import docx_import_contracts as contracts
from packages.authoring import docx_import_parser as parser
from packages.authoring import docx_import_service as service
from packages.authoring import docx_import_sources as sources
from packages.domain.runtime import DomainError, sha
from packages.rag.indexing import original_source_id


def source_context(digest, size):
    document, file, upload, operation, binding = (str(uuid4()) for _ in range(5))
    source = str(original_source_id(UUID(document)))
    instant = "2026-01-01T00:00:00+00:00"
    intake = sha({"schema": "word-intake-inspection/1"})
    return {
        "source": {
            "document_version_id": document,
            "digest": digest,
            "byte_size": size,
            "media_type": sources.DOCX,
            "filename": "synthetic-private-original.docx",
            "role": "body",
            "file_id": file,
            "file_revision": 1,
            "intake_digest": intake,
        },
        "source_id": source,
        "receipt": {
            "upload_id": upload,
            "verify_operation_id": operation,
            "inspection_digest": intake,
            "binding_id": binding,
        },
        "obtained_at": instant,
        "locator_digest": sha(b"private-original-location"),
        "authority": [
            {
                "source_id": source,
                "ancestor_id": source,
                "kind": "document",
                "policy_class": "prebid_content",
                "known_at": instant,
                "digest": digest,
                "revision": 2,
                "status": "published",
                "valid_from": instant,
                "valid_until": None,
            }
        ],
    }


@pytest.fixture
def candidate(monkeypatch):
    data = image_package(
        heading("进口章节")
        + paragraph("准确文字 120 天")
        + merged_table()
        + heading("子章节", 2)
        + image_paragraph()
    )
    parsed = parser.parse_docx(data)
    assert parsed["can_apply"], parsed["issues"]
    identity, bid, draft, actor, command, snapshot = (uuid4() for _ in range(6))
    objects = {}
    monkeypatch.setattr(
        service.storage, "put", lambda key, body, media: objects.__setitem__(key, body)
    )
    monkeypatch.setattr(service.storage, "get", lambda key: objects[key])
    staged = service.stage_images(bid, identity, parsed)
    public = parser.public_result(parsed)
    source = source_context(sha(data), len(data))
    body = {
        "source_document_version_id": source["source"]["document_version_id"],
        "source_digest": sha(data),
        "source_byte_size": len(data),
        "base_draft_revision": 1,
        "method_digest": sha(public["method"]),
        "reason": "合成明确导入",
    }
    condition = service.draft_etag(draft, 1)
    manifest = {
        "protocol": service.PROTOCOL,
        "candidate_id": str(identity),
        "bid_id": str(bid),
        "draft_id": str(draft),
        "source_context": source,
        "target": {
            "base_draft_revision": 1,
            "base_snapshot_id": str(snapshot),
            "before_digest": sha({}),
            "node_count": 0,
            "context": {},
            "authority": {},
            "existing_sections": [],
        },
        "method_digest": body["method_digest"],
        "parsed": public,
        "sections": service.planned_sections(identity, public),
        "staged_images": staged,
        "reason": body["reason"],
        "preparation": {
            "command_id": str(command),
            "actor_id": str(actor),
            "idempotency_key": "unit-original-key",
            "request_digest": sha(
                {"body": service.request_scope(bid, draft, body), "if_match": condition}
            ),
            "request": body,
            "if_match": condition,
        },
    }
    row = {
        "id": identity,
        "bid_id": bid,
        "draft_id": draft,
        "source_document_version_id": UUID(body["source_document_version_id"]),
        "base_draft_revision": 1,
        "base_snapshot_id": snapshot,
        "command_id": command,
        "created_by": actor,
        "created_at": datetime.now(timezone.utc),
        "manifest": manifest,
        "digest": sha(manifest),
        "resolution": None,
    }
    return row, objects


def test_preview_has_exact_mapping_without_private_objects_and_node_ids_are_isolated(candidate):
    row, objects = candidate
    view = service.view(row)
    contracts.validate("AuthoringWordImportCandidate", view)
    assert "object_key" not in str(view) and "original_bytes" not in str(view)
    assert (
        len(view["sections"]) == 2
        and view["sections"][1]["parent_id"] == view["sections"][0]["section_id"]
    )
    asset = view["images"][0]
    picture = next(
        node for node in view["sections"][1]["content"]["content"] if node["type"] == "image"
    )
    assert picture["attrs"]["asset_id"] == asset["key"]
    assert any(item["node_id"] == picture["attrs"]["id"] for item in view["mapping"])
    for item in view["mapping"]:
        if item["kind"] == "section_title":
            assert item["node_id"] == next(
                s["section_id"] for s in view["sections"] if s["key"] == item["section_key"]
            )
    another = service.planned_sections(uuid4(), row["manifest"]["parsed"])
    assert another[0]["section_id"] != view["sections"][0]["section_id"]
    assert (
        another[0]["content"]["content"][0]["attrs"]["id"]
        != view["sections"][0]["content"]["content"][0]["attrs"]["id"]
    )
    service.verify_staged(row["manifest"])
    descriptor = row["manifest"]["staged_images"][0]["normalized"]
    objects[descriptor["object_key"]] += b"corruption"
    with pytest.raises(DomainError) as caught:
        service.verify_staged(row["manifest"])
    assert caught.value.code == "AUTHORING_WORD_IMPORT_IMAGE_CHANGED"


@pytest.mark.parametrize("change", ["parser", "planned", "image", "location"])
def test_candidate_rejects_independently_rehashed_mismatched_content(candidate, change):
    row, _ = candidate
    row = deepcopy(row)
    manifest = row["manifest"]
    if change == "parser":
        manifest["parsed"]["sections"][0]["title"] += "不同"
    elif change == "planned":
        manifest["sections"][0]["title"] += "不同"
    elif change == "image":
        manifest["staged_images"][0]["normalized"]["digest"] = "0" * 64
    else:
        manifest["staged_images"][0]["normalized"]["object_key"] = "other-project/image"
    row["digest"] = sha(manifest)
    with pytest.raises(DomainError) as caught:
        service.view(row)
    assert caught.value.code == "AUTHORING_WORD_IMPORT_RECORD_CORRUPT"


def metadata_for(row):
    return {
        "word_import_sources": [
            sources.provenance(
                row["bid_id"], row["draft_id"], row["id"], row["digest"], row["manifest"]
            )
        ]
    }


def test_copy_delete_restore_keeps_original_immutable_proof_and_actual_active_sources(candidate):
    row, _ = candidate
    metadata = metadata_for(row)
    original = metadata["word_import_sources"][0]["section_ids"][0]
    first, second, unrelated = (str(uuid4()) for _ in range(3))
    copied = sources.extend_import_copies(metadata, {first: original, unrelated: str(uuid4())})
    copied = sources.extend_import_copies(copied, {second: first})
    source = row["manifest"]["source_context"]["source_id"]
    assert copied["word_import_sources"] == metadata["word_import_sources"]
    assert "word_import_copies" not in metadata
    assert len(copied["word_import_copies"]) == 2
    assert sources.import_source_ids(copied, section_ids={second}) == [source]
    assert sources.import_source_ids(copied, section_ids={unrelated}) == []
    assert sources.import_source_ids(copied, section_ids={original}) == [source]


@pytest.mark.parametrize(
    "fault", ["cycle", "duplicate", "self", "bad_uuid", "unknown_field", "source_shape"]
)
def test_malformed_inactive_proof_or_copy_graph_never_silently_disappears(candidate, fault):
    row, _ = candidate
    metadata = metadata_for(row)
    first, second = (str(uuid4()) for _ in range(2))
    copies = [{"source_section_id": first, "target_section_id": second}]
    if fault == "cycle":
        copies.append({"source_section_id": second, "target_section_id": first})
    elif fault == "duplicate":
        copies.append(dict(copies[0]))
    elif fault == "self":
        copies[0]["source_section_id"] = second
    elif fault == "bad_uuid":
        copies[0]["source_section_id"] = "invalid"
    elif fault == "unknown_field":
        copies[0]["ignored"] = True
    else:
        proof = metadata["word_import_sources"][0]
        proof["source_context"]["authority"] = []
        proof["proof_digest"] = sha({k: v for k, v in proof.items() if k != "proof_digest"})
    metadata["word_import_copies"] = copies
    with pytest.raises(DomainError):
        sources.import_source_ids(metadata, section_ids=[])


def test_imported_image_keeps_its_source_without_any_imported_chapter(candidate, monkeypatch):
    row, _ = candidate
    context = row["manifest"]["source_context"]
    proof = {
        "input_origin": "external_docx_embedded_raster",
        "word_import_source": sources.image_source(
            row["id"], row["bid_id"], row["manifest"], "word/media/figure.png"
        ),
    }
    assert sources.image_import_source_ids(proof) == [context["source_id"]]
    assert sources.image_import_source_ids({"input_origin": "direct_upload"}) == []
    observed = []

    def captured(_c, _bid, _doc, *, lock_sources):
        observed.append(lock_sources)
        return deepcopy(context), {}

    monkeypatch.setattr(sources, "capture", captured)
    assert sources.assert_image_import_source(None, row["bid_id"], proof, lock_sources=False)[
        "direct_source_ids"
    ] == [context["source_id"]]
    assert observed == [False]
    with pytest.raises(DomainError):
        sources.assert_image_import_source(None, uuid4(), proof)
    for corrupt in (
        {"input_origin": "external_docx_embedded_raster"},
        proof | {"word_import_source": None},
    ):
        with pytest.raises(DomainError):
            sources.image_import_source_ids(corrupt)
    changed = deepcopy(context)
    changed["authority"][0]["revision"] += 1
    monkeypatch.setattr(sources, "capture", lambda *_a, **_kw: (changed, {}))
    with pytest.raises(DomainError):
        sources.assert_image_import_source(None, row["bid_id"], proof)


@pytest.mark.parametrize(
    "field,value",
    [
        ("reason", "bad\u0000text"),
        ("reason", "bad\ud800text"),
        ("reason", "   "),
        ("source_byte_size", float("nan")),
        ("source_byte_size", True),
        ("base_draft_revision", -1),
        ("unknown", 1),
    ],
)
def test_prepare_rejects_ambiguous_or_unstorable_requests(candidate, field, value):
    row, _ = candidate
    request = deepcopy(row["manifest"]["preparation"]["request"])
    request[field] = value
    with pytest.raises(DomainError) as caught:
        contracts.validate("AuthoringWordImportPrepareRequest", request)
    assert caught.value.code == "AUTHORING_WORD_IMPORT_INVALID"
