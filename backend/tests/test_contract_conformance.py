"""对外数据结构与 contracts/domain.schema.json 的字段集合、必填性一致；有意的扩展在 EXTENSIONS 中逐条登记。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bidwb import schemas

CONTRACT = Path(__file__).resolve().parents[2] / "contracts/domain.schema.json"

# 响应在契约基础上新增的字段
EXTENSIONS: dict[str, set[str]] = {}
# 契约里以 nullable 必填表示、而实现里允许缺省（None 默认值）的字段
OPTIONAL_IN_IMPL: dict[str, set[str]] = {
    "Revision": {"target_version_id"},
}
# 逐条登记的已知差异：实现与契约不同的地方及原因
KNOWN_DIFFERENCES: dict[str, str] = {
    "Task": "snapshot_id/bundle_id 可为 null：解析、规则提取没有快照，诊断/改稿使用内置方法（见 schema.sql 中 jobs 的 CHECK）",
}


@pytest.mark.skipif(CONTRACT is None or not CONTRACT.exists(), reason="契约文件不在当前工作区")
def test_schemas_match_contract() -> None:
    assert CONTRACT is not None
    defs = json.loads(CONTRACT.read_text(encoding="utf-8")).get("$defs", {})
    problems: list[str] = []
    checked = 0
    for name, spec in defs.items():
        model = getattr(schemas, name, None)
        if model is None or "properties" not in spec:
            continue
        checked += 1
        contract_fields = set(spec["properties"])
        impl = model.model_fields
        impl_fields = set(impl)
        extra = impl_fields - contract_fields - EXTENSIONS.get(name, set())
        missing = contract_fields - impl_fields
        if extra or missing:
            problems.append(f"{name}: 实现多出 {sorted(extra)}，缺少 {sorted(missing)}")
            continue
        required = set(spec.get("required", []))
        impl_required = {f for f, info in impl.items() if info.is_required()} - EXTENSIONS.get(name, set())
        impl_required |= OPTIONAL_IN_IMPL.get(name, set())
        if required != impl_required and name not in KNOWN_DIFFERENCES:
            problems.append(f"{name}: 必填不一致 契约 {sorted(required)} 实现 {sorted(impl_required)}")
    assert checked >= 15, "匹配到的模型过少，检查模型命名"
    assert not problems, "\n".join(problems)


def test_migration_sql_is_identical_to_contract_schema():
    root = Path(__file__).resolve().parents[2]
    assert (root / "backend/migrations/sql/0001_initial.sql").read_bytes() == (root / "contracts/schema.sql").read_bytes()
    assert (root / "backend/migrations/sql/0002_evidence_embeddings.sql").read_bytes() == (
        root / "contracts/evidence-embeddings.sql"
    ).read_bytes()


def test_generated_contracts_are_current() -> None:
    """contracts/openapi.json 与 domain.schema.json 中由代码生成的部分与当前代码一致；不一致时运行 tools/export_contracts.py。"""
    import subprocess
    import sys

    tool = Path(__file__).resolve().parents[1] / "tools/export_contracts.py"
    result = subprocess.run([sys.executable, str(tool), "--check"], capture_output=True, text=True, check=False)  # noqa: S603
    assert result.returncode == 0, result.stderr
