"""Configuration/DB compatibility and ownership without any real secret or database."""

import ast
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier

import pytest

from packages.platform_runtime import configuration, database


def test_defaults_preserve_explicit_values_quotes_comments_and_empty_settings(tmp_path):
    (tmp_path / ".env").write_text(
        "# ignored\nA='quoted # value'\nB=fallback\nC=\nA=later\nno equals\n"
    )
    values = {"B": "explicit"}
    configuration.load_development_defaults(tmp_path, values)
    assert values == {"A": "quoted # value", "B": "explicit", "C": ""}
    assert configuration.required("B", values) == "explicit"
    with pytest.raises(RuntimeError, match="缺少配置 C"):
        configuration.required("C", values)


def test_purpose_marker_never_reads_default_or_marker_path(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("A=synthetic")

    def forbidden(*args, **kwargs):
        pytest.fail("purpose process read configuration")

    monkeypatch.setattr(Path, "read_text", forbidden)
    values = {"WORKBENCH_ENV_FILE": "/nonexistent/not-a-loader"}
    configuration.load_development_defaults(tmp_path, values)
    assert "A" not in values


def test_missing_default_does_nothing_and_empty_mapping_never_falls_back(monkeypatch, tmp_path):
    values = {}
    configuration.load_development_defaults(tmp_path, values)
    monkeypatch.setenv("TEST_ONLY_RUNTIME_KEY", "synthetic")
    with pytest.raises(RuntimeError, match="缺少配置 TEST_ONLY_RUNTIME_KEY"):
        configuration.required("TEST_ONLY_RUNTIME_KEY", values)


class Cancelled(BaseException):
    pass


@pytest.mark.parametrize("worker", [False, True])
@pytest.mark.parametrize("failure", [None, RuntimeError("synthetic failure"), Cancelled()])
def test_connection_is_lazy_role_specific_and_always_released(worker, failure):
    events = []

    class C:
        def execute(self, sql):
            events.append(sql)

    @contextmanager
    def connect(dsn, **kwargs):
        assert kwargs["row_factory"] is database.dict_row
        events.append(("open", dsn))
        try:
            yield C()
            events.append("commit")
        except BaseException:
            events.append("rollback")
            raise
        finally:
            events.append("close")

    expected = "WORKER_DATABASE_DSN" if worker else "API_DATABASE_DSN"

    def lookup(key):
        assert key == expected
        events.append("lookup")
        return "synthetic-dsn"

    manager = database.transaction(worker, lookup=lookup, connector=connect)
    assert not events

    def use():
        with manager:
            assert events[-1] == "SET LOCAL search_path=design,public"
            if failure:
                raise failure

    if failure:
        with pytest.raises(type(failure)):
            use()
    else:
        use()
    assert events[-2:] == ["rollback" if failure else "commit", "close"]


def test_connection_setup_failure_closes_before_exposing_handle():
    closed = []

    class C:
        def execute(self, sql):
            raise RuntimeError("setup failed")

    @contextmanager
    def connect(*args, **kwargs):
        try:
            yield C()
        finally:
            closed.append(True)

    with pytest.raises(RuntimeError, match="setup failed"):
        with database.transaction(lookup=lambda key: "synthetic", connector=connect):
            pytest.fail("setup failure exposed connection")
    assert closed == [True]


def test_compatibility_entry_looks_up_configuration_on_entry(monkeypatch):
    from packages.domain import runtime

    seen = []

    @contextmanager
    def connect(dsn, **kwargs):
        seen.append(dsn)
        yield type("C", (), {"execute": lambda self, sql: None})()

    monkeypatch.setattr(database.psycopg, "connect", connect)
    manager = runtime.connection()
    monkeypatch.setattr(runtime, "required", lambda key: "late-synthetic-value")
    with manager:
        pass
    assert seen == ["late-synthetic-value"]


def test_concurrent_transactions_do_not_share_connections():
    barrier = Barrier(2)
    closed = []

    @contextmanager
    def connect(*args, **kwargs):
        c = type("C", (), {"execute": lambda self, sql: None})()
        try:
            yield c
        finally:
            closed.append(c)

    def use(_):
        with database.transaction(lookup=lambda key: "synthetic", connector=connect) as c:
            barrier.wait(timeout=5)
            return c

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(use, range(2)))
    assert values[0] is not values[1] and len(closed) == 2


def test_new_platform_import_has_no_business_bootstrap_or_domain_dependency():
    root = Path(__file__).parents[1]
    source = """import sys,os
sys.path.insert(0,sys.argv[1])
from pathlib import Path
original=Path.read_text
def checked(path,*args,**kwargs):
    assert path.name != '.env', 'unexpected configuration read'
    return original(path,*args,**kwargs)
Path.read_text=checked
from packages.platform_runtime import configuration,database
assert 'packages.domain.runtime' not in sys.modules
assert 'API_DATABASE_DSN' not in os.environ
"""
    subprocess.run(
        [sys.executable, "-I", "-c", source, str(root)],
        env={"LANG": "C.UTF-8"},
        check=True,
        capture_output=True,
    )  # nosec B603
    for name in ("configuration", "database"):
        tree = ast.parse((root / f"packages/platform_runtime/{name}.py").read_text())
        imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not any(x.startswith(("apps", "packages.domain", "fastapi")) for x in imports)


def test_active_source_guards_cover_all_extracted_runtime_dependencies(monkeypatch):
    from deploy import review_acceptance as acceptance
    from packages.authoring import docx_import_parser as parser

    expected = {
        "packages/platform_runtime/__init__.py",
        "packages/platform_runtime/configuration.py",
        "packages/platform_runtime/database.py",
    }
    assert expected <= set(parser.SOURCE_FILES)
    assert expected <= acceptance.REQUIRED_SOURCES
    changed = parser._source_digests()
    changed["packages/platform_runtime/database.py"] = "0" * 64
    monkeypatch.setattr(parser, "_source_digests", lambda: changed)
    from packages.domain.errors import DomainError

    with pytest.raises(DomainError, match="导入实现文件已变化"):
        parser.method_identity()
