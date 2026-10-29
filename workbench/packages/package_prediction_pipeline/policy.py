"""Versioned source identity for newly frozen project prediction intents."""

from pathlib import Path

from packages.domain.review_identity import digest
from packages.storage.private_cas import sha

VERSION = "package-prediction-pipeline/1"


def method_digest():
    root = Path(__file__).parent
    return digest(
        {
            "version": VERSION,
            "sources": {p.name: sha(p.read_bytes()) for p in sorted(root.glob("*.py"))},
            "sql": sha(
                (root.parents[1] / "deploy/sql/package-prediction-selection.sql").read_bytes()
            ),
        }
    )


def same_documents(expected, actual):
    """Same nonempty physical document set, without duplicate or partial identities."""
    keys = ("document_version_id", "parse_run_id", "file_digest")
    try:
        left = [tuple(row[key] for key in keys) for row in expected]
        right = [tuple(row[key] for key in keys) for row in actual]
        return (
            bool(left)
            and all(isinstance(value, str) and value for row in left + right for value in row)
            and len(left) == len(set(left))
            and len(right) == len(set(right))
            and set(left) == set(right)
        )
    except (KeyError, TypeError):
        return False
