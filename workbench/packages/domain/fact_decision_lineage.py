"""Resolve explicit immutable adoption edges; dates never select or invent history."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from packages.domain.package_fact_validation import fact_identity
from packages.domain.runtime import sha

MAX_HOPS = 256


def _id(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("lineage_timezone")
    return result


def decision_known(decision, as_of):
    try:
        return _time(decision["created_at"]) <= _time(as_of)
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def resolve(bid, leaf, decision, basis, as_of, read_edge, read_fact, *, limit=MAX_HOPS):
    try:
        if not all(
            _id(x)
            for x in (
                bid,
                leaf["id"],
                leaf["fact_set_id"],
                str(decision["id"]),
                str(decision["object_id"]),
            )
        ):
            return None
        root = str(decision["object_id"])
        decision_id = str(decision["id"])
        at = _time(as_of)
        known = _time(decision["created_at"])
        if known > at:
            return None
        current = leaf
        edges: list[dict[str, Any]] = []
        seen = set()
        equivalence = sha(basis)
        for _ in range(limit):
            if current["id"] == root:
                return edges
            if current["id"] in seen:
                return None
            seen.add(current["id"])
            edge = read_edge(current)
            if not isinstance(edge, dict) or not all(
                _id(edge.get(k))
                for k in (
                    "audit_id",
                    "new_fact_id",
                    "from_fact_id",
                    "from_decision_id",
                    "fact_set_id",
                    "bid_id",
                )
            ):
                return None
            if (
                not isinstance(edge.get("audit_digest"), str)
                or re.fullmatch("[a-f0-9]{64}", edge["audit_digest"]) is None
            ):
                return None
            if (
                edge["bid_id"] != bid
                or edge["fact_set_id"] != current["fact_set_id"]
                or edge["new_fact_id"] != current["id"]
                or edge["from_decision_id"] != decision_id
                or edge["equivalence_digest"] != equivalence
            ):
                return None
            if not known <= _time(edge["audit_recorded_at"]) <= at:
                return None
            parent = read_fact(edge["from_fact_id"])
            if (
                not isinstance(parent, dict)
                or parent["id"] != edge["from_fact_id"]
                or parent["bid_id"] != bid
                or not _id(parent["fact_set_id"])
                or parent["fact_set_id"] == current["fact_set_id"]
            ):
                return None
            recorded = edge["previous_set_recorded"]
            if (
                type(recorded) is not bool
                or recorded
                and edge["previous_set_id"] != parent["fact_set_id"]
            ):
                return None
            if (
                fact_identity(current) != basis["fact_identity"]
                or fact_identity(parent) != basis["fact_identity"]
            ):
                return None
            edges.append(
                {
                    key: edge[key]
                    for key in (
                        "audit_id",
                        "audit_digest",
                        "audit_recorded_at",
                        "actor_id",
                        "command_id",
                        "new_fact_id",
                        "fact_set_id",
                        "from_fact_id",
                        "from_decision_id",
                        "equivalence_digest",
                        "previous_set_recorded",
                    )
                }
                | {"from_fact_set_id": parent["fact_set_id"]}
            )
            at = _time(edge["audit_recorded_at"])
            current = parent
        return edges if current["id"] == root else None
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None
