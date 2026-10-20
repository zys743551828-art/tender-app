"""Append-only scope declaration storage; caller owns lock, command and transaction."""

from psycopg.types.json import Jsonb

from packages.domain.package_fact_scope import verify
from packages.domain.runtime import DomainError

KIND = "package-fact-scope-declare"


def head(c, bid, input_id, fact_id):
    rows = c.execute(
        """SELECT a.manifest,a.digest FROM design.bid_package_fact_scopes a
        WHERE a.bid_id=%s AND a.execution_input_id=%s AND a.fact_id=%s
        AND NOT EXISTS(SELECT 1 FROM design.bid_package_fact_scopes b
        WHERE b.execution_input_id=a.execution_input_id AND b.fact_id=a.fact_id
        AND b.previous_digest=a.digest)""",
        (bid, input_id, fact_id),
    ).fetchall()
    if len(rows) > 1:
        raise DomainError("PACKAGE_FACT_SCOPE_CORRUPT", "事实范围绑定链不完整", 500)
    return verify(dict(rows[0])) if rows else None


def append(c, record):
    value = verify(record)
    m = value["manifest"]
    b = m["binding"]
    c.execute(
        """INSERT INTO design.bid_package_fact_scopes
        (id,bid_id,execution_input_id,fact_id,actor_id,command_id,previous_digest,manifest,digest)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            m["id"],
            b["bid_id"],
            b["execution_input_id"],
            b["fact_id"],
            m["actor_id"],
            m["command_id"],
            m["previous_digest"],
            Jsonb(m),
            value["digest"],
        ),
    )
    return value


def load(c, scope, frozen_id, input_id, record_id):
    row = c.execute(
        """SELECT a.manifest,a.digest FROM design.bid_package_fact_scopes a
        JOIN design.bid_package_execution_inputs p ON p.bid_id=a.bid_id AND p.id=a.execution_input_id
        WHERE a.bid_id=%s AND p.manifest->>'package_id'=%s AND p.manifest->>'revision_id'=%s
        AND p.manifest->>'inventory_id'=%s AND p.frozen_input_id=%s AND p.id=%s AND a.id=%s""",
        (*scope, frozen_id, input_id, record_id),
    ).fetchone()
    if row is None:
        raise DomainError("PACKAGE_FACT_SCOPE_NOT_FOUND", "事实范围绑定不存在", 404)
    return verify(dict(row))
