"""Explicit source policy and independent PDF fixtures, not Word conversion acceptance."""

import copy
from xml.etree import ElementTree as ET

import pytest
import test_authoring_rich as rich_cases
import test_authoring_rich_table_continuations as pages_cases
import test_authoring_rich_table_pdf as cases

from packages.authoring import (
    content,
    generated_renderer,
    rich_content,
    rich_docx,
    rich_renderer,
    rich_repeated_headers,
    rich_table_pdf,
    rich_verification,
)
from packages.authoring.build import W
from packages.domain.runtime import DomainError


def declared():
    block = pages_cases.table(header=True)
    block["attrs"]["pagination"] = copy.deepcopy(rich_content.SCHEMA["table_pagination"])
    return block


def render_pages(block, *, split=2, attack="repeat_header"):
    # Fixture pieces are physical pages, not new source tables with a new policy.
    physical = copy.deepcopy(block)
    physical["attrs"].pop("pagination", None)
    return pages_cases.pages(physical, split=split, attack=attack, repeat_header=attack is not None)


@pytest.mark.parametrize("split", [2, 3])
def test_declared_header_is_verified_as_same_source_row_on_second_page(split):
    block = declared()
    snapshot, docx, roots = cases.source([block])
    manifest = rich_verification.manifest(docx, snapshot, [])
    rich_verification.verify(docx, snapshot, [], manifest, rich_docx.sha(rich_docx.identity()))
    proof = rich_table_pdf.inspect_tables(
        render_pages(block, split=split), snapshot, roots, cases.STYLE
    )
    assert proof["coverage"] == "complete", proof
    matched = proof["tables"][0]
    assert len(matched["cells"]) == 12
    repeated = [c for c in matched["fragments"][1]["cells"] if c.get("repeated_header")]
    assert [c["node_id"] for c in repeated] == [
        c["attrs"]["id"] for c in block["content"][0]["content"]
    ]
    assert all(c["row"] == 0 for c in repeated)
    assert len(matched["fragments"][1]["cells"]) == (5 - split) * 3


@pytest.mark.parametrize(
    "attack",
    [
        None,
        "missing",
        "row_swap",
        "duplicate_row",
        "page_swap",
        "gap",
        "shift",
        "covered",
        "middle",
        "duplicate_fragment",
        "detached_header",
        "leading_image",
    ],
)
def test_declared_policy_does_not_allow_missing_or_misplaced_header(attack):
    block = declared()
    snapshot, _, roots = cases.source([block])
    proof = rich_table_pdf.inspect_tables(
        render_pages(block, attack=attack), snapshot, roots, cases.STYLE
    )
    assert proof["coverage"] == "partial", proof


def test_header_only_first_fragment_is_not_supported():
    block = declared()
    snapshot, _, roots = cases.source([block])
    proof = rich_table_pdf.inspect_tables(
        render_pages(block, split=1), snapshot, roots, cases.STYLE
    )
    assert proof["coverage"] == "partial", proof


@pytest.mark.parametrize(
    "policy",
    [
        None,
        {},
        {"protocol": "authoring-table-pagination/2", "repeat_header_rows": 1},
        {"protocol": "authoring-table-pagination/1", "repeat_header_rows": True},
        {"protocol": "authoring-table-pagination/1", "repeat_header_rows": 2},
        {"protocol": "authoring-table-pagination/1", "repeat_header_rows": 1, "extra": 1},
    ],
)
def test_invalid_declaration_is_rejected(policy):
    block = declared()
    block["attrs"]["pagination"] = policy
    with pytest.raises(DomainError):
        rich_content.validate_content(rich_cases.document(block))


def test_legacy_snapshot_readable_but_cannot_claim_new_policy():
    doc = rich_cases.document(pages_cases.table(header=True))
    content.validate_for_schema(doc, rich_content.LEGACY_SCHEMA_DIGEST)
    doc["content"][0] = declared()
    with pytest.raises(DomainError, match="SECTION_SCHEMA_UNSUPPORTED"):
        content.validate_for_schema(doc, rich_content.LEGACY_SCHEMA_DIGEST)
    content.validate_for_schema(doc, rich_content.SCHEMA_DIGEST)


@pytest.mark.parametrize("mutation", ["header_style", "merged", "list", "one_row", "too_many"])
def test_declared_source_rejects_unsupported_shapes(mutation):
    block = declared()
    cell = block["content"][0]["content"][0]
    if mutation == "header_style":
        cell["attrs"]["header"] = False
    elif mutation == "merged":
        cell["attrs"]["colspan"] = 2
    elif mutation == "list":
        cell["content"][0]["type"] = "orderedList"
    elif mutation == "one_row":
        block["content"] = block["content"][:1]
    else:
        block["content"] *= 4
    with pytest.raises(DomainError):
        rich_content.validate_content(rich_cases.document(block))


