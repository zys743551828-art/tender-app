"""CI must never turn missing, failed or skipped native coverage into a pass."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from archived_recovery_inputs import required_archive

from deploy import ci_checks, ci_object_store


def test_junit_preserves_pass_fail_error_and_skip_reasons(tmp_path):
    path = tmp_path / "result.xml"
    path.write_text(
        '<testsuites><testsuite name="first">'
        '<testcase name="success"/>'
        '<testcase name="failure"><failure message="broken"/></testcase>'
        '<testcase name="error"><error message="fixture failed"/></testcase>'
        '<testcase name="external"><skipped message="requires PG"/></testcase>'
        '</testsuite><testsuite name="second">'
        '<testcase name="another external"><skipped message="requires PG"/></testcase>'
        "</testsuite></testsuites>"
    )
    summary = ci_checks.junit_summary(path)
    assert summary == {
        "tests": 5,
        "passed": 1,
        "failures": 1,
        "errors": 1,
        "skipped": 2,
        "skip_reasons": [{"reason": "requires PG", "count": 2}],
    }


@pytest.mark.parametrize("body", ["<testsuites/>", "<unrelated><testcase/></unrelated>"])
def test_empty_or_unrelated_report_cannot_be_a_success(tmp_path, body):
    path = tmp_path / "result.xml"
    path.write_text(body)
    with pytest.raises(ValueError):
        ci_checks.junit_summary(path)


@pytest.mark.parametrize(
    "body",
    [
        '<testcase><skipped message="missing database"/></testcase>',
        "<testcase><failure/></testcase>",
    ],
)
@pytest.mark.parametrize("suite", ["postgres", "authoring"])
def test_native_zero_exit_still_fails_when_report_contains_missing_coverage(
    tmp_path, monkeypatch, body, suite
):
    monkeypatch.setattr(
        ci_checks,
        "postgres_environment",
        lambda **_: {"FUSION_REQUIREMENTS_ADMIN_DSN": "synthetic-bootstrap"},
    )
    monkeypatch.setattr(ci_object_store, "temporary_object_store", lambda *_: nullcontext({}))
    monkeypatch.setattr(ci_checks, "suite_files", lambda _: ["synthetic.py"])
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    def run(args, **kwargs):
        (tmp_path / "junit.xml").write_text("<testsuite>" + body + "</testsuite>")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ci_checks.subprocess, "run", run)
    assert (
        ci_checks.main(
            [
                "--suite",
                suite,
                "--disposable-postgres",
                "--report-dir",
                str(tmp_path),
                "--weed",
                "synthetic-unused-binary",
            ]
        )
        == 1
    )


def test_authoring_requires_explicit_verified_service_binary_before_connecting(monkeypatch):
    def forbidden(**_):
        raise AssertionError("must validate arguments before connecting to PostgreSQL")

    monkeypatch.setattr(ci_checks, "postgres_environment", forbidden)
    with pytest.raises(SystemExit) as error:
        ci_checks.main(["--suite", "authoring", "--disposable-postgres"])
    assert error.value.code == 2


def test_stale_report_cannot_replace_a_crashed_run(tmp_path, monkeypatch):
    (tmp_path / "junit.xml").write_text('<testsuite><testcase name="stale pass"/></testsuite>')
    for name in ("summary.json", "summary.md", "s3.log"):
        (tmp_path / name).write_text("stale successful evidence")
    monkeypatch.setattr(ci_checks.subprocess, "run", lambda *_, **__: SimpleNamespace(returncode=2))
    assert ci_checks.main(["--suite", "unit", "--report-dir", str(tmp_path)]) == 2
    assert not any(
        (tmp_path / name).exists() for name in ("junit.xml", "summary.json", "summary.md", "s3.log")
    )


def test_test_child_does_not_inherit_service_or_paid_provider_credentials(monkeypatch):
    for name in (
        "API_DATABASE_DSN",
        "CI_POSTGRES_DSN",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "OBJECT_STORE_SECRET_KEY",
        "WORKBENCH_ENV_FILE",
    ):
        monkeypatch.setenv(name, "private-host-value")
    result = ci_checks.test_environment()
    assert "private-host-value" not in result.values()


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://postgres:synthetic@production.invalid:5432/postgres",
        "host=127.0.0.1 hostaddr=198.51.100.7 port=5432 dbname=postgres user=postgres",
        "host=127.0.0.1 service=external-profile port=5432 dbname=postgres user=postgres",
    ],
)
def test_postgres_requires_explicit_disposable_local_cluster(monkeypatch, dsn):
    monkeypatch.setenv("CI_POSTGRES_DSN", dsn)
    with pytest.raises(ValueError, match="EXPLICIT_DISPOSABLE"):
        ci_checks.postgres_environment(disposable=False)
    with pytest.raises(ValueError, match="EXPLICIT_LOCAL"):
        ci_checks.postgres_environment(disposable=True)


@pytest.mark.parametrize("key", ["PGHOSTADDR", "PGSERVICE"])
def test_ambient_libpq_routing_cannot_override_explicit_local_target(monkeypatch, key):
    monkeypatch.setenv("CI_POSTGRES_DSN", "host=127.0.0.1 port=5432 dbname=postgres user=postgres")
    monkeypatch.setenv(key, "untrusted-host-value")
    with pytest.raises(ValueError, match="EXPLICIT_LOCAL"):
        ci_checks.postgres_environment(disposable=True)


def test_archived_acceptance_is_skipped_unless_requested_and_missing_input_then_fails(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("RUN_ARCHIVED_RECOVERY", raising=False)
    with pytest.raises(pytest.skip.Exception):
        required_archive("missing-original.json")
    monkeypatch.setenv("RUN_ARCHIVED_RECOVERY", "1")
    with pytest.raises(pytest.fail.Exception, match="missing required input"):
        required_archive("missing-original.json")
