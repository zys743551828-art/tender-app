"""The opt-in install plan fixes its complete authoring closure before mutations."""

import json
from copy import deepcopy

import pytest

from deploy import authoring_candidate as candidate
from deploy import bootstrap_fresh as fresh
from deploy import create_check_environment as entry


@pytest.fixture
def copied_sql(tmp_path, monkeypatch):
    original = fresh.ROOT
    for relative in (*fresh.BASE_SQL, *candidate.OPTIONAL_SQL):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((original / relative).read_bytes())
    monkeypatch.setattr(fresh, "ROOT", tmp_path)
    return tmp_path


def reseal(document):
    document["digest"] = candidate.digest({k: v for k, v in document.items() if k != "digest"})
    return document


def test_explicit_authoring_plan_is_complete_ordered_and_still_optional():
    base = tuple(fresh.BASE_SQL)
    document = candidate.plan()
    frozen = candidate.checked(document)
    assert tuple(fresh.BASE_SQL) == base
    assert len(base) == 38 and len(frozen) == 46
    assert "deploy/sql/word-adoption-command-receipts.sql" in base
    assert [item["path"] for item in document["base_sql"]] == list(base)
    assert tuple(item.path for item in frozen) == (*base, *candidate.OPTIONAL_SQL)
    assert not set(base) & set(candidate.OPTIONAL_SQL)
    assert all(item.content and item.sha256 for item in frozen)
    assert len(candidate.function_names(frozen)) == 26


@pytest.mark.parametrize("change", ("missing", "reordered", "extra", "digest", "base"))
def test_malformed_plan_is_rejected_before_existing_bootstrap(monkeypatch, change):
    document = deepcopy(candidate.plan())
    if change == "missing":
        document["optional_sql"].pop()
    elif change == "reordered":
        document["optional_sql"][-2:] = reversed(document["optional_sql"][-2:])
    elif change == "extra":
        document["optional_sql"].append(document["optional_sql"][0])
    elif change == "base":
        document["base_sql"].pop()
    reseal(document)
    if change == "digest":
        document["digest"] = "0" * 64

    def forbidden(**kwargs):
        pytest.fail("an invalid candidate must never reach bootstrap")

    monkeypatch.setattr(fresh, "bootstrap", forbidden)
    with pytest.raises(fresh.BootstrapError, match="AUTHORING_CANDIDATE_PLAN_INVALID"):
        candidate.create(document, base_profile="unused", name="unused")


@pytest.mark.parametrize("relative", (candidate.OPTIONAL_SQL[-1], fresh.BASE_SQL[0]))
def test_changed_bytes_are_rejected_before_profile_or_database(copied_sql, monkeypatch, relative):
    document = candidate.plan()
    target = copied_sql / relative
    target.write_bytes(target.read_bytes() + b"\n-- synthetic source change\n")

    def forbidden(*args, **kwargs):
        pytest.fail("changed SQL must fail before a connection")

    monkeypatch.setattr(fresh.psycopg, "connect", forbidden)
    with pytest.raises(fresh.BootstrapError, match="REVIEWED_SQL_DIGEST_MISMATCH"):
        candidate.create(document, base_profile="unused", name="unused")
    assert not (copied_sql / ".local").exists()


@pytest.mark.parametrize("relative", (candidate.OPTIONAL_SQL[0], fresh.BASE_SQL[0]))
def test_bootstrap_rechecks_sha_if_source_changes_after_candidate_validation(
    copied_sql, monkeypatch, relative
):
    document = candidate.plan()
    original = fresh.bootstrap

    def changed(**kwargs):
        target = copied_sql / relative
        target.write_bytes(target.read_bytes() + b"\n-- change after candidate validation\n")
        return original(**kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("bootstrap must verify the plan digest again before connecting")

    monkeypatch.setattr(fresh, "bootstrap", changed)
    monkeypatch.setattr(fresh.psycopg, "connect", forbidden)
    with pytest.raises(fresh.BootstrapError, match="REVIEWED_SQL_(DIGEST|PLAN)_MISMATCH"):
        candidate.create(document, base_profile="unused", name="unused")


def test_plan_writer_and_reader_preserve_digest_and_refuse_ambiguous_json(tmp_path):
    path = tmp_path / "authoring-plan.json"
    candidate.main(["--write-plan", str(path)])
    assert candidate.load(path) == candidate.plan()
    with pytest.raises(FileExistsError):
        candidate.main(["--write-plan", str(path)])
    duplicate = path.read_text().rstrip()[:-1] + ',"digest":"' + "0" * 64 + '"}'
    path.write_text(duplicate)
    with pytest.raises(fresh.BootstrapError, match="AUTHORING_CANDIDATE_PLAN_INVALID"):
        candidate.load(path)


@pytest.mark.parametrize(
    "additional",
    (
        ["--model-purposes"],
        ["--reviewed-sql", "arbitrary.sql", "0" * 64],
        ["--extension-sql", "arbitrary.sql", "--extension-sha256", "0" * 64],
    ),
)
def test_creation_entry_rejects_mixed_candidates_before_reading_profiles(additional):
    with pytest.raises(SystemExit) as error:
        entry.main(
            [
                "--base-init-file",
                "unused.env",
                "--name",
                "probe",
                "--authoring-candidate",
                "unused-plan.json",
                *additional,
            ]
        )
    assert error.value.code == 2


def test_existing_explicit_extension_entry_remains_available(monkeypatch, capsys):
    calls = []

    def bootstrap(**kwargs):
        calls.append(kwargs)
        return {"no_business_process_started": True}

    monkeypatch.setattr(entry, "bootstrap", bootstrap)
    entry.main(["--base-init-file", "unused.env", "--name", "probe"])
    assert calls[0]["extensions"] == []
    assert json.loads(capsys.readouterr().out) == {"no_business_process_started": True}