def test_full_body_expansion_is_position_bound_and_does_not_mutate_source():
    block = declared()
    snapshot, _, roots = cases.source([block])
    pdf = render_pages(block)
    proof = rich_table_pdf.inspect_tables(pdf, snapshot, roots, cases.STYLE)
    assert proof["coverage"] == "complete"
    # Isolate body equality from headings/TOC/footer fixture requirements.
    root = ET.Element("{" + W + "}document")
    root.append(copy.deepcopy(next(roots["word/document.xml"].iter("{" + W + "}tbl"))))
    roots = roots | {"word/document.xml": root}
    original = ET.tostring(root)
    expanded = rich_repeated_headers.body_roots(roots, proof)
    style = cases.STYLE | {
        "header_text": "",
        "footer_text": "",
        "page_number": False,
        "font_size_halfpoints": 20,
    }
    prepared = {"roots": roots, "config": style}
    assert (
        "AUTHORING_COMPLETE_BODY_TEXT_UNVERIFIED"
        in generated_renderer.inspect_pdf(pdf, prepared)["gaps"]
    )
    assert (
        "AUTHORING_COMPLETE_BODY_TEXT_UNVERIFIED"
        not in generated_renderer.inspect_pdf(pdf, prepared | {"roots": expanded})["gaps"]
    )
    integrated = rich_renderer.inspect_pdf(
        pdf, prepared | {"snapshot": snapshot, "materials": [], "pagination": None}
    )
    assert "AUTHORING_COMPLETE_BODY_TEXT_UNVERIFIED" not in integrated["gaps"]
    assert integrated["gaps"]  # Missing navigation remains a genuine gap in this isolated fixture.
    assert integrated["frozen_source_body_digest"] != integrated["expected_body_digest"]
    assert ET.tostring(root) == original
    assert rich_repeated_headers.body_roots(roots, proof | {"coverage": "partial"}) is roots
    wrong = copy.deepcopy(expanded)
    repeated = list(wrong["word/document.xml"].iter("{" + W + "}tr"))[2]
    table = next(wrong["word/document.xml"].iter("{" + W + "}tbl"))
    table.remove(repeated)
    table.append(repeated)
    assert (
        "AUTHORING_COMPLETE_BODY_TEXT_UNVERIFIED"
        in generated_renderer.inspect_pdf(pdf, prepared | {"roots": wrong})["gaps"]
    )


@pytest.mark.parametrize(
    "attack", ["second_row", "false_value", "duplicate", "foreign_parent", "undeclared"]
)
def test_admission_rejects_forged_or_misplaced_repeat_markers(attack):
    from test_authoring_rich_captions import mutate

    block = declared()
    if attack == "undeclared":
        block["attrs"].pop("pagination")
    snapshot, docx, _ = cases.source([block])
    manifest = rich_verification.manifest(docx, snapshot, [])

    def change(root):
        rows = list(root.iter("{" + W + "}tr"))
        if attack == "undeclared":
            prop = ET.Element("{" + W + "}trPr")
            ET.SubElement(prop, "{" + W + "}tblHeader", {"{" + W + "}val": "1"})
            rows[0].insert(0, prop)
        else:
            prop = rows[0][0]
            if attack == "second_row":
                rows[0].remove(prop)
                rows[1].insert(0, prop)
            elif attack == "false_value":
                prop[0].set("{" + W + "}val", "0")
            elif attack == "duplicate":
                rows[0].insert(0, copy.deepcopy(prop))
            else:
                rows[0].remove(prop)
                rows[0][0].append(prop)

    forged = mutate(docx, change)
    if attack != "undeclared":
        with pytest.raises(DomainError):
            rich_verification.verify_container(forged, [], page_number=True)
    with pytest.raises(DomainError):
        rich_verification.verify(
            forged, snapshot, [], manifest, rich_docx.sha(rich_docx.identity())
        )


def test_declared_table_on_one_page_needs_no_physical_repetition():
    block = declared()
    snapshot, _, roots = cases.source([block])
    proof = rich_table_pdf.inspect_tables(cases.pdf(block), snapshot, roots, cases.STYLE)
    assert proof["coverage"] == "complete", proof
    assert "fragments" not in proof["tables"][0]
    assert generated_renderer.expected_body(
        rich_repeated_headers.body_roots(roots, proof)
    ) == generated_renderer.expected_body(roots)
