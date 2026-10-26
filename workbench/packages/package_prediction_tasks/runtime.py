"""Opt-in API coordinator used by the existing bounded task runner."""

from packages.domain.errors import DomainError
from packages.model_governance.common import GovernanceError
from packages.package_prediction_tasks.native import BLOCKED, CANCELLED, EVENT, PUBLISHED

_service = None
_connections = None


def configure(service, connections):
    global _service, _connections
    _service, _connections = service, connections


def drain(limit=50):
    if _service is None or _connections is None:
        return {"processed": 0, "blocked": 0}
    with _connections() as c:
        rows = c.execute(
            "SELECT a.payload FROM design.audit_entries a JOIN design.operations o ON o.id=(a.payload->>'operation_id')::uuid WHERE a.event_type=%s AND o.state='succeeded' AND NOT EXISTS(SELECT FROM design.audit_entries p WHERE p.event_type=ANY(%s) AND p.payload->>'request_id'=a.payload->>'request_id') ORDER BY o.finished_at,a.id LIMIT %s",
            (EVENT, [PUBLISHED, CANCELLED, BLOCKED], limit),
        ).fetchall()
    done = blocked = 0
    for row in rows:
        b = row["payload"]["body"]
        try:
            value = _service.advance(b["actor"], b["bid"], b["scope"], b["command"])
            done += value["state"] == "published"
        except (DomainError, GovernanceError):
            blocked += 1
    return {"processed": done, "blocked": blocked}
