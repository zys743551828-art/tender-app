"""Compose reviewed exact inputs; never copy a mutable source tree or private/runtime cache."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("/workspace/tender-workbench")
DOCS = Path("/workspace/tender-docs/04-验证与测试")
OUT = ROOT / "docs/application-composition-development-checks"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def candidate(name, path, folder):
    data = json.loads(path.read_text())
    return {
        "name": name,
        "path": str(path),
        "sha256": digest(path.read_bytes()),
        "data": data,
        "folder": folder,
    }


def inputs():
    word = candidate(
        "word-mainflow01", ROOT / "docs/word-mainflow-development-checks/candidate-01.json", None
    )
    word["folder"] = Path(word["data"]["fixed_runtime_root"])
    task = candidate(
        "task-drafts05", DOCS / "task-drafts-development-checks/candidate05/candidate.json", None
    )
    task["folder"] = Path(task["data"]["runtime_root"])
    stage = candidate(
        "governance-stageA01",
        DOCS
        / "research-backend-checks/fr029-development-checks/candidate-01/model-governance-candidate-01.json",
        DOCS / "research-backend-checks/fr029-development-checks/candidate-01/frozen-inputs",
    )
    hist = candidate(
        "historical-proof02",
        DOCS / "research-backend-checks/historical-authority/candidate-02/candidate.json",
        None,
    )
    hist["folder"] = Path(hist["data"]["runtime_root"])
    historical = candidate(
        "historical-input01",
        DOCS
        / "research-backend-checks/historical-input/candidate-01/historical-input-candidate-01.json",
        DOCS / "research-backend-checks/historical-input/candidate-01/runtime",
    )
    release = candidate(
        "model-release01",
        DOCS / "research-backend-checks/fr029-release/candidate-01/model-release-candidate-01.json",
        DOCS / "research-backend-checks/fr029-release/candidate-01/frozen-inputs",
    )
    score = candidate(
        "score-execution01",
        DOCS
        / "research-backend-checks/score-execution/candidate-01/score-execution-candidate-01.json",
        DOCS / "research-backend-checks/score-execution/candidate-01/runtime",
    )
    selected = {}
    conflicts = []
    actions = []

    def take(layer, row, folder):
        source = folder / row["path"]
        raw = source.read_bytes()
        assert digest(raw) == row["sha256"], source
        previous = selected.get(row["path"])
        if previous and previous["sha256"] != row["sha256"]:
            conflicts.append(
                {
                    "path": row["path"],
                    "previous_layer": previous["layer"],
                    "previous_sha256": previous["sha256"],
                    "selected_layer": layer,
                    "selected_sha256": row["sha256"],
                    "resolution": "take exact reviewed module own source; preserve all other Word guards",
                }
            )
        value = {"path": row["path"], "sha256": row["sha256"], "layer": layer, "input": str(source)}
        selected[row["path"]] = value
        actions.append(value)

    base = json.loads(Path(word["data"]["runtime_manifest"]["path"]).read_text())
    for row in base["sources"]:
        take(word["name"], row, word["folder"])
    for row in task["data"]["sources"]:
        if row["path"] in task["data"]["delta_sources"]:
            take(task["name"], row, task["folder"])
    for row in stage["data"]["sources"]:
        take(stage["name"], row, stage["folder"])
    names = [
        x["path"]
        for x in hist["data"]["sources"]
        if x["path"].startswith(
            (
                "apps/api/historical_routes.py",
                "packages/model_governance/historical_",
                "deploy/sql/historical-backtest.sql",
                "tests/test_historical_context_isolation.py",
                "tests/test_model_governance_historical_",
            )
        )
    ]
    for row in hist["data"]["sources"]:
        if row["path"] in names:
            take(hist["name"], row, hist["folder"])
    for module in [historical, release, score]:
        for row in module["data"]["sources"]:
            take(module["name"], row, module["folder"])
    common = [
        "contracts",
        "repository",
        "evaluation",
        "intake",
        "leakage",
        "purpose_runtime",
        "statistics",
    ]
    for name in common:
        path = f"packages/model_governance/{name}.py"
        references = []
        for module in [hist, historical, release, score]:
            rows = module["data"].get("reference_inputs", module["data"]["sources"])
            row = next((x for x in rows if x["path"] == path), None)
            if row:
                references.append((module["name"], row["sha256"]))
        assert len({sha for _, sha in references}) == 1, (path, references)
        row = next(x for x in score["data"]["reference_inputs"] if x["path"] == path)
        take(
            "score01-exact-shared-dependency", row, Path(score["path"]).parent / "reference-inputs"
        )
    for row in score["data"]["reference_inputs"]:
        if row["path"] in selected and row["path"].startswith("packages/model_governance/"):
            assert selected[row["path"]]["sha256"] == row["sha256"], row["path"]
    fresh = json.loads((DOCS / "word-mainflow-environment03/fresh-initialization.json").read_text())
    sql = fresh["ordered_sql"] + [
        {"path": "deploy/sql/score-execution.sql", "sha256": score["data"]["sql"]["sha256"]}
    ]
    for row in sql:
        if row["path"] not in selected:
            found = False
            for module in [score, release, historical, stage, hist]:
                for folder in [module["folder"], Path(module["path"]).parent / "reference-inputs"]:
                    source = folder / row["path"]
                    if source.exists() and digest(source.read_bytes()) == row["sha256"]:
                        take(module["name"] + "-exact-sql-dependency", row, folder)
                        found = True
                        break
                if found:
                    break
            assert found, ("missing exact initialized SQL", row["path"])
        assert selected[row["path"]]["sha256"] == row["sha256"], row["path"]
    modules = [word, task, stage, hist, historical, release, score]
    return {
        "status": "recipe awaiting composition implementation checks",
        "candidates": [{k: m[k] for k in ("name", "path", "sha256")} for m in modules],
        "base_source_count": len(base["sources"]),
        "source_count_before_composition_delta": len(selected),
        "overlaps": conflicts,
        "ordered_copy_actions": actions,
        "selected_inputs": sorted(selected.values(), key=lambda x: x["path"]),
        "ordered_fresh_sql": sql,
        "excluded": [
            "unreviewed new A2",
            "moving TechnicalScale",
            "private env/cache/runtime journals",
        ],
        "lifecycle": "mount exact Word base lifecycle router; common/producer guards remain Word versions",
        "core_guards": "Word mainflow base wins all historic observed older API/Worker/runtime references",
    }


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    recipe = inputs()
    path = OUT / "recipe-01.json"
    path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + "\n")
    print(
        {
            "recipe": str(path),
            "sha256": digest(path.read_bytes()),
            "selected": recipe["source_count_before_composition_delta"],
            "overlaps": len(recipe["overlaps"]),
            "fresh_sql_count": len(recipe["ordered_fresh_sql"]),
        }
    )
