from copy import deepcopy
from hashlib import sha256
from uuid import UUID

import pytest

from packages.domain.partial_page_selection import SelectionError, candidate


def uid(number):
    return str(UUID(int=number))


def fixture():
    source = {
        "bid_id": uid(1),
        "document_version_id": uid(2),
        "parse_run_id": uid(3),
        "file_digest": "a" * 64,
        "parser_digest": "b" * 64,
        "config_digest": "c" * 64,
        "page_count": 3,
        "coverage": "partial",
        "gaps": ["OCR_UNVERIFIED"],
    }
    pages = [
        {"physical_page": 1, "quality": "usable", "gaps": []},
        {"physical_page": 2, "quality": "partial", "gaps": ["OCR_LOW_CONFIDENCE"]},
        {"physical_page": 3, "quality": "failed", "gaps": ["OCR_FAILED"]},
    ]
    blocks = [
        {
            "id": uid(n + 10),
            "physical_page": n,
            "ordinal": 0,
            "kind": "text",
            "text_content": text,
            "digest": sha256(text.encode()).hexdigest(),
        }
        for n, text in [(1, "outside"), (2, "selected")]
    ]
    return {
        "source": source,
        "pages": pages,
        "blocks": blocks,
        "first_page": 2,
        "last_page": 2,
        "purpose": "technical_reference",
    }


def test_candidate_keeps_exact_provenance_and_gaps_without_exposing_text():
    inputs = fixture()
    before = deepcopy(inputs)
    value = candidate(**inputs)
    manifest = value["manifest"]
    assert manifest["selected_blocks"][0]["id"] == uid(12)
    assert manifest["selected_pages"] == [inputs["pages"][1]]
    assert manifest["omitted_ranges"] == [
        {"first_page": 1, "last_page": 1},
        {"first_page": 3, "last_page": 3},
    ]
    assert manifest["coverage"] == "partial"
    assert not any(
        manifest[k]
        for k in (
            "manual_confirmation_recorded",
            "original_bytes_reverified",
            "model_execution_allowed",
            "formal_qualification",
        )
    )
    assert "selected" not in str(manifest["selected_blocks"])
    assert inputs == before and candidate(**inputs) == value


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.update(first_page=0),
        lambda x: x.update(last_page=4),
        lambda x: x.update(first_page=True),
        lambda x: x.update(purpose="formal_scoring"),
        lambda x: x["source"].update(coverage="failed"),
        lambda x: x["pages"].pop(),
        lambda x: x["blocks"][1].update(text_content="altered"),
        lambda x: x["blocks"].append(deepcopy(x["blocks"][0])),
        lambda x: x["blocks"].append(deepcopy(x["blocks"][0]) | {"id": uid(99)}),
    ],
)
def test_candidate_rejects_invalid_or_rebound_inputs(change):
    inputs = fixture()
    change(inputs)
    with pytest.raises(SelectionError):
        candidate(**inputs)
