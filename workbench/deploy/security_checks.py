"""Fail-closed Bandit coverage gate with two source-pinned, reviewed SQL sites.

The reviewed sites append only literal locking clauses to constant SQL. This is
not a general SQL exemption: any other finding, or any changed source, blocks CI.
No report files are written, so the gate also works on a read-only checkout.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

# Only the fixed local Python/Bandit invocation below is permitted; no shell.
import subprocess  # nosec B404
import sys
from pathlib import Path, PureWindowsPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "deploy/bandit-reviewed-exceptions.json"
TARGETS = ("apps/api", "apps/worker", "packages", "deploy")
ANCHORS = (
    "apps/api/authoring_exact_revisions.py",
    "apps/worker/engine.py",
    "packages/authoring/exact_sources.py",
    "deploy/ci_checks.py",
)
# A baseline cannot grant exceptions to additional files, rules or locations.
REVIEWED_SITES = {
    ("packages/domain/partial_page_selection_repository.py", "B608", 12, "MEDIUM", "MEDIUM"),
    ("packages/model_governance/material_qualification_registry.py", "B608", 38, "MEDIUM", "LOW"),
}
LEVELS = {"LOW", "MEDIUM", "HIGH"}


class SecurityCheckError(ValueError):
    """A stable, non-secret diagnostic for an unverified scan."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SecurityCheckError("BANDIT_JSON_DUPLICATE_KEY")
        value[key] = item
    return value


def _constant(_: str) -> None:
    raise SecurityCheckError("BANDIT_JSON_NONFINITE_NUMBER")


def _json(value: str) -> Any:
    try:
        return json.loads(value, object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, TypeError) as error:
        raise SecurityCheckError("BANDIT_JSON_INVALID") from error


def normalized_filename(filename: Any, root: Path) -> str:
    """Accept native absolute or slash/backslash relative paths only inside root."""
    if not isinstance(filename, str) or not filename or "\x00" in filename:
        raise SecurityCheckError("BANDIT_PATH_INVALID")
    windows = PureWindowsPath(filename)
    # A foreign Windows drive must not become a relative Linux filename. Also
    # reject drive-relative paths (C:foo) and root-relative paths (\\foo).
    if windows.drive and (os.name != "nt" or not windows.is_absolute()):
        raise SecurityCheckError("BANDIT_PATH_INVALID")
    if filename.startswith("\\") and not windows.is_absolute():
        raise SecurityCheckError("BANDIT_PATH_INVALID")
    try:
        path = Path(filename.replace("\\", "/"))
        resolved = (path if path.is_absolute() else root / path).resolve()
        relative = resolved.relative_to(root.resolve()).as_posix()
    except (ValueError, OSError, RuntimeError) as error:
        raise SecurityCheckError("BANDIT_PATH_OUTSIDE_ROOT") from error
    # Windows paths are case-insensitive; Linux paths are not.
    relative = relative.casefold() if os.name == "nt" else relative
    if relative == "." or not relative.endswith(".py"):
        raise SecurityCheckError("BANDIT_PATH_INVALID")
    return relative


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _site(finding: Any, root: Path) -> tuple[str, str, int, str, str]:
    if not isinstance(finding, dict):
        raise SecurityCheckError("BANDIT_FINDING_INVALID")
    filename = normalized_filename(finding.get("filename"), root)
    rule, line = finding.get("test_id"), finding.get("line_number")
    severity, confidence = finding.get("issue_severity"), finding.get("issue_confidence")
    if (
        not isinstance(rule, str)
        or re.fullmatch(r"B\d{3}", rule) is None
        or not isinstance(line, int)
        or not _positive(line)
        or not isinstance(severity, str)
        or severity not in LEVELS
        or not isinstance(confidence, str)
        or confidence not in LEVELS
    ):
        raise SecurityCheckError("BANDIT_FINDING_INVALID")
    return filename, rule, line, severity, confidence


