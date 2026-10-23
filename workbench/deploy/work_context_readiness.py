"""Verify actual nonowner read permissions without DDL, business writes or I/O.

Run with the ordinary API_DATABASE_DSN already configured. Credentials and record
content are never printed. This command does not repair permissions as an owner.
"""

import json

from packages.domain.runtime import DomainError, connection
from packages.work_contexts import permissions


def verify():
    results = {}
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        for kind in ("run", "submission", "relations"):
            results[kind] = permissions.require(c, kind)
    return {
        "version": "work-context-readiness/1",
        "ready": True,
        "ddl_applied": False,
        "checks": results,
    }


def main():
    try:
        print(json.dumps(verify(), sort_keys=True, indent=2))
    except DomainError as error:
        print(
            json.dumps(
                {
                    "version": "work-context-readiness/1",
                    "ready": False,
                    "code": error.code,
                    "ddl_applied": False,
                },
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
