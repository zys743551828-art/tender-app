"""Read-only readiness for the additive four-stage directory; no owner fallback."""

import json

from packages.domain.runtime import DomainError
from packages.work_contexts import authoring_service, catalog_permissions, permissions


def verify():
    results = {}
    for kind in ("draft_snapshot", "build", "package_review_run", "package_submission"):
        with authoring_service.snapshot(kind) as c:
            native = {"package_review_run": "run", "package_submission": "submission"}.get(
                kind, "relations"
            )
            results[kind] = permissions.inspect(c, native)
            results[kind]["additional_tables"] = (
                catalog_permissions.require(c) if kind in {"draft_snapshot", "build"} else []
            )
    return {
        "version": "work-context-catalog-readiness/1",
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
                    "version": "work-context-catalog-readiness/1",
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
