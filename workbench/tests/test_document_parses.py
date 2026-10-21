"""Actual local PDF bytes plus isolated fail-closed mechanism checks; no paid model."""

import copy
import io
from contextlib import contextmanager

import pytest
from reportlab.pdfgen import canvas

from apps.worker import document_parse_handlers as handler
from packages.contracts.document_parses_api import validate
from packages.domain import document_parse_policy as policy
from packages.domain.runtime import DomainError, sha
from packages.parsing.physical_pdf import extract


def original():
    out = io.BytesIO()
    page = canvas.Canvas(out, pagesize=(420, 595))
    page.drawString(30, 550, "Standalone exact original; no current body switch.")
    page.showPage()
    page.setPageRotation(90)
    page.drawString(30, 250, "Second actual physical page.")
    page.save()
    return out.getvalue()


def selected(monkeypatch):
    monkeypatch.delenv("PARSING_RUNTIME_TOKEN", raising=False)
    method, parser = policy.method()
    assert parser is None
    return method


def test_real_pdfium_pages_are_read_without_promising_word_or_visual_coverage(monkeypatch):
    method = selected(monkeypatch)
    parsed = policy.normalize(extract(original()), method)
    assert len(parsed["pages"]) == 2
    assert parsed["pages"][1]["rotation"] == 90
    assert "Standalone exact original" in parsed["pages"][0]["blocks"][0]["text_content"]
    assert parsed["coverage"] == "partial"
    assert parsed["gaps"] == ["TEXT_ONLY_TABLES_VISUAL_AND_LAYOUT_UNVERIFIED"]
    assert policy.normalize(parsed, method, frozen=True) == parsed


@pytest.mark.parametrize(
    "change", ["complete", "nan", "ordinal", "digest", "page", "bbox", "gaps", "profile"]
)
def test_unknown_or_inconsistent_result_cannot_be_published(monkeypatch, change):
    method = selected(monkeypatch)
    raw = {
        "parser_digest": method["parser_digest"],
        "config_digest": method["config_digest"],
        "coverage": "partial",
        "gaps": ["visual unverified"],
        "pages": [
            {
                "physical_page": 1,
                "width": 420.125,
                "height": 595.25,
                "rotation": 0,
                "quality": "usable",
                "gaps": [],
                "blocks": [
                    {
                        "ordinal": 0,
                        "kind": "text",
                        "bbox": [30.125, 40.25, 100.5, 120.75],
                        "text_content": "original",
                        "digest": sha(b"original"),
                    }
                ],
            }
        ],
    }
    alterations = {
        "complete": lambda: raw.update(coverage="complete", gaps=[]),
        "nan": lambda: raw["pages"][0].update(width=float("nan")),
        "ordinal": lambda: raw["pages"][0]["blocks"][0].update(ordinal=1),
        "digest": lambda: raw["pages"][0]["blocks"][0].update(text_content="changed"),
        "page": lambda: raw["pages"][0].update(physical_page=2),
        "bbox": lambda: raw["pages"][0]["blocks"][0].update(bbox=[0, 0, 999, 100]),
        "gaps": lambda: raw.update(gaps=""),
        "profile": lambda: raw.update(config_digest="f" * 64),
    }
    alterations[change]()
    with pytest.raises(DomainError):
        policy.normalize(raw, method)


def test_configured_geometry_and_table_structure_remain_exact(monkeypatch):
    method = selected(monkeypatch) | {"mode": "configured_local"}
    table = {
        "bbox": [30.125, 40.25, 100.5, 120.75],
        "rows": [["first", "second"]],
        "cells": [{"row": 0, "col": 0, "row_span": 1, "column_span": 2}],
    }
    raw = {
        "parser_digest": method["parser_digest"],
        "config_digest": method["config_digest"],
        "coverage": "usable",
        "gaps": [],
        "pages": [
            {
                "physical_page": 1,
                "width": 420.125,
                "height": 595.25,
                "rotation": 0,
                "quality": "usable",
                "gaps": [],
                "tables": [table],
                "blocks": [
                    {
                        "ordinal": 0,
                        "kind": "table",
                        "bbox": table["bbox"],
                        "text_content": "first second",
                        "digest": sha(b"first second"),
                        "chapter_path": ["chapter one"],
                        "confidence": 0.975,
                    }
                ],
            }
        ],
    }
    parsed = policy.normalize(raw, method)
    assert parsed["coverage"] == "complete"
    block = parsed["pages"][0]["blocks"][0]
    assert block["bbox"] == table["bbox"] and block["structure"]["tables"] == [table]
    assert block["structure"]["confidence"] == 0.975
    assert policy.normalize(parsed, method, frozen=True) == parsed
    raw["pages"][0]["gaps"] = ["unknown visual"]
    with pytest.raises(DomainError):
        policy.normalize(raw, method)


