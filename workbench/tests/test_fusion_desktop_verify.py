import builtins
from copy import deepcopy

import pypdfium2
import pytest

from deploy import fusion_desktop_verify as verify
from deploy import fusion_parsing_spec as parsing
from deploy.fusion_desktop_verify import pdf
from packages.parsing.physical_pdf import CONFIG_DIGEST, PARSER_DIGEST


def test_verification_pdf_does_not_require_a_pdf_authoring_dependency(monkeypatch):
    original_import = builtins.__import__

    def without_reportlab(name, *args, **kwargs):
        if name == "reportlab" or name.startswith("reportlab."):
            raise ModuleNotFoundError("ReportLab is absent from the application image")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_reportlab)
    data = pdf()
    expected = [
        "Synthetic desktop transport acceptance. No official bid.",
        "Second physical page. No model or score qualification.",
    ]
    document = pypdfium2.PdfDocument(data)
    try:
        assert len(document) == 2
        for index, text in enumerate(expected):
            page = document[index]
            textpage = page.get_textpage()
            try:
                assert textpage.get_text_range().strip() == text
            finally:
                textpage.close()
                page.close()
    finally:
        document.close()


def observation(*, configured):
    document = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    digest = "b" * 64
    method = {
        "protocol": "document-parse-method/1",
        "mode": "configured_local" if configured else "physical_text_only",
        "parser_digest": "c" * 64 if configured else PARSER_DIGEST,
        "config_digest": "d" * 64 if configured else CONFIG_DIGEST,
        "implementation_digest": "e" * 64,
    }
    context = {"document_version_id": document, "document": {"sha256": digest}, "method": method}
    selected = {"context": context, "context_digest": "f" * 64}
    parsed = {
        "document_version_id": document,
        "context": deepcopy(context),
        "context_digest": selected["context_digest"],
        "operation": {"handler_version": "document-parse/1", "state": "succeeded"},
        "current_body_changed": False,
        "automatically_started_review": False,
        "result": {
            "parse_run_id": "11111111-1111-4111-8111-111111111111",
            "document_version_id": document,
            "source_digest": digest,
            "parser_digest": method["parser_digest"],
            "config_digest": method["config_digest"],
            "page_count": 2,
            "evidence_count": 2,
            "word_coverage_claimed": False,
            "coverage": "complete" if configured else "partial",
            "gaps": [] if configured else ["TEXT_ONLY_TABLES_VISUAL_AND_LAYOUT_UNVERIFIED"],
            "gap_count": 0 if configured else 1,
        },
    }
    profile = {
        "plan": {"parser": parsing.descriptor("synthetic-parser@sha256:" + "1" * 64)}
        if configured
        else {}
    }
    return profile, selected, parsed, document, digest


@pytest.mark.parametrize("configured", [False, True])
def test_fixed_two_page_fixture_qualifies_only_its_declared_parse_lane(configured):
    profile, selected, parsed, document, digest = observation(configured=configured)
    result = verify.parse_qualification(
        profile, selected, parsed, document=document, source_digest=digest
    )
    assert result["coverage"] == ("complete" if configured else "partial")
    assert result["parser_mode"] == ("configured_local" if configured else "physical_text_only")
    assert result["parser_digest"] == selected["context"]["method"]["parser_digest"]
    assert result["config_digest"] == selected["context"]["method"]["config_digest"]


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize(
    "attack",
    [
        "opposite_coverage",
        "wrong_mode",
        "parser",
        "config",
        "context",
        "source",
        "document",
        "one_page",
        "gap",
        "body_adopted",
        "review_started",
        "word_claim",
        "wrong_handler",
    ],
)
def test_transport_verification_does_not_accept_a_different_lane_or_qualification(
    configured, attack
):
    profile, selected, parsed, document, digest = observation(configured=configured)
    if attack == "opposite_coverage":
        parsed["result"]["coverage"] = "partial" if configured else "complete"
    elif attack == "wrong_mode":
        selected["context"]["method"]["mode"] = (
            "physical_text_only" if configured else "configured_local"
        )
        parsed["context"] = deepcopy(selected["context"])
    elif attack in {"parser", "config"}:
        parsed["result"][attack + "_digest"] = "9" * 64
    elif attack == "context":
        parsed["context_digest"] = "8" * 64
    elif attack == "source":
        parsed["result"]["source_digest"] = "7" * 64
    elif attack == "document":
        parsed["result"]["document_version_id"] = "22222222-2222-4222-8222-222222222222"
    elif attack == "one_page":
        parsed["result"]["page_count"] = 1
    elif attack == "gap":
        parsed["result"]["gaps"] = ["OCR_NOT_CONFIGURED"]
    elif attack == "body_adopted":
        parsed["current_body_changed"] = True
    elif attack == "review_started":
        parsed["automatically_started_review"] = True
    elif attack == "word_claim":
        parsed["result"]["word_coverage_claimed"] = True
    else:
        parsed["operation"]["handler_version"] = "document/2"
    with pytest.raises(verify.spec.ConfigurationError, match="DESKTOP_PARSE_QUALIFICATION_CHANGED"):
        verify.parse_qualification(
            profile, selected, parsed, document=document, source_digest=digest
        )


def test_relabelled_legacy_parser_identity_cannot_pass_as_configured_service():
    profile, selected, parsed, document, digest = observation(configured=True)
    selected["context"]["method"]["parser_digest"] = PARSER_DIGEST
    parsed["context"] = deepcopy(selected["context"])
    parsed["result"]["parser_digest"] = PARSER_DIGEST
    with pytest.raises(verify.spec.ConfigurationError, match="DESKTOP_PARSE_QUALIFICATION_CHANGED"):
        verify.parse_qualification(
            profile, selected, parsed, document=document, source_digest=digest
        )
