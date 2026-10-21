"""Generate the independently owned retrospective UI contract without shared output edits."""

import json
import os

# Runs the fixed local schema generator without a shell or inherited credentials.
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from packages.contracts.package_retrospectives_api import SCHEMAS, schemas  # noqa: E402

OUTPUT = ROOT / "apps/web/src/packageRetrospectiveContracts.ts"
with tempfile.TemporaryDirectory(prefix="retrospective-contract-") as temporary:
    source = Path(temporary) / "openapi.json"
    source.write_text(json.dumps({"components": {"schemas": schemas()}}), encoding="utf-8")
    # Executable, script and schema roots are trusted constants.
    subprocess.run(  # nosec B603
        [
            sys.executable,
            str(ROOT / "apps/web/scripts/generate-contracts.py"),
            "--openapi",
            str(source),
            "--output",
            str(OUTPUT),
            "--schemas",
            ",".join(SCHEMAS),
        ],
        check=True,
        timeout=60,
        env={key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL"}},
    )
value = OUTPUT.read_text(encoding="utf-8")
OUTPUT.write_text(
    "// Generated from packages/contracts/package_retrospectives_api.py.\n// Run python apps/web/scripts/generate-retrospective-contracts.py from workbench.\n"
    + "\n".join(value.splitlines()[1:]),
    encoding="utf-8",
)
