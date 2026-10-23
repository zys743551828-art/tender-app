"""Import provenance joins the existing model/source fence without fake citations."""

from copy import deepcopy
from uuid import UUID

import pytest

from packages.authoring import docx_import_sources, package_outputs, section_sources
from packages.authoring.content import empty_content
from packages.domain.runtime import DomainError


def uid(value):
    return str(UUID(int=value))


@pytest.fixture
def port(monkeypatch):
    seen = {"identities": None, "import_checks": [], "asset_checks": []}

    def authority(_c, refs):
        seen["identities"] = sorted(r["source_id"] for r in refs)
        return [{"source_id": identity} for identity in seen["identities"]]

    monkeypatch.setattr(section_sources, "source_authority_manifest", authority)
    monkeypatch.setattr(section_sources.rich_snapshots, "identities", lambda _: [])
    return seen


def test_text_without_imports_keeps_its_existing_source_manifest(port):
    value = empty_content("原正文", 0)
    ref = {"source_id": uid(10)}
    value["attrs"]["source_refs"] = [ref]
    before = deepcopy(value)
    result = section_sources.authority(
        None, uid(1), uid(2), uid(3), value, additional_refs=[ref], extension=None
    )
    assert result == [{"source_id": uid(10)}]
    assert value == before


def test_selected_imported_chapter_adds_original_authority_without_inventing_refs(
    port, monkeypatch
):
    value = empty_content("导入正文", 0)
    metadata = {"word_import_sources": [{"controlled": "immutable proof"}]}

    def imported(c, bid, actual, *, section_ids):
        assert c is None and bid == uid(1) and actual == metadata
        assert section_ids == [uid(3)]
        return {"direct_source_ids": [uid(10)]}

    monkeypatch.setattr(docx_import_sources, "assert_import_sources", imported)
    result = section_sources.authority(
        None,
        uid(1),
        uid(2),
        uid(3),
        value,
        additional_refs=[{"source_id": uid(11)}],
        extension={"metadata": metadata},
    )
    assert result == [{"source_id": uid(10)}, {"source_id": uid(11)}]
    assert value["attrs"]["source_refs"] == []


def test_reused_import_image_keeps_original_authority_in_an_unrelated_chapter(port, monkeypatch):
    value = empty_content("手工章节", 0)
    image_identity = (uid(20), 1, uid(21))
    proof = {"word_import_source": {"controlled": "immutable image proof"}}
    monkeypatch.setattr(section_sources.rich_snapshots, "identities", lambda _: [image_identity])

    def assets(_c, bid, identities):
        assert bid == uid(1) and identities == [image_identity]
        port["asset_checks"].append(True)
        return [{"normalization_proof": proof, "source_refs": [{"source_id": uid(11)}]}]

    def imported(actual):
        assert actual == proof
        return [uid(10)]

    monkeypatch.setattr(section_sources.rich_assets, "freeze_assets", assets)
    monkeypatch.setattr(docx_import_sources, "image_import_source_ids", imported)
    result = section_sources.authority(
        None, uid(1), uid(2), uid(3), value, extension={"metadata": {}}
    )
    assert result == [{"source_id": uid(10)}, {"source_id": uid(11)}]
    assert port["asset_checks"] == [True]


def test_failed_original_guard_never_emits_a_model_authority(port, monkeypatch):
    def withdrawn(*_, **__):
        raise DomainError("SOURCE_WITHDRAWN", "原件已撤回", 409)

    monkeypatch.setattr(docx_import_sources, "assert_import_sources", withdrawn)
    with pytest.raises(DomainError, match="原件已撤回"):
        section_sources.authority(
            None,
            uid(1),
            uid(2),
            uid(3),
            empty_content("导入正文", 0),
            extension={"metadata": {"word_import_sources": []}},
        )
    assert port["identities"] is None


def test_generated_output_lineage_keeps_imported_chapters_and_reused_images(monkeypatch):
    metadata = {"word_import_sources": [{"controlled": "immutable proof"}]}

    def chapters(actual, *, section_ids):
        assert actual == metadata and section_ids == [uid(3)]
        return [uid(10)]

    def images(proof):
        assert proof == {"controlled": "image proof"}
        return [uid(10), uid(11)]

    monkeypatch.setattr(docx_import_sources, "import_source_ids", chapters)
    monkeypatch.setattr(docx_import_sources, "image_import_source_ids", images)
    snapshot = {
        "authoring_structure": {
            "metadata": metadata,
            "nodes": [
                {"section_id": uid(3), "deleted": False},
                {"section_id": uid(4), "deleted": True},
            ],
        },
        "authoring_images": {"items": [{"normalization_proof": {"controlled": "image proof"}}]},
    }
    assert package_outputs._import_source_ids(snapshot) == [uid(10), uid(11)]
