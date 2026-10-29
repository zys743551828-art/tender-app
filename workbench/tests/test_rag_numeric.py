"""Identifier boundaries and bounded matching, independent of model quality."""

from uuid import uuid4

import pytest

from packages.rag.numeric import numeric_patterns
from packages.rag.search import candidates, rerank


def test_identifiers_normalize_only_search_and_keep_units_decimals_and_revisions():
    assert numeric_patterns("混凝土Ｃ３０，标准GB/T 50300-2013，2.5MPa") == (
        r"(^|[^A-Za-z0-9_.+\-])c30([^A-Za-z0-9_.+\-]|$)",
        r"(^|[^A-Za-z0-9_.+\-])gb/t[[:space:]]*50300\-2013([^A-Za-z0-9_.+\-]|$)",
        r"(^|[^A-Za-z0-9_.+\-])2\.5mpa([^A-Za-z0-9_.+\-]|$)",
    )
    assert numeric_patterns("c30 C30 Ｃ３０") == numeric_patterns("C30")
    assert numeric_patterns("道路围挡要求") == ()
    assert numeric_patterns("C30 (.*)| C40") == numeric_patterns("C30 C40")


def test_excessive_identifiers_are_rejected_without_truncating_the_query():
    with pytest.raises(ValueError, match="NUMERIC_QUERY_TOO_LARGE"):
        numeric_patterns(" ".join(f"C{i}" for i in range(33)))
    with pytest.raises(ValueError, match="NUMERIC_QUERY_TOO_LARGE"):
        numeric_patterns("1" * 65)


def test_numeric_recall_uses_same_eligibility_and_excluded_evidence_as_other_lanes():
    ids = [uuid4(), uuid4(), uuid4()]
    source, bid, profile, blocked = uuid4(), uuid4(), uuid4(), uuid4()

    class Scope:
        source_ids = (source,)
        bid_id = bid
        as_of = "2026-01-01T00:00:00+00:00"
        excluded_groups = ()

    class Connection:
        def __init__(self):
            self.calls = []

        def execute(self, query, parameters):
            self.calls.append((str(query), parameters))
            return self

        def fetchall(self):
            step = len(self.calls)
            if step == 1:
                return []
            if step in (2, 3, 4):
                return [{"id": ids[step - 2]}]
            return [{"id": value} for value in ids]

    c = Connection()
    result = candidates(c, Scope(), profile, "[]", "no-number", (blocked,), query="C30")
    assert {r["id"] for r in result} == set(ids)
    numeric_sql, parameters = c.calls[3]
    assert "eligible_chunks" in numeric_sql and "NOT evidence_ids" in numeric_sql
    assert parameters[:5] == ([source], Scope.as_of, [], False, [blocked])
    assert parameters[5] == list(numeric_patterns("C30"))


def test_unavailable_reranker_retains_numeric_fusion_and_does_not_invent_identity():
    class Broken:
        def rank(self, query, texts):
            raise ValueError("Explicit unavailable fixture")

    rows = [{"id": uuid4(), "text_content": "混凝土C30"}]
    selected, route, identity = rerank("C30", rows, Broken())
    assert selected == rows
    assert route == "exact_vector+lexical+numeric_exact+rrf+reranker_unavailable"
    assert identity is None


def test_unidentified_reranker_does_not_claim_verified_success():
    class Unidentified:
        def rank(self, query, texts):
            return [0.0, 1.0]

    rows = [
        {"id": uuid4(), "text_content": "混凝土C30"},
        {"id": uuid4(), "text_content": "混凝土C40"},
    ]
    selected, route, identity = rerank("C30", rows, Unidentified())
    assert selected == rows and route.endswith("reranker_unavailable") and identity is None
