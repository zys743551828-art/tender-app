"""Bounded, literal identifiers and numbers for an independent exact retrieval lane.

This is a recall channel, not a unit conversion or an interpretation of a rule.
The original text is never normalized in stored citations. PostgreSQL applies the
same NFKC normalization only to the search expression.
"""

from __future__ import annotations

import re
import unicodedata

MAX_TERMS = 32
MAX_TERM_CHARACTERS = 64
NUMERIC_POLICY = {
    "version": 1,
    "normalization": "NFKC_case_insensitive",
    "matching": "literal_ascii_identifier_boundaries",
    "max_terms": MAX_TERMS,
    "max_term_characters": MAX_TERM_CHARACTERS,
    "candidates": 50,
    "rank": "matched_distinct_terms_then_uuid",
}
_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_.+\-])"
    r"(?:[A-Za-z]{1,8}(?:[ /-][A-Za-z]{1,4})?[ /-]?)?"
    r"[+\-]?[0-9]+(?:[./-][0-9]+)*(?:[A-Za-z]{1,8}|%)?"
    r"(?![A-Za-z0-9_.+\-])"
)


def numeric_patterns(query: str) -> tuple[str, ...]:
    """Return escaped PostgreSQL AREs; query text is always a bound parameter."""
    terms = tuple(
        dict.fromkeys(
            m.group().casefold() for m in _TOKEN.finditer(unicodedata.normalize("NFKC", query))
        )
    )
    if len(terms) > MAX_TERMS or any(len(term) > MAX_TERM_CHARACTERS for term in terms):
        raise ValueError("RAG_NUMERIC_QUERY_TOO_LARGE")
    return tuple(
        r"(^|[^A-Za-z0-9_.+\-])"
        + re.escape(term).replace(r"\ ", "[[:space:]]*")
        + r"([^A-Za-z0-9_.+\-]|$)"
        for term in terms
    )
