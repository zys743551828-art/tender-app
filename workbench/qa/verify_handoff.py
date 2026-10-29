"""Read-only SHA-256 verification of the coordinated GitHub handoff snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text())
    failed = []
    checked = 0
    for row in inventory["files"]:
        relative = Path(row["repository"]) / row["repository_path"]
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit("Unsafe inventory path")
        path = args.workspace / relative
        if not path.is_file() or path.is_symlink():
            failed.append({"path": str(relative), "error": "missing_or_symlink"})
            continue
        data = path.read_bytes()
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            failed.append({"path": str(relative), "error": "bytes_or_sha256_mismatch"})
        checked += 1
    print(
        json.dumps(
            {"checked": checked, "failed": failed, "status": "failed" if failed else "passed"},
            ensure_ascii=False,
        )
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
