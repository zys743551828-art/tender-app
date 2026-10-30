"""Explicit isolated acceptance consumer; never mounted on the business API.

Host uses existing API DSN/private storage injection and frozen local CAS paths.
No secret is accepted as a command-line argument or printed in an error.
"""

import argparse
import json
import sys
from uuid import UUID

from psycopg import Error

from packages.domain.errors import DomainError
from packages.domain.runtime import connection
from packages.model_governance.common import GovernanceError
from packages.package_model_live.producer import Executor
from packages.package_prediction_tasks.storage import Objects
from packages.prediction_sandbox.application import Sandbox
from packages.prediction_sandbox.native import Transactions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--actor", required=True, type=UUID)
    parser.add_argument("--bid", required=True, type=UUID)
    parser.add_argument("--command", required=True, type=UUID)
    parser.add_argument("--certificate", type=UUID)
    parser.add_argument("--scope", type=UUID)
    parser.add_argument("--source-ref")
    parser.add_argument("--valid-until")
    parser.add_argument("--reason")
    parser.add_argument(
        "action", choices=("issue", "submit", "advance", "read", "revoke", "cancel")
    )
    args = parser.parse_args()
    service = Sandbox(Transactions(connection), Objects(), Executor(args.store, args.index))
    body = {
        key: str(getattr(args, key)) for key in ("actor", "bid", "scope", "certificate", "command")
    }
    if args.action == "issue":
        if not args.source_ref or not args.valid_until:
            parser.error("issue requires --source-ref and --valid-until")
    elif not args.scope or not args.certificate:
        parser.error("task actions require --scope and --certificate")
    try:
        if args.action == "issue":
            result = service.issue(
                args.actor, args.bid, args.command, args.source_ref, args.valid_until
            )
        elif args.action == "revoke":
            if not args.reason:
                parser.error("revoke requires --reason")
            result = service.revoke(body, args.command, args.reason)
        else:
            result = getattr(service, args.action)(body)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except (DomainError, GovernanceError, Error, OSError, KeyError, TypeError, ValueError):
        print("PREDICTION_SANDBOX_REJECTED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
