"""Record public contract/registration facts from the exact fixed application root."""

import hashlib
import json
from pathlib import Path

from fastapi.routing import APIRoute

from apps.api.main import app

OUT = Path("/workspace/tender-workbench/docs/application-composition-development-checks")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def collect():
    manifest = json.loads((OUT / "source-preview-01.json").read_text())
    root = Path(manifest["runtime_root"])
    for row in manifest["sources"]:
        assert digest((root / row["path"]).read_bytes()) == row["sha256"], row["path"]
    actual = app.openapi()
    (OUT / "actual-01.openapi.json").write_text(
        json.dumps(actual, ensure_ascii=False, indent=2) + "\n"
    )
    annotated = []
    manual = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods):
            operation = actual["paths"][route.path][method.lower()]
            item = {"path": route.path, "method": method, "operation_id": operation["operationId"]}
            if route.response_model is None:
                manual.append(item)
            else:
                annotated.append(item | {"model": str(route.response_model)})
    base = json.loads(
        Path(
            "/workspace/tender-workbench/docs/word-mainflow-development-checks/actual-02.openapi.json"
        ).read_text()
    )
    changed_base_schemas = [
        name
        for name, schema in base["components"]["schemas"].items()
        if actual["components"]["schemas"].get(name) != schema
    ]
    assert not changed_base_schemas, changed_base_schemas
    new = []
    for path, methods in actual["paths"].items():
        for method, operation in methods.items():
            if method in base["paths"].get(path, {}):
                continue
            new.append({"path": path, "method": method, "operation_id": operation["operationId"]})
            for code, response in operation["responses"].items():
                if code.startswith("2"):
                    assert response.get("content", {}).get("application/json", {}).get("schema")
    value = {
        "runtime_source_count": len(manifest["sources"]),
        "paths": len(actual["paths"]),
        "operations": sum(len(m) for m in actual["paths"].values()),
        "schemas": len(actual["components"]["schemas"]),
        "new_operations": new,
        "unchanged_base_schema_count": len(base["components"]["schemas"]),
        "changed_base_schemas": changed_base_schemas,
        "declared_response_models": annotated,
        "not_annotated_response_models": manual,
        "response_check_scope": "All declared models expanded against final schemas; manual projections only selected real ASGI objects plus prior module evidence, not automatic validation of every response.",
        "source_integrity": "all fixed input hashes matched",
        "actual_sha256": digest((OUT / "actual-01.openapi.json").read_bytes()),
    }
    (OUT / "contract-registration-check-01.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        {
            k: value[k]
            for k in ["runtime_source_count", "paths", "operations", "schemas", "actual_sha256"]
        }
    )


if __name__ == "__main__":
    collect()
