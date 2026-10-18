from __future__ import annotations

from bidwb import term_conflicts


def _term(value: str, source: str = "evd_tender") -> dict[str, object]:
    return {"value": value, "quote": f"技术标满分{value}分", "evidence_ids": [source]}


def test_distinct_candidates_are_not_resolved_by_order() -> None:
    for candidates in ((_term("60"), _term("80", "evd_supplement")), (_term("80", "evd_supplement"), _term("60"))):
        terms: term_conflicts.TermMap = {}
        for candidate in candidates:
            term_conflicts.add_candidate(terms, "technical_full_score", candidate)
        assert set(term_conflicts.effective(terms)) == set()
        assert len(term_conflicts.pending(terms)["technical_full_score"]) == 2


def test_equivalent_decimal_values_are_not_a_conflict() -> None:
    terms: term_conflicts.TermMap = {}
    for value in ("60", "60.0", "60.00"):
        term_conflicts.add_candidate(terms, "technical_full_score", _term(value))
    assert term_conflicts.pending(terms) == {}
    assert term_conflicts.effective(terms)["technical_full_score"]["value"] == "60"


def test_price_method_changes_and_partial_candidates_require_review() -> None:
    terms: term_conflicts.TermMap = {}
    for candidate in (
        {"method": "average", "full_score": "40", "quote": "平均值40分", "evidence_ids": ["a"]},
        {"method": "trimmed_average", "full_score": "40", "quote": "去极值40分", "evidence_ids": ["b"]},
    ):
        term_conflicts.add_candidate(terms, "price_rule", candidate)
    assert "price_rule" in term_conflicts.pending(terms)


def test_human_resolution_keeps_candidates_and_selected_value() -> None:
    terms: term_conflicts.TermMap = {}
    for candidate in (_term("60"), _term("80", "evd_supplement")):
        term_conflicts.add_candidate(terms, "technical_full_score", candidate)
    selected = terms["_alternatives"]["technical_full_score"][1]
    terms["technical_full_score"] = selected
    terms["_resolved"] = {"technical_full_score": term_conflicts.option_id(selected)}
    assert term_conflicts.pending(terms) == {}
    assert term_conflicts.effective(terms)["technical_full_score"]["value"] == "80"
    assert len(terms["_alternatives"]["technical_full_score"]) == 2
