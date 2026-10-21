"""Inspect B1 discovery's actual SELECT role dependencies; never install or grant."""

import json

from packages.authoring_input_catalog import permissions, service
from packages.domain.runtime import DomainError


def verify():
    checks = {}
    for kind in ("nodes", "sets", "facts"):
        with service.snapshot(kind) as c:
            checks[kind] = permissions.require(c, kind)
    return {
        "protocol": "authoring-input-catalog-readiness/1",
        "ready": True,
        "ddl_applied": False,
        "checks": checks,
    }


def main():
    try:
        print(json.dumps(verify(), sort_keys=True, indent=2))
    except DomainError as error:
        print(
            json.dumps(
                {
                    "protocol": "authoring-input-catalog-readiness/1",
                    "ready": False,
                    "code": error.code,
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
