"""Bounded recovery of existing project intents; no scheduler or provider is started."""

from packages.domain.errors import DomainError
from packages.model_governance.common import GovernanceError

_service = None
_connections = None
_cursor = None


def configure(service, connections):
    global _service, _connections, _cursor
    _service, _connections, _cursor = service, connections, None


def drain(limit=50):
    global _cursor
    if _service is None or _connections is None:
        return {"processed": 0, "blocked": 0}
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("bounded scan required")
    with _connections() as c:
        rows = c.execute(
            "SELECT s.id,s.bid_id,s.actor_id FROM design.bid_package_technical_scopes s "
            "JOIN design.members m ON m.id=s.actor_id AND m.active "
            "WHERE (%s::uuid IS NULL OR s.id>%s::uuid) ORDER BY s.id LIMIT %s",
            (_cursor, _cursor, limit),
        ).fetchall()
    _cursor = str(rows[-1]["id"]) if len(rows) == limit else None
    processed = blocked = 0
    for row in rows:
        try:
            _service.advance(row["actor_id"], row["bid_id"], row["id"])
            processed += 1
        except (DomainError, GovernanceError):
            blocked += 1
    return {"processed": processed, "blocked": blocked}
