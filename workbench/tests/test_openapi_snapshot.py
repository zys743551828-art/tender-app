"""The compact snapshot must retain every actual route, schema and generated UI type."""

import gzip
import json
import shutil
import subprocess  # nosec B404 -- fixed local generator and formatter in development checks
import sys
from pathlib import Path

import pytest

from apps.api import export_openapi
from apps.api.main import app

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packages/contracts/fusion-implemented.openapi.json.gz"
GENERATOR = ROOT / "apps/web/scripts/generate-contracts.py"


def test_committed_gzip_contains_the_complete_current_actual_contract():
    compressed = SNAPSHOT.read_bytes()
    actual = export_openapi.implemented_openapi(app)
    assert gzip.decompress(compressed) == export_openapi.snapshot_bytes(actual)
    assert json.loads(gzip.decompress(compressed)) == app.openapi()
    assert compressed == export_openapi.snapshot_bytes(actual, compressed=True)
    assert compressed[3] & 8 == 0  # No original-filename field in the gzip header.
    assert compressed[4:8] == b"\x00\x00\x00\x00"


def test_export_stdout_plain_file_and_path_independent_gzip_are_equivalent(tmp_path, capsys):
    plain = tmp_path / "readable.json"
    first = tmp_path / "first.json.gz"
    second = tmp_path / "another-name.json.gz"
    export_openapi.main([])
    stdout = capsys.readouterr().out.encode("utf-8")
    for path in (plain, first, second):
        export_openapi.main(["--output", str(path)])
    assert capsys.readouterr().out == ""
    assert plain.read_bytes() == stdout
    assert gzip.decompress(first.read_bytes()) == stdout
    assert first.read_bytes() == second.read_bytes()


def _generate(output, source=None):
    command = [sys.executable, str(GENERATOR), "--output", str(output)]
    if source is not None:
        command += ["--openapi", str(source)]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=30)  # nosec B603
    return output.read_bytes()


def test_generator_default_gzip_and_explicit_plain_preserve_all_types_and_capabilities(tmp_path):
    plain = tmp_path / "actual.json"
    plain.write_bytes(gzip.decompress(SNAPSHOT.read_bytes()))
    from_gzip = _generate(tmp_path / "from-gzip.ts")
    from_plain = _generate(tmp_path / "from-plain.ts", plain)
    assert from_gzip.split(b"\n", 1)[1] == from_plain.split(b"\n", 1)[1]
    assert b"export const implementedOperations" in from_gzip
    assert b"export type DocumentParseView" in from_gzip
    assert b"export type PackageReviewReportView" in from_gzip


def test_checked_in_types_equal_formatted_generation_from_complete_snapshot(tmp_path):
    formatter = ROOT / "apps/web/node_modules/prettier/bin/prettier.cjs"
    node = shutil.which("node")
    if not formatter.is_file() or node is None:
        pytest.skip("Locked frontend dependencies and Node are required for the exact byte check")
    generated = tmp_path / "contracts.ts"
    _generate(generated)
    formatted = subprocess.run(  # nosec B603 -- fixed local locked formatter, no shell
        [node, str(formatter), str(generated)],
        cwd=ROOT / "apps/web",
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    assert formatted == (ROOT / "apps/web/src/contracts.ts").read_bytes()
