"""Explicit internal route activation/consumption/rollback, never business routing."""

import argparse
import json
import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from packages.model_governance import package_feature_handoff as files
    from packages.package_model_observation.execution import LocalExecutor
    from packages.package_model_route.application import Routes
    from packages.package_model_route.infrastructure import NativeTransactions
    from packages.platform_runtime.database import transaction
    from packages.storage.private_cas import sha

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--expected-request-digest", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        files.command(args.actor)
        raw = files.private_read(args.request, maximum=16384)
        if sha(raw) != files.checksum(args.expected_request_digest):
            raise ValueError("request mismatch")
        receipt = Routes(
            NativeTransactions(transaction), LocalExecutor(args.store, args.artifact_dir)
        ).execute(args.actor, files.decode(raw))
        print(json.dumps(receipt))
        return 0
    except Exception:
        print(json.dumps({"ok": False, "code": "PACKAGE_INTERNAL_ROUTE_REJECTED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
