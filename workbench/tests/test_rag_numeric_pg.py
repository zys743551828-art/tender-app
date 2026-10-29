"""Actual PostgreSQL matching; opt-in shares the new isolated real-RAG database."""

import os

import pytest

from packages.rag.numeric import numeric_patterns
from tests.test_rag_real_integration import database

pytestmark = pytest.mark.skipif(os.environ.get("RUN_RAG_REAL") != "1", reason="Isolated PG opt-in")


@pytest.mark.parametrize(
    "query,original,expected",
    [
        ("C30", "混凝土C30强度等级", True),
        ("C30", "混凝土C300强度等级", False),
        ("3.2", "按照第3.2条执行", True),
        ("3.2", "按照第3.20条执行", False),
        ("GB/T 50300-2013", "依据GB/T50300-2013条款", True),
        ("GB/T 50300-2013", "依据GB/T50300-2026条款", False),
        ("C30", "混凝土Ｃ３０强度等级", True),
        ("-2.5", "观测值-2.5。", True),
        ("2.5", "观测值-2.5。", False),
        ("2.5MPa", "要求达到2.5MPa。", True),
    ],
)
def test_postgresql_literal_number_boundaries(query, original, expected):
    with database("api") as c:
        matched = c.execute(
            "SELECT normalize(%s,NFKC) ~* ANY(%s::text[]) AS matched",
            (original, list(numeric_patterns(query))),
        ).fetchone()["matched"]
    assert matched is expected
