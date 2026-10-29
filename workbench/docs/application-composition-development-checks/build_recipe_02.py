"""Select immutable composition01+A2 PAGE02+Scale01 inputs; small integration deltas only."""

import hashlib
import json
import os
from pathlib import Path

ROOT = Path("/workspace/tender-workbench")
OUT = ROOT / "docs/application-composition-development-checks"
DOC = Path("/workspace/tender-docs/04-验证与测试")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def build():
    basepath = OUT / "candidate-01.json"
    base = json.loads(basepath.read_text())
    a2path = DOC / "authoring-complete-development-checks/candidate-02/candidate.json"
    a2 = json.loads(a2path.read_text())
    scalepath = (
        DOC
        / "research-backend-checks/technical-scale/candidate-01/technical-scale-candidate-01.json"
    )
    scale = json.loads(scalepath.read_text())
    assert (
        digest(basepath.read_bytes())
        == "32630d1d1e8572760cc9ca991ebd436caf7cf4f09f66e88c919777f1b2f20df3"
    )
    assert (
        digest(a2path.read_bytes())
        == "5cb2bd6f9c205bace488158d3b9656222b3e9a54aa215d1c6bf2d834f11773e9"
    )
    assert (
        digest(scalepath.read_bytes())
        == "9ad9becd41065d334ff03246026da4f9a79f90db89a5aa0696b3a0ada01c6f62"
    )
    sources = {}
    overlaps = []

    def take(row, folder, layer):
        src = folder / row["path"]
        assert digest(src.read_bytes()) == row["sha256"], row["path"]
        previous = sources.get(row["path"])
        value = {"path": row["path"], "input": str(src), "sha256": row["sha256"], "layer": layer}
        if previous and previous["sha256"] != row["sha256"]:
            overlaps.append(
                {
                    "path": row["path"],
                    "previous_sha256": previous["sha256"],
                    "previous_layer": previous["layer"],
                    "selected_sha256": row["sha256"],
                    "selected_layer": layer,
                    "decision": "select exact reviewed module own source; no merge of moving sources",
                }
            )
        sources[row["path"]] = value

    for row in base["sources"]:
        take(row, Path(base["fixed_runtime_root"]), "composition01")
    for row in a2["sources"]:
        take(row, Path(a2["runtime_root"]), "A2-PAGE02")
    for row in scale["sources"]:
        take(row, scalepath.parent / "source", "technical-scale01")
    # Score software remains unchanged: new scale authority does not enable a denominator or prediction.
    score_refs = []
    for row in scale["reference_inputs"]:
        if row["path"].startswith("packages/model_governance/scoring_") and row["path"] in sources:
            assert row["sha256"] == sources[row["path"]]["sha256"], row["path"]
            score_refs.append(row["path"])
    own = [
        "apps/api/composition.py",
        "apps/api/lifecycle_routes.py",
        "tests/test_application_composition_integration.py",
        "tests/test_lifecycle_resource_etag.py",
        "tests/test_application_composition.py",
        "tests/test_application_new_modules_integration.py",
    ]
    for path in own:
        take(
            {"path": path, "sha256": digest((ROOT / path).read_bytes())},
            ROOT,
            "composition02-integration-delta",
        )
    sql = base["ordered_fresh_sql"] + [
        {
            "path": "packages/authoring/sql/structure.sql",
            "sha256": sources["packages/authoring/sql/structure.sql"]["sha256"],
        },
        {
            "path": "deploy/sql/technical-scale-authority.sql",
            "sha256": sources["deploy/sql/technical-scale-authority.sql"]["sha256"],
        },
    ]
    recipe = {
        "base_candidate": {"path": str(basepath), "sha256": digest(basepath.read_bytes())},
        "module_candidates": [
            {"path": str(p), "sha256": digest(p.read_bytes())} for p in (a2path, scalepath)
        ],
        "selected_inputs": sorted(sources.values(), key=lambda x: x["path"]),
        "overlaps": overlaps,
        "ordered_fresh_sql": sql,
        "unchanged_scoring_references_checked": score_refs,
        "excluded": [
            "moving RICH",
            "new Score max integration",
            "any real provider or consumer startup",
        ],
        "transfer": "immutable existing input files hardlinked; own integration files copied, never overwrite a hardlink in place",
    }
    (OUT / "recipe-02.json").write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + "\n")
    runtime = OUT / "runtime-preview-02"
    for row in sources.values():
        target = runtime / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        if row["layer"] == "composition02-integration-delta":
            target.write_bytes(Path(row["input"]).read_bytes())
            target.chmod(0o644)
        else:
            os.link(row["input"], target)
    (OUT / "source-preview-02.json").write_text(
        json.dumps(
            {"runtime_root": str(runtime), "sources": recipe["selected_inputs"]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(
        {
            "inputs": len(sources),
            "overlaps": len(overlaps),
            "sql_count": len(sql),
            "recipe_sha256": digest((OUT / "recipe-02.json").read_bytes()),
            "runtime": str(runtime),
        }
    )


if __name__ == "__main__":
    build()