@pytest.mark.parametrize("location", ["root_gap", "page_gap", "table_cell", "table_key"])
def test_result_strings_reject_nul_before_any_jsonb_publication(monkeypatch, location):
    method = selected(monkeypatch) | {"mode": "configured_local"}
    area = [10, 10, 100, 100]
    table = {"bbox": area, "rows": [["cell"]]}
    raw = {
        "parser_digest": method["parser_digest"],
        "config_digest": method["config_digest"],
        "coverage": "partial",
        "gaps": [],
        "pages": [
            {
                "physical_page": 1,
                "width": 420,
                "height": 595,
                "rotation": 0,
                "quality": "usable",
                "gaps": [],
                "tables": [table],
                "blocks": [
                    {
                        "ordinal": 0,
                        "kind": "table",
                        "bbox": area,
                        "text_content": "cell",
                        "digest": sha(b"cell"),
                    }
                ],
            }
        ],
    }
    if location == "root_gap":
        raw["gaps"] = ["invalid\x00gap"]
    elif location == "page_gap":
        raw["pages"][0]["gaps"] = ["invalid\x00gap"]
    elif location == "table_cell":
        table["rows"][0][0] = "invalid\x00cell"
    else:
        table["invalid\x00key"] = "cell"
    with pytest.raises(DomainError) as error:
        policy.normalize(raw, method)
    assert error.value.code == "DOCUMENT_PARSE_RESULT_INVALID"


@pytest.mark.parametrize("raw", [b"%PDF-small", b"%PDF-this-is-longer-than-declared"])
def test_original_bytes_fail_before_parse_on_wrong_size_or_digest(monkeypatch, raw):
    class Client:
        def get_object(self, **_kwargs):
            return {"Body": io.BytesIO(raw)}

    monkeypatch.setattr(handler.storage, "client", Client)
    monkeypatch.setattr(handler.storage, "bucket", lambda: "memory")
    with pytest.raises(DomainError) as error:
        handler._bytes({"object_key": "private", "byte_size": 20, "digest": "a" * 64})
    assert error.value.code == "ORIGINAL_BYTES_CORRUPTED"


def test_byte_and_parser_work_have_no_open_connection_and_postcheck_is_required(monkeypatch):
    method = selected(monkeypatch)
    raw = original()
    row = {"id": "request", "input_digest": "a" * 64, "input_manifest": {"method": method}}
    document = {"digest": sha(raw), "byte_size": len(raw), "object_key": "private"}
    open_connections, calls = [], []

    class Cursor:
        def execute(self, _query):
            pass

    @contextmanager
    def connection(*_args):
        open_connections.append(1)
        try:
            yield Cursor()
        finally:
            open_connections.pop()

    def record(_c, _message):
        calls.append(1)
        if len(calls) == 2:
            raise DomainError("DOCUMENT_PARSE_CONTEXT_CHANGED", "source revoked", 409)
        return copy.deepcopy(row), copy.deepcopy(document)

    def read_bytes(value):
        assert not open_connections and value == document
        return raw

    monkeypatch.setattr(handler, "connection", connection)
    monkeypatch.setattr(handler, "_record", record)
    monkeypatch.setattr(handler, "_bytes", read_bytes)
    with pytest.raises(DomainError) as error:
        handler.compute({})
    assert error.value.code == "DOCUMENT_PARSE_CONTEXT_CHANGED" and len(calls) == 2


def test_start_contract_has_no_current_material_body_or_implicit_review_fields():
    good = {"context_digest": "a" * 64, "reason": "Read exactly this original"}
    validate("StartDocumentParse", good)
    for field in (
        "current_body_id",
        "material_snapshot_id",
        "automatically_start_review",
        "document_version_id",
    ):
        with pytest.raises(DomainError):
            validate("StartDocumentParse", good | {field: "attacker supplied"})
