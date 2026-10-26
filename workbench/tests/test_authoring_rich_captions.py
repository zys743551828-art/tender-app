"""Owned caption anchors: source identity and closed OOXML, no converter grants."""

import copy
from xml.etree import ElementTree as ET

import pytest
import test_authoring_generated as generated_cases
import test_authoring_rich_renderer as renderer_cases

from packages.authoring import rich_captions, rich_docx, rich_verification
from packages.authoring.build import W
from packages.domain.runtime import DomainError, sha


@pytest.fixture(name="rich_input")
def caption_input():
    return renderer_cases.rich_input.__wrapped__()


def mutate(source, change):
    def edit(files):
        root = ET.fromstring(files["word/document.xml"])
        change(root)
        files["word/document.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    return generated_cases.repack(source, edit)


def captions(root):
    return [
        item
        for item in root.iter("{" + W + "}bookmarkStart")
        if item.get("{" + W + "}name", "").startswith("cap_")
    ]


def test_caption_identity_stable_across_text_edit_but_distinct_for_repeated_labels(rich_input):
    snapshot, materials, _, pagination, source = rich_input
    expected = rich_captions.entries(snapshot)
    assert len(expected) == 2 and len({item["anchor"] for item in expected}) == 2
    changed = copy.deepcopy(snapshot)
    for block in changed["sections"][0]["content"]:
        block["attrs"]["caption"] = "same repeated 120"
    repeated = rich_captions.entries(changed)
    assert [item["anchor"] for item in repeated] == [item["anchor"] for item in expected]
    assert len({item["text"] for item in repeated}) == 1
    roots = rich_verification.verify_container(source, materials, page_number=True)
    assert [item.get("{" + W + "}name") for item in captions(roots["word/document.xml"])] == [
        item["anchor"] for item in expected
    ]
    assert rich_docx.assemble(snapshot, materials, pagination=pagination) == source
    assert rich_verification.manifest(source, snapshot, materials, pagination=pagination)[
        "caption_entries_digest"
    ] == sha(expected)


@pytest.mark.parametrize(
    "attack", ["foreign_name", "section_id_range", "missing_end", "nested", "unbound"]
)
def test_direct_container_grammar_rejects_caption_escape(rich_input, attack):
    _, materials, _, _, source = rich_input

    def edit(root):
        start = captions(root)[0]
        parent = next(item for item in root.iter() if start in list(item))
        if attack == "foreign_name":
            start.set("{" + W + "}name", "outside")
        elif attack == "section_id_range":
            start.set("{" + W + "}id", "1")
        elif attack == "missing_end":
            parent.remove(parent[-1])
        elif attack == "nested":
            parent.remove(start)
            parent.find("{" + W + "}r").insert(0, start)
        else:
            body = root.find("{" + W + "}body")
            body.remove(parent)
            body.insert(0, parent)

    with pytest.raises(DomainError):
        rich_verification.verify_container(mutate(source, edit), materials, page_number=True)


def test_rehashed_manifest_does_not_admit_old_source_without_caption_anchors(rich_input):
    snapshot, materials, profile, pagination, source = rich_input

    def strip(root):
        ids = {item.get("{" + W + "}id") for item in captions(root)}
        for parent in root.iter():
            for item in list(parent):
                if (
                    item.tag in {"{" + W + "}bookmarkStart", "{" + W + "}bookmarkEnd"}
                    and item.get("{" + W + "}id") in ids
                ):
                    parent.remove(item)

    old = mutate(source, strip)
    with pytest.raises(DomainError):
        rich_verification.verify(
            old,
            snapshot,
            materials,
            rich_verification.manifest(old, snapshot, materials, pagination=pagination),
            profile["identity"]["generator_digest"],
            pagination=pagination,
        )


def test_previous_manifest_protocol_is_not_reinterpreted(rich_input):
    snapshot, materials, profile, pagination, source = rich_input
    manifest = rich_verification.manifest(source, snapshot, materials, pagination=pagination)
    manifest["protocol"] = "authoring-generated-rich/3"
    with pytest.raises(DomainError):
        rich_verification.verify(
            source,
            snapshot,
            materials,
            manifest,
            profile["identity"]["generator_digest"],
            pagination=pagination,
        )
