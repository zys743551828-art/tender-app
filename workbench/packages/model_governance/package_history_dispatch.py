"""Bounded metadata discovery and existing owned CPU execution; no app configuration."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import psycopg

from packages.model_governance import package_history_runtime as runtime
from packages.model_governance.common import GovernanceError

MAX_BATCH = 20


@dataclass(frozen=True, order=True)
class Cursor:
    created_at: datetime
    job_id: UUID

    def view(self):
        return {
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(
                timespec="microseconds"
            ),
            "job_id": str(self.job_id),
        }


def _invalid():
    return GovernanceError(
        "PACKAGE_HISTORY_DISPATCH_INVALID", "Invalid bounded CPU dispatch metadata"
    )


def _arguments(purpose, after, limit):
    if (
        not isinstance(purpose, str)
        or purpose not in {"train", "evaluate"}
        or type(limit) is not int
        or not 1 <= limit <= MAX_BATCH
    ):
        raise _invalid()
    if after is not None and (
        not isinstance(after, Cursor)
        or not isinstance(after.job_id, UUID)
        or not isinstance(after.created_at, datetime)
        or after.created_at.tzinfo is None
        or after.created_at.utcoffset() is None
    ):
        raise _invalid()


def _page(value, after, limit):
    if not isinstance(value, list) or len(value) > limit:
        raise _invalid()
    previous = after
    seen = set()
    result = []
    for item in value:
        try:
            if not isinstance(item, dict) or set(item) != {"job_id", "generation", "created_at"}:
                raise _invalid()
            identity = UUID(item["job_id"])
            at = datetime.fromisoformat(item["created_at"])
            generation = item["generation"]
            if (
                str(identity) != item["job_id"]
                or at.tzinfo is None
                or at.utcoffset() is None
                or type(generation) is not int
                or not 1 <= generation < 2**63
                or identity in seen
            ):
                raise _invalid()
            position = Cursor(at, identity)
            if previous is not None and position <= previous:
                raise _invalid()
        except (TypeError, ValueError, AttributeError):
            raise _invalid() from None
        result.append((position, generation))
        previous = position
        seen.add(identity)
    return result


def cycle(purpose, *, after=None, limit=5, stopped=None):
    """Advance even past a stale candidate; wrap on an empty page in the next cycle."""
    _arguments(purpose, after, limit)
    with runtime.connection(purpose) as c:
        raw = c.execute(
            "SELECT package_historical_research.dispatch_candidates(%s,%s,%s,%s) AS value",
            (purpose, after.created_at if after else None, after.job_id if after else None, limit),
        ).fetchone()["value"]
    candidates = _page(raw, after, limit)
    outcomes = []
    position = after
    for candidate, generation in candidates:
        if stopped is not None and stopped.is_set():
            break
        try:
            value = runtime.run(purpose, candidate.job_id, generation)
            if (
                not isinstance(value, dict)
                or value.get("job_id") != str(candidate.job_id)
                or value.get("state") != "succeeded"
            ):
                raise _invalid()
            state = "completed"
        except psycopg.Error as error:
            if error.sqlstate not in {"55000", "P0002", "23514"}:
                raise
            # Claim races, changed generations, stale sources or invalid exports
            # never replace the request, fabricate results or expose private errors.
            state = "deferred"
        except GovernanceError as error:
            if error.code in {
                "PACKAGE_HISTORY_ROLE_DENIED",
                "PACKAGE_HISTORY_ENVIRONMENT_NOT_ISOLATED",
                "PACKAGE_HISTORY_PURPOSE_NOT_CONFIGURED",
                "PACKAGE_HISTORY_PURPOSE_INVALID",
            }:
                raise
            state = "deferred"
        outcomes.append({"job_id": str(candidate.job_id), "generation": generation, "state": state})
        position = candidate
    if not candidates:
        position = None
    return position, {
        "schema": "package-history-dispatch-cycle/1",
        "purpose": purpose,
        "scanned": len(candidates),
        "attempted": len(outcomes),
        "completed": sum(item["state"] == "completed" for item in outcomes),
        "outcomes": outcomes,
        "next_cursor": position.view() if position else None,
        "research_only": True,
        "formal_eligibility": "unavailable",
        "provider_requests": 0,
        "paid_calls": 0,
    }
