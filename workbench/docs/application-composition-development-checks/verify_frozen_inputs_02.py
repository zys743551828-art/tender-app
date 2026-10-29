"""Verify every original candidate source/ref against its original immutable tree."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("/workspace/tender-workbench")
DOC = Path("/workspace/tender-docs/04-验证与测试")
OUT = ROOT / "docs/application-composition-development-checks"


def verify():
    app_path = OUT / "candidate-01.json"
    a2_path = DOC / "authoring-complete-development-checks/candidate-02/candidate.json"
    scale_path = (
        DOC
        / "research-backend-checks/technical-scale/candidate-01/technical-scale-candidate-01.json"
    )
    score_path = (
        DOC
        / "research-backend-checks/score-execution/candidate-01/score-execution-candidate-01.json"
    )
    word_path = ROOT / "docs/word-mainflow-development-checks/candidate-01.json"
    results = []
    for path in (app_path, a2_path, scale_path, score_path, word_path):
        data = json.loads(path.read_text())
        sets = []
        if path == app_path:
            sets = [("sources", data["sources"], Path(data["fixed_runtime_root"]))]
        elif path == a2_path:
            sets = [
                ("sources", data["sources"], Path(data["runtime_root"])),
                ("dependencies", data["dependencies"], Path(data["runtime_root"])),
            ]
        elif path == scale_path:
            sets = [
                ("sources", data["sources"], path.parent / "source"),
                ("reference_inputs", data["reference_inputs"], path.parent / "reference-inputs"),
            ]
        elif path == score_path:
            sets = [
                ("sources", data["sources"], path.parent / "runtime"),
                ("reference_inputs", data["reference_inputs"], path.parent / "reference-inputs"),
            ]
        else:
            manifest = json.loads(Path(data["runtime_manifest"]["path"]).read_text())
            sets = [("sources", manifest["sources"], Path(data["fixed_runtime_root"]))]
        counts = {}
        for name, rows, folder in sets:
            for row in rows:
                value = (folder / row["path"]).read_bytes()
                assert hashlib.sha256(value).hexdigest() == row["sha256"], (str(path), row["path"])
            counts[name] = len(rows)
        results.append(
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "all_input_bytes_match": True,
                "counts": counts,
            }
        )
    out = OUT / f"frozen-input-integrity-{sys.argv[1]}.json"
    out.write_text(json.dumps({"candidates": results}, ensure_ascii=False, indent=2) + "\n")
    print(
        {
            "phase": sys.argv[1],
            "candidates_verified": len(results),
            "inputs_verified": sum(sum(x["counts"].values()) for x in results),
        }
    )


if __name__ == "__main__":
    verify()
