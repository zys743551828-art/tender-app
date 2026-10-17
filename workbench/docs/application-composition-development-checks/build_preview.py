"""Build only SHA-checked reviewed public sources and explicit integration deltas."""

import hashlib
import json
from pathlib import Path

ROOT = Path("/workspace/tender-workbench")
OUT = ROOT / "docs/application-composition-development-checks"
OWN = [
    "apps/api/main.py",
    "apps/api/export_openapi.py",
    "apps/api/composition.py",
    "apps/api/composition_contracts.py",
    "tests/test_application_composition.py",
    "tests/test_application_composition_integration.py",
]


def build():
    recipe = json.loads((OUT / "recipe-01.json").read_text())
    runtime = OUT / "runtime-preview-01"
    sources = {x["path"]: x for x in recipe["selected_inputs"]}
    for path in OWN:
        raw = (ROOT / path).read_bytes()
        sources[path] = {
            "path": path,
            "input": str(ROOT / path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "layer": "composition01",
        }
    for row in sources.values():
        raw = Path(row["input"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row["sha256"], row["path"]
        target = runtime / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        target.chmod(0o644)
    value = {
        "runtime_root": str(runtime),
        "sources": sorted(sources.values(), key=lambda x: x["path"]),
    }
    (OUT / "source-preview-01.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )
    print({"source_count": len(sources), "runtime": str(runtime)})


if __name__ == "__main__":
    build()
