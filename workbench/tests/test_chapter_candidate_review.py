import copy

import pytest

from qa.chapter_candidate_review import review_candidates


def fixture():
    return {
        "coverage": "partial",
        "gaps": [{"physical_page": 1, "code": "OCR_LOW_CONFIDENCE"}],
        "pages": [
            {
                "physical_page": 1,
                "width": 600,
                "blocks": [
                    {
                        "id": "a",
                        "text_content": "A long paragraph ends in a model prefix",
                        "bbox": [60, 10, 540, 30],
                    },
                    {
                        "id": "b",
                        "text_content": "400. Example continuation",
                        "bbox": [60, 33, 540, 53],
                        "confidence": 0.7,
                        "kind": "text",
                    },
                    {"id": "c", "text_content": "Next line", "bbox": [60, 56, 540, 76]},
                ],
            }
        ],
        "chapters": [
            {
                "physical_page": 1,
                "evidence_id": "b",
                "title": "400. Example continuation",
                "inferred": True,
            }
        ],
    }


def test_context_and_signals_never_change_source_or_accept_headings():
    parsed = fixture()
    original = copy.deepcopy(parsed)
    result = review_candidates(parsed)
    row = result["candidates"][0]
    assert "ADJACENT_WIDE_LINES_CHECK_FOR_CONTINUATION" in row["signals"]
    assert row["previous_same_page_block"]["id"] == "a"
    assert row["next_same_page_block"]["id"] == "c"
    assert row["candidate_block"]["confidence"] == 0.7
    assert row["review_decision"] == "not_reviewed"
    assert not result["automatic_heading_acceptance"]
    assert result["coverage"] == "partial"
    row["candidate_block"]["bbox"][0] = 999
    result["gaps"].clear()
    assert parsed == original


@pytest.mark.parametrize("box", [None, [0, 0, 0, 0], [0, float("nan"), 50, 30], [0, 0, 30]])
def test_missing_or_invalid_geometry_does_not_guess_continuity(box):
    parsed = fixture()
    parsed["pages"][0]["blocks"][0]["bbox"] = box
    assert (
        "ADJACENT_WIDE_LINES_CHECK_FOR_CONTINUATION"
        not in review_candidates(parsed)["candidates"][0]["signals"]
    )


def test_short_heading_is_not_asserted_correct_and_never_joins_previous_page():
    parsed = fixture()
    parsed["pages"][0]["blocks"] = [parsed["pages"][0]["blocks"][1]]
    row = review_candidates(parsed)["candidates"][0]
    assert row["previous_same_page_block"] is None
    assert row["next_same_page_block"] is None
    assert row["review_decision"] == "not_reviewed"


@pytest.mark.parametrize(
    "change, error",
    [("missing", "CHAPTER_EVIDENCE_NOT_FOUND"), ("duplicate", "DUPLICATE_EVIDENCE_REFERENCE")],
)
def test_invalid_reference_is_rejected(change, error):
    parsed = fixture()
    if change == "missing":
        parsed["chapters"][0]["evidence_id"] = "absent"
    else:
        parsed["pages"][0]["blocks"].append(parsed["pages"][0]["blocks"][1])
    with pytest.raises(ValueError, match=error):
        review_candidates(parsed)


def test_no_candidates_does_not_infer_from_text():
    parsed = fixture()
    parsed["chapters"] = []
    assert review_candidates(parsed)["candidates"] == []


def test_cli_preserves_existing_output(tmp_path, monkeypatch):
    import json
    import sys

    from qa.chapter_candidate_review import main

    source = tmp_path / "source.json"
    output = tmp_path / "review.json"
    source.write_text(json.dumps(fixture()), encoding="utf-8")
    output.write_text("existing human review", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["review", str(source), str(output)])
    with pytest.raises(FileExistsError):
        main()
    assert output.read_text(encoding="utf-8") == "existing human review"


def test_cli_creates_private_review_without_stdout(tmp_path, monkeypatch, capsys):
    import json
    import sys

    from qa.chapter_candidate_review import main

    source = tmp_path / "source.json"
    output = tmp_path / "review.json"
    source.write_text(json.dumps(fixture()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["review", str(source), str(output)])
    main()
    assert json.loads(output.read_text(encoding="utf-8"))["purpose"] == "private_human_review_only"
    assert capsys.readouterr().out == ""
