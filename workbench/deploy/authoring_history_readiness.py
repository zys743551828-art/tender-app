"""Read-only availability check; never apply SQL or promote runtime accounts."""

import json

from packages.authoring_history import permissions, service
from packages.domain.runtime import DomainError


def verify():
    with service.snapshot() as c:
        result = permissions.require(c)
        result["image_tables"] = permissions.tables(c, permissions.IMAGE_TABLES)
    return {
        "version": "authoring-history-readiness/1",
        "ready": True,
        "ddl_applied": False,
        "checks": result,
    }


def main():
    try:
        print(json.dumps(verify(), sort_keys=True, indent=2))
    except DomainError as error:
        print(
            json.dumps(
                {"version": "authoring-history-readiness/1", "ready": False, "code": error.code}
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