def reviewed_exceptions(root: Path) -> set[tuple[str, str, int, str, str]]:
    try:
        baseline = _json((root / BASELINE).read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as error:
        raise SecurityCheckError("BANDIT_BASELINE_UNREADABLE") from error
    if (
        not isinstance(baseline, dict)
        or set(baseline) != {"version", "reviewed_exceptions"}
        or type(baseline["version"]) is not int
        or baseline["version"] != 1
        or not isinstance(baseline["reviewed_exceptions"], list)
    ):
        raise SecurityCheckError("BANDIT_BASELINE_INVALID")
    reviewed = set()
    fields = {
        "filename",
        "test_id",
        "line_number",
        "issue_severity",
        "issue_confidence",
        "source_sha256",
        "reason",
    }
    for item in baseline["reviewed_exceptions"]:
        if not isinstance(item, dict) or set(item) != fields:
            raise SecurityCheckError("BANDIT_BASELINE_INVALID")
        site = _site(item, root)
        digest, reason = item["source_sha256"], item["reason"]
        if (
            site not in REVIEWED_SITES
            or site in reviewed
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise SecurityCheckError("BANDIT_BASELINE_INVALID")
        try:
            actual = hashlib.sha256((root / site[0]).read_bytes()).hexdigest()
        except OSError as error:
            raise SecurityCheckError("BANDIT_REVIEWED_SOURCE_UNREADABLE") from error
        if actual != digest:
            raise SecurityCheckError("BANDIT_REVIEWED_SOURCE_CHANGED")
        reviewed.add(site)
    if reviewed != REVIEWED_SITES:
        raise SecurityCheckError("BANDIT_BASELINE_INVALID")
    return reviewed


def verify_report(
    report: Any, returncode: int, root: Path, reviewed: set[tuple[str, str, int, str, str]]
) -> tuple[int, int, int, list[tuple[str, str, int, str, str]]]:
    if returncode not in {0, 1}:
        raise SecurityCheckError("BANDIT_TOOL_EXIT_INVALID")
    if not isinstance(report, dict) or not isinstance(report.get("errors"), list):
        raise SecurityCheckError("BANDIT_REPORT_INVALID")
    if report["errors"]:
        raise SecurityCheckError("BANDIT_SCAN_ERRORS")
    metrics, findings = report.get("metrics"), report.get("results")
    if not isinstance(metrics, dict) or not isinstance(findings, list):
        raise SecurityCheckError("BANDIT_REPORT_INVALID")
    totals = metrics.get("_totals")
    if not isinstance(totals, dict) or not _positive(totals.get("loc")):
        raise SecurityCheckError("BANDIT_COVERAGE_EMPTY")
    files = {}
    for filename, metric in metrics.items():
        if filename == "_totals":
            continue
        relative = normalized_filename(filename, root)
        if (
            relative in files
            or not relative.startswith(tuple(target + "/" for target in TARGETS))
            or relative.startswith("packages/parsing/qa/")
            or not isinstance(metric, dict)
            or type(metric.get("loc")) is not int
            or metric["loc"] < 0
        ):
            raise SecurityCheckError("BANDIT_COVERAGE_INVALID")
        files[relative] = metric["loc"]
    if any(not _positive(files.get(anchor)) for anchor in ANCHORS):
        raise SecurityCheckError("BANDIT_COVERAGE_ANCHOR_MISSING")
    if sum(files.values()) != totals["loc"]:
        raise SecurityCheckError("BANDIT_COVERAGE_TOTAL_MISMATCH")
    if returncode != int(bool(findings)):
        raise SecurityCheckError("BANDIT_EXIT_FINDINGS_MISMATCH")
    seen = set()
    blocked = []
    for finding in findings:
        site = _site(finding, root)
        if site in seen or not _positive(files.get(site[0])):
            raise SecurityCheckError("BANDIT_FINDING_COVERAGE_INVALID")
        seen.add(site)
        if site not in reviewed:
            blocked.append(site)
    return totals["loc"], len(files), len(seen & reviewed), sorted(blocked)


def main() -> int:
    try:
        reviewed = reviewed_exceptions(ROOT)
        # Explicit targets, fixed interpreter/module/options, no shell or network.
        # Bandit matches exclusions against os.walk paths without resolving them;
        # both targets and exclusion must be absolute for the QA exclusion to work.
        command = [
            sys.executable,
            "-m",
            "bandit",
            "-q",
            "-ll",
            "-r",
            *(str(ROOT / target) for target in TARGETS),
            "-x",
            str(ROOT / "packages/parsing/qa"),
            "-f",
            "json",
        ]
        result = subprocess.run(  # nosec B603
            command,
            cwd=ROOT,
            capture_output=True,
            encoding="utf-8",
            check=False,
            shell=False,
            timeout=300,
        )
        loc, files, count, blocked = verify_report(
            _json(result.stdout), result.returncode, ROOT, reviewed
        )
    except (SecurityCheckError, OSError, UnicodeError, subprocess.SubprocessError) as error:
        # Never echo source snippets, stderr, raw JSON, paths or tool exceptions.
        code = str(error) if isinstance(error, SecurityCheckError) else "BANDIT_TOOL_FAILED"
        print(f"Security gate failed: {code}", file=sys.stderr)
        return 1
    print(
        f"Bandit coverage: {loc} LOC across {files} files; reviewed={count}; blocked={len(blocked)}"
    )
    for filename, rule, line, severity, confidence in blocked:
        # Validated relative path and structured metadata only, not issue text/code.
        safe_filename = re.sub(r"[^A-Za-z0-9_./-]", "?", filename)
        print(f"Blocked: {safe_filename}:{line} {rule} severity={severity} confidence={confidence}")
    return int(bool(blocked))


if __name__ == "__main__":
    raise SystemExit(main())
