"""Executable import and resource ownership rules for the migrated business slice."""

import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier

from packages.material_jobs.infrastructure import SqlTransactions

ROOT = Path(__file__).parents[1]


def imports(path):
    tree = ast.parse(path.read_text())
    return {
        name
        for node in ast.walk(tree)
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else []
        )
    }


def test_application_imports_only_language_primitives_and_domain_errors():
    actual = imports(ROOT / "packages/material_jobs/application.py")
    assert actual <= {"contextlib", "dataclasses", "typing", "packages.domain.errors"}
    assert not imports(ROOT / "packages/material_jobs/__init__.py")


def test_infrastructure_has_no_http_or_application_composition_dependency():
    actual = imports(ROOT / "packages/material_jobs/infrastructure.py")
    assert not any(
        x.startswith(("apps", "fastapi", "starlette", "httpx", "subprocess")) for x in actual
    )


def test_migrated_http_handlers_cannot_reintroduce_persistence_or_native_io():
    tree = ast.parse((ROOT / "apps/api/package_technical_execution.py").read_text())
    selected = {
        "_qualified_resume",
        "qualified_job_request",
        "qualified_job_read",
        "qualified_execution_state",
    }
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in selected:
            found.add(node.name)
            for inner in ast.walk(node):
                assert not isinstance(inner, (ast.Import, ast.ImportFrom))
                if isinstance(inner, ast.Call):
                    name = ast.unparse(inner.func)
                    assert not name.endswith(
                        (".execute", ".submit", ".prepare", ".authorize", ".current", ".audit")
                    )
                    assert name != "connection"
    assert found == selected


def test_transaction_factory_owns_distinct_connections_and_caches_for_concurrent_use():
    opened = []
    closed = []
    barrier = Barrier(2)

    @contextmanager
    def connect():
        connection = object()
        opened.append(connection)
        try:
            yield connection
        finally:
            closed.append(connection)

    factory = SqlTransactions(connect)

    def task():
        with factory() as tx:
            barrier.wait(timeout=5)
            return tx

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: task(), range(2)))
    assert len(opened) == len(closed) == 2 and opened[0] is not opened[1]
    assert values[0] is not values[1]
    assert values[0]._intents is not values[1]._intents
