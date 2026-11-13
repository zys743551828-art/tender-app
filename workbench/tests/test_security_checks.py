"""Security CI must prove scan coverage, not merely observe a zero exit code."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy import security_checks as gate

SOURCE_ROOT = gate.ROOT


@pytest.fixture
def scan(tmp_path, monkeypatch):
    paths = set(gate.ANCHORS) | {site[0] for site in gate.REVIEWED_SITES} | {gate.BASELINE}
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((SOURCE_ROOT / relative).read_bytes())
    baseline = json.loads((tmp_path / gate.BASELINE).read_text(encoding="utf-8"))
    findings = [
        {key: value for key, value in item.items() if key not in {"reason", "source_sha256"}}
        for item in baseline["reviewed_exceptions"]
    ]
    metrics = {path: {"loc": 10} for path in sorted(paths - {gate.BASELINE})}
    metrics["_totals"] = {"loc": 10 * len(metrics)}
    report = {"errors": [], "metrics": metrics, "results": findings}
    state = SimpleNamespace(root=tmp_path, report=report, returncode=1, calls=[], stdout=None)

    def run(args, **kwargs):
        state.calls.append((args, kwargs))
        return SimpleNamespace(
            stdout=json.dumps(state.report) if state.stdout is None else state.stdout,
            returncode=state.returncode,
            stderr="synthetic-private-scanner-output",
        )

    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate.subprocess, "run", run)
    return state


def save_baseline(scan, change):
    path = scan.root / gate.BASELINE
    baseline = json.loads(path.read_text(encoding="utf-8"))
    change(baseline)
    path.write_text(json.dumps(baseline), encoding="utf-8")


def test_real_explicit_argv_no_csv_no_shell_no_output_file(scan, capsys):
    assert gate.main() == 0
    assert len(scan.calls) == 1
    args, options = scan.calls[0]
    assert args == [
        sys.executable,
        "-m",
        "bandit",
        "-q",
        "-ll",
        "-r",
        *(str(scan.root / target) for target in gate.TARGETS),
        "-x",
        str(scan.root / "packages/parsing/qa"),
        "-f",
        "json",
    ]
    assert Path(args[args.index("-x") + 1]).is_absolute()
    assert not any("," in item for item in args)
    assert options == {
        "cwd": scan.root,
        "capture_output": True,
        "encoding": "utf-8",
        "check": False,
        "shell": False,
        "timeout": 300,
    }
    assert "60 LOC across 6 files; reviewed=2; blocked=0" in capsys.readouterr().out


@pytest.mark.parametrize("loc", [0, -1, None, True, 1.5, "60"])
def test_zero_or_invalid_total_loc_fails_even_with_zero_exit(scan, loc):
    scan.returncode = 0
    scan.report["results"] = []
    scan.report["metrics"]["_totals"]["loc"] = loc
    assert gate.main() == 1


@pytest.mark.parametrize("anchor", gate.ANCHORS)
@pytest.mark.parametrize("loc", [None, 0, -1, True])
def test_each_coverage_anchor_is_required_with_positive_loc(scan, anchor, loc):
    if loc is None:
        del scan.report["metrics"][anchor]
    else:
        scan.report["metrics"][anchor]["loc"] = loc
    assert gate.main() == 1


def test_missing_anchors_cannot_hide_behind_substantial_total(scan):
    scan.report["metrics"] = {
        "packages/unrelated.py": {"loc": 99999},
        "_totals": {"loc": 99999},
    }
    assert gate.main() == 1


def test_total_must_equal_file_metrics(scan):
    scan.report["metrics"]["_totals"]["loc"] += 1
    assert gate.main() == 1


@pytest.mark.parametrize("body", ["", "not-json", "null", "[]", "{}", '{"errors":[],"errors":[]}'])
def test_empty_malformed_or_incomplete_report_fails(scan, body):
    scan.stdout = body
    assert gate.main() == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("errors", None),
        ("errors", {}),
        ("metrics", []),
        ("results", {}),
    ],
)
def test_malformed_report_fields_fail(scan, key, value):
    scan.report[key] = value
    assert gate.main() == 1


def test_scan_errors_fail_without_echoing_raw_report_or_stderr(scan, capsys):
    scan.report["errors"] = [{"filename": "private-source", "reason": "private-secret"}]
    assert gate.main() == 1
    output = capsys.readouterr()
    assert "BANDIT_SCAN_ERRORS" in output.err
    assert "private" not in output.err + output.out


@pytest.mark.parametrize("returncode", [-9, 2, 127])
def test_unexpected_tool_exit_fails(scan, returncode):
    scan.returncode = returncode
    assert gate.main() == 1


def test_zero_exit_with_findings_is_not_trusted(scan):
    scan.returncode = 0
    assert gate.main() == 1


def test_nonzero_exit_without_findings_is_not_trusted(scan):
    scan.report["results"] = []
    assert gate.main() == 1


@pytest.mark.parametrize(
    "error", [OSError("private-path"), subprocess.TimeoutExpired("private", 300)]
)
def test_tool_start_and_timeout_errors_fail_without_raw_exception(scan, monkeypatch, capsys, error):
    def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.main() == 1
    assert capsys.readouterr().err == "Security gate failed: BANDIT_TOOL_FAILED\n"


def test_new_finding_in_same_file_is_not_covered_by_review(scan, capsys):
    finding = copy.deepcopy(scan.report["results"][0])
    finding["line_number"] += 1
    finding["code"] = "private code containing a secret"
    finding["issue_text"] = "private text"
    scan.report["results"].append(finding)
    assert gate.main() == 1
    output = capsys.readouterr()
    assert "reviewed=2; blocked=1" in output.out
    assert "partial_page_selection_repository.py:13 B608" in output.out
    assert "private" not in output.out + output.err


@pytest.mark.parametrize(
    "key,value",
    [
        ("test_id", "B602"),
        ("line_number", 14),
        ("issue_severity", "HIGH"),
        ("issue_confidence", "HIGH"),
        ("filename", gate.ANCHORS[0]),
    ],
)
def test_review_only_matches_exact_path_rule_line_severity_and_confidence(scan, key, value):
    scan.report["results"][0][key] = value
    assert gate.main() == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("test_id", "B608\nprivate"),
        ("line_number", True),
        ("line_number", "12"),
        ("issue_severity", None),
        ("issue_confidence", []),
        ("filename", None),
    ],
)
def test_malformed_findings_fail(scan, key, value):
    scan.report["results"][0][key] = value
    assert gate.main() == 1


def test_duplicate_finding_fails(scan):
    scan.report["results"].append(copy.deepcopy(scan.report["results"][0]))
    assert gate.main() == 1


def test_unscanned_finding_fails(scan):
    scan.report["results"][0]["filename"] = "packages/unscanned.py"
    assert gate.main() == 1


def test_changed_reviewed_source_fails_before_scanner_even_if_no_findings(scan):
    path = scan.root / scan.report["results"][0]["filename"]
    path.write_bytes(path.read_bytes() + b"\n# changed\n")
    scan.report["results"] = []
    scan.returncode = 0
    assert gate.main() == 1
    assert scan.calls == []


def test_missing_reviewed_source_fails(scan):
    (scan.root / scan.report["results"][0]["filename"]).unlink()
    assert gate.main() == 1
    assert scan.calls == []


def test_stale_baseline_hash_fails(scan):
    save_baseline(
        scan, lambda value: value["reviewed_exceptions"][0].update(source_sha256="0" * 64)
    )
    assert gate.main() == 1
    assert scan.calls == []


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value["reviewed_exceptions"].pop(),
        lambda value: value["reviewed_exceptions"].append(
            copy.deepcopy(value["reviewed_exceptions"][0])
        ),
        lambda value: value["reviewed_exceptions"][0].update(filename="packages/unreviewed.py"),
        lambda value: value["reviewed_exceptions"][0].update(line_number=13),
        lambda value: value["reviewed_exceptions"][0].update(test_id="B602"),
        lambda value: value["reviewed_exceptions"][0].update(reason=""),
        lambda value: value["reviewed_exceptions"][0].update(source_sha256="invalid"),
        lambda value: value.update(version=True),
        lambda value: value.update(extra="unknown"),
    ],
)
def test_baseline_cannot_expand_or_invalidate_review(scan, change):
    save_baseline(scan, change)
    assert gate.main() == 1
    assert scan.calls == []


@pytest.mark.parametrize("body", ["", "not-json", "[]", "null", "{}"])
def test_malformed_baseline_fails(scan, body):
    (scan.root / gate.BASELINE).write_text(body, encoding="utf-8")
    assert gate.main() == 1
    assert scan.calls == []


def test_missing_baseline_fails(scan):
    (scan.root / gate.BASELINE).unlink()
    assert gate.main() == 1
    assert scan.calls == []


@pytest.mark.parametrize("style", ["backslash", "absolute", "dot_relative"])
def test_native_absolute_and_windows_or_linux_relative_paths_match_review(scan, style):
    def transform(path):
        if style == "backslash":
            return path.replace("/", "\\")
        if style == "absolute":
            return str(scan.root / path)
        return "./" + path

    scan.report["metrics"] = {
        key if key == "_totals" else transform(key): value
        for key, value in scan.report["metrics"].items()
    }
    for finding in scan.report["results"]:
        finding["filename"] = transform(finding["filename"])
    assert gate.main() == 0


@pytest.mark.parametrize(
    "filename",
    [
        "../outside.py",
        "..\\outside.py",
        "C:relative.py",
        "\\root-relative.py",
        "packages/not-python.txt",
        "packages/a\x00.py",
        "",
        ".",
    ],
)
@pytest.mark.parametrize("field", ["metrics", "results"])
def test_unsafe_or_invalid_paths_fail(scan, filename, field):
    if field == "metrics":
        scan.report["metrics"][filename] = {"loc": 1}
    else:
        scan.report["results"][0]["filename"] = filename
    assert gate.main() == 1


def test_absolute_path_outside_root_fails(scan):
    scan.report["results"][0]["filename"] = str(scan.root.parent / "outside.py")
    assert gate.main() == 1


def test_foreign_windows_absolute_path_cannot_become_linux_relative_path(scan):
    if os.name == "nt":
        path = "Z:\\unrelated\\packages\\domain\\partial_page_selection_repository.py"
    else:
        path = "C:\\unrelated\\packages\\domain\\partial_page_selection_repository.py"
    scan.report["results"][0]["filename"] = path
    assert gate.main() == 1


def test_excluded_qa_archive_must_not_be_scanned(scan):
    scan.report["metrics"]["packages/parsing/qa/archived.py"] = {"loc": 1}
    assert gate.main() == 1


def test_path_alias_cannot_duplicate_coverage(scan):
    scan.report["metrics"]["./" + gate.ANCHORS[0]] = {"loc": 10}
    assert gate.main() == 1


def test_nonfinite_json_is_not_accepted(scan):
    scan.stdout = '{"errors":[],"metrics":{"_totals":{"loc":NaN}},"results":[]}'
    assert gate.main() == 1


def test_gate_has_no_mandatory_output_writes(scan, monkeypatch):
    def write(*args, **kwargs):
        pytest.fail("security gate must not write a report or update baseline")

    monkeypatch.setattr(Path, "write_text", write)
    monkeypatch.setattr(Path, "write_bytes", write)
    assert gate.main() == 0
