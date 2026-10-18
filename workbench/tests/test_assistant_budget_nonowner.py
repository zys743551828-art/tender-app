"""Opt-in fresh helper + real restricted API/Worker; explicit offline model transport."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from deploy import bootstrap_fresh as fresh

EXTRA_SQL = (
    "packages/assistant/sql/assistant.sql",
    "packages/assistant/sql/live-facts.sql",
    "packages/assistant/sql/intent-budget.sql",
)
SYNTHETIC_SESSION = "explicit-nonowner-test-session"
SYNTHETIC_CSRF = "explicit-nonowner-test-csrf"


def record_evidence(event, value):
    location = os.environ.get("FUSION_NONOWNER_RECEIPT")
    if location:
        with Path(location).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, "value": value}) + "\n")


def read_profile(path):
    return {
        key: shlex.split(value)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for key, value in [line.split("=", 1)]
    }


def child_environment(role, dsn):
    # The orchestrator owns fresh credentials. Each business subprocess receives one DSN.
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(fresh.ROOT),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "WORKBENCH_ENV_FILE": "explicit-nonowner-test-no-business-profile",
        "APP_ORIGIN": "http://127.0.0.1:19971",
        "SESSION_SECRET": "explicit-offline-synthetic-session-secret",
        role.upper() + "_DATABASE_DSN": dsn,
    }


def run_child(world, role, mode, payload=None):
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--child", mode],
        input=json.dumps(payload or {}),
        text=True,
        capture_output=True,
        cwd=fresh.ROOT,
        env=child_environment(role, world[role.upper() + "_DATABASE_DSN"]),
        timeout=45,
        check=False,
    )
    # Child errors contain only synthetic SQL/identifiers; never include its environment/DSN.
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    if mode in {"execute", "inspect", "publish", "probe", "tick"}:
        record_evidence(role + ":" + mode, value)
    return value


@pytest.fixture(scope="module")
def restricted_world():
    owner_dsn = os.environ.get("FUSION_NONOWNER_OWNER_DSN")
    if not owner_dsn:
        pytest.skip("Explicit isolated PG17 owner bootstrap URI required")
    assert os.name == "posix", "Actual helper file-mode contract requires the Linux3.12 harness"
    assert sys.version_info[:2] == (3, 12)
    owner = fresh.owner_parameters(owner_dsn)
    assert owner["dbname"] == "postgres"
    # Never accept the host business endpoints; the harness supplies its internal PG hostname.
    assert owner["host"] == "fusion-nonowner-postgres"
    assert owner["port"] == "5432"
    name = "nb" + uuid4().hex[:10]
    database = "tender_checks_" + name
    private = fresh.ROOT / ".local"
    private.mkdir(mode=0o700, exist_ok=True)
    assert not private.is_symlink() and not private.stat().st_mode & 0o077
    base = private / (name + "-base.env")
    fresh.write_private(
        base,
        {"OWNER_DATABASE_DSN": owner_dsn, "OBJECT_STORE_PREFIX": "explicit-offline-nonowner"},
    )
    paths = [
        base,
        *(
            private / (name + suffix)
            for suffix in ("-init.env", "-checks.env", "-assistant_budget_admin.env")
        ),
    ]
    expected_prefix = "twb_checks_" + name + "_"
    with psycopg.connect(owner_dsn, autocommit=True) as c:
        assert 170000 <= c.info.server_version < 180000
        assert (
            c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None
        )
        before = c.execute(
            "SELECT rolname,rolcanlogin,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=ANY(%s) ORDER BY rolname",
            ([*fresh.GROUPS, "tender_assistant_budget_admin"],),
        ).fetchall()
        assert {r[0] for r in before} == {*fresh.GROUPS, "tender_assistant_budget_admin"}
        assert not any(any(r[1:]) for r in before)
    try:
        receipt = fresh.bootstrap(
            base_profile=base,
            name=name,
            extensions=[
                (fresh.ROOT / p, fresh.reviewed_sql(fresh.ROOT / p).sha256) for p in EXTRA_SQL
            ],
            assistant_budget_admin=True,
            app_origin="http://127.0.0.1:19971",
        )
        paths.extend(fresh.ROOT / p for p in receipt["profiles"].values())
        business = read_profile(fresh.ROOT / receipt["profiles"]["business"])
        assert "OWNER_DATABASE_DSN" not in business
        assert "ASSISTANT_BUDGET_ADMIN_DATABASE_DSN" not in business
        assert "DEEPSEEK_API_KEY" not in business
        assert business["KAFKA_BOOTSTRAP_SERVERS"] == ""
        admin_profile = fresh.ROOT / receipt["profiles"]["assistant_budget_admin"]
        assert set(read_profile(admin_profile)) == {"ASSISTANT_BUDGET_ADMIN_DATABASE_DSN"}
        record_evidence(
            "fresh_sql_and_roles",
            {
                "ordered_sql": receipt["ordered_sql"],
                "five_nonowner_logins_verified": receipt[
                    "all_created_login_connections_verified_before_business_profiles"
                ],
                "business_admin_owner_dsn_isolation": True,
            },
        )
        yield business | {"receipt": receipt, "admin_profile": admin_profile, "private": private}
    finally:
        # Only resources named by this fresh nonce are removed. Shared capability roles survive.
        init = private / (name + "-init.env")
        if init.exists():
            paths.append(init)
            values = read_profile(init)
            logins = []
            for key, value in values.items():
                if key.endswith("_DATABASE_DSN") and key != "OWNER_DATABASE_DSN":
                    fields = conninfo_to_dict(value)
                    assert fields["dbname"] == database
                    login = fields["user"]
                    assert isinstance(login, str) and login.startswith(expected_prefix)
                    logins.append(login)
            with psycopg.connect(owner_dsn, autocommit=True) as c:
                c.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database)
                    )
                )
                for login in logins:
                    c.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(login)))
                after = c.execute(
                    "SELECT rolname,rolcanlogin,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=ANY(%s) ORDER BY rolname",
                    ([*fresh.GROUPS, "tender_assistant_budget_admin"],),
                ).fetchall()
                assert after == before
                assert (
                    c.execute("SELECT FROM pg_database WHERE datname=%s", (database,)).fetchone()
                    is None
                )
                assert (
                    c.execute("SELECT FROM pg_roles WHERE rolname=ANY(%s)", (logins,)).fetchone()
                    is None
                )
        for path in set(paths):
            path.unlink(missing_ok=True)
        record_evidence(
            "cleanup",
            {
                "nonce_database_absent": True,
                "nonce_logins_absent": True,
                "private_profiles_absent": all(not path.exists() for path in paths),
                "capability_groups_unchanged": True,
            },
        )


def configure(world, kind, value, source=None):
    path = world["private"] / ("mock-budget-" + uuid4().hex + ".json")
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    args = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "packages.assistant.budget_admin",
        kind,
        "--profile",
        str(world["admin_profile"]),
        "--input",
        str(path),
    ]
    source_path = None
    if source is not None:
        source_path = path.with_suffix(".source")
        source_path.write_bytes(source)
        source_path.chmod(0o600)
        args.extend(["--source-document", str(source_path)])
    env = child_environment("unused", "unused")
    env.pop("UNUSED_DATABASE_DSN")
    try:
        result = subprocess.run(
            args, cwd=fresh.ROOT, env=env, capture_output=True, text=True, timeout=20, check=False
        )
        assert result.returncode == 0, result.stderr
        assert (
            json.loads(result.stdout.replace("'", '"').replace("True", "true"))[
                "real_provider_attempts"
            ]
            == 0
        )
    finally:
        path.unlink()
        if source_path:
            source_path.unlink()


@pytest.fixture(scope="module")
def tariff(restricted_world):
    source = b"EXPLICIT SYNTHETIC OFFLINE TARIFF; NO REAL PAYMENT AUTHORITY"
    clock = datetime.now(timezone.utc)
    configure(
        restricted_world,
        "price",
        {
            "id": str(uuid4()),
            "version": "mock-" + uuid4().hex,
            "provider": "deepseek",
            "model": "deepseek-flash",
            "currency": "USD",
            "amount_scale": 1000000000,
            "input_per_million_minor": 1000000,
            "output_per_million_minor": 1000000,
            "input_hard_ceiling": 2097152,
            "output_hard_ceiling": 8192,
            "source_kind": "explicit_mock_fixture",
            "source_uri": "https://synthetic.invalid/tariff",
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "verified_at": clock.isoformat(),
            "valid_from": (clock - timedelta(hours=1)).isoformat(),
            "valid_until": (clock + timedelta(hours=1)).isoformat(),
        },
        source,
    )
    return restricted_world


def prepared(world):
    identifiers = run_child(world, "api", "seed_api")
    identifiers |= run_child(world, "worker", "seed_worker", identifiers)
    identifiers |= run_child(world, "api", "confirm_api", identifiers)
    clock = datetime.now(timezone.utc)
    for scope, owner in [
        ("global", "assistant"),
        ("member", identifiers["actor"]),
        ("project", identifiers["canonical_project_key"]),
    ]:
        configure(
            world,
            "limit",
            {
                "id": str(uuid4()),
                "scope": scope,
                "owner_key": owner,
                "currency": "USD",
                "revision": 1 if scope != "global" else int(clock.timestamp() * 1000000),
                "limit_minor": 1000000000,
                "window_from": (clock - timedelta(hours=1)).isoformat(),
                "window_until": (clock + timedelta(hours=1)).isoformat(),
                "configured_reason": "explicit offline test only",
            },
        )
    return identifiers


def test_fresh_receipt_and_real_restricted_capabilities(restricted_world):
    receipt = restricted_world["receipt"]
    assert [x["path"] for x in receipt["ordered_sql"]] == [*fresh.BASE_SQL, *EXTRA_SQL]
    assert len(receipt["logins"]) == 5
    assert receipt["all_created_login_connections_verified_before_business_profiles"]
    for role in ("api", "worker"):
        probe = run_child(restricted_world, role, "probe", {"role": role})
        assert not probe["owns"] and not probe["superuser"]
        assert not probe["direct_job_authority"] and not probe["direct_live_fact"]
        assert not probe["write_prices"] and not probe["write_limits"]
        assert probe["one_business_dsn"]


@pytest.mark.parametrize("scope", ["project", "global"])
def test_native_nonowner_answer_publish_and_replay(tariff, scope):
    ids = prepared(tariff)
    accepted = run_child(tariff, "api", "accept", ids | {"scope": scope})
    assert accepted["status"] == 202, accepted
    worker = run_child(tariff, "worker", "execute", accepted | {"scope": scope})
    assert worker["calls"] == 1 and worker["second_calls"] == 0
    result = run_child(tariff, "api", "publish", ids | accepted | {"scope": scope})
    assert result["published"] and result["history_count"] == 2
    assert result["budget_state"] == "settled" and result["settled_minor"] == 32
    assert result["dispatch_events"] == 1 and result["native_calls"] == 1
    replay = run_child(tariff, "api", "replay", ids | accepted | {"scope": scope})
    assert replay["status"] == 202 and replay["id"] == accepted["id"]


def test_source_withdrawn_before_worker_dispatch_has_no_model_attempt(tariff):
    ids = prepared(tariff)
    accepted = run_child(tariff, "api", "accept", ids | {"scope": "project"})
    assert accepted["status"] == 202, accepted
    run_child(tariff, "worker", "withdraw", ids)
    worker = run_child(tariff, "worker", "execute", accepted | {"scope": "project"})
    assert worker["calls"] == worker["second_calls"] == 0
    result = run_child(tariff, "api", "inspect", accepted | {"scope": "project"})
    assert result["dispatch_events"] == result["native_calls"] == 0
    assert result["budget_state"] == "held"
    recovered = run_child(tariff, "api", "tick", accepted | {"scope": "project"})
    assert recovered["budget_state"] == "released" and recovered["settled_minor"] == 0
    assert recovered["dispatch_events"] == recovered["native_calls"] == 0


def test_unknown_native_result_remains_held_and_duplicate_never_reissues(tariff):
    ids = prepared(tariff)
    accepted = run_child(tariff, "api", "accept", ids | {"scope": "global"})
    assert accepted["status"] == 202, accepted
    worker = run_child(tariff, "worker", "execute", accepted | {"scope": "global", "timeout": True})
    assert worker["calls"] == 1 and worker["second_calls"] == 0
    result = run_child(tariff, "api", "inspect", accepted | {"scope": "global"})
    assert result["budget_state"] == "unknown" and result["held_minor"] > 0
    assert result["dispatch_events"] == result["native_calls"] == 1
    recovered = run_child(tariff, "api", "tick", accepted | {"scope": "global"})
    assert recovered["budget_state"] == "unknown"
    assert recovered["held_minor"] == result["held_minor"]
    replay = run_child(tariff, "api", "replay", ids | accepted | {"scope": "global"})
    assert replay["status"] == 202 and replay["id"] == accepted["id"]


def _seed_api():
    from packages.domain.runtime import connection, secret_hash
    from packages.identity.repository import record_binding, register_bidder

    actor, bid, project, lot, round_id, blob, version = [uuid4() for _ in range(7)]
    with connection() as c:
        c.execute(
            "INSERT INTO members(id,display_name) VALUES(%s,'synthetic nonowner actor')", (actor,)
        )
        bidder = register_bidder(
            c, actor, "synthetic nonowner bidder", "explicit test registration", None
        )["id"]
        c.execute(
            "INSERT INTO bids(id,title,settings,created_by) VALUES(%s,'synthetic nonowner bid','{}',%s)",
            (bid, actor),
        )
        c.execute(
            "INSERT INTO engineering_projects(id,title) VALUES(%s,'synthetic nonowner engineering')",
            (project,),
        )
        c.execute("INSERT INTO engineering_lots VALUES(%s,%s,'lot A')", (lot, project))
        c.execute(
            "INSERT INTO bid_rounds(id,engineering_project_id,lot,lot_id,round_no) VALUES(%s,%s,'lot A',%s,1)",
            (round_id, project, lot),
        )
        c.execute(
            "INSERT INTO bid_profiles(bid_id,round_id,bidder_id,phase) VALUES(%s,%s,%s,'preparation')",
            (bid, round_id, bidder),
        )
        record_binding(
            c, bid, actor, None, reason="explicit synthetic identity confirmation", confirmed=True
        )
        c.execute("INSERT INTO stream_heads(id,bid_id) VALUES(%s,%s)", (uuid4(), bid))
        c.execute("INSERT INTO review_slots(bid_id,revision) VALUES(%s,1)", (bid,))
        content = b"synthetic original nonowner page"
        c.execute(
            "INSERT INTO blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,%s,'application/pdf')",
            (
                blob,
                hashlib.sha256(str(version).encode()).hexdigest(),
                "synthetic/" + str(version),
                len(content),
            ),
        )
        c.execute(
            "INSERT INTO document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) VALUES(%s,%s,%s,'synthetic.pdf',now(),'bid_body',%s)",
            (version, bid, blob, actor),
        )
        c.execute(
            "INSERT INTO sessions(id,member_id,token_digest,csrf_digest,expires_at) VALUES(%s,%s,%s,%s,now()+interval '1 hour')",
            (
                uuid4(),
                actor,
                secret_hash(str(actor) + SYNTHETIC_SESSION),
                hashlib.sha256(SYNTHETIC_CSRF.encode()).hexdigest(),
            ),
        )
    return {"actor": actor, "bid": bid, "version": version}


def _seed_worker(payload):
    from packages.domain.runtime import connection, sha
    from packages.rag.indexing import ensure_parse_sources

    parse, evidence = uuid4(), uuid4()
    bid, version = UUID(payload["bid"]), UUID(payload["version"])
    with connection(True) as c:
        c.execute(
            "INSERT INTO parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) VALUES(%s,%s,%s,%s,%s,1,'complete','[]')",
            (parse, bid, version, "b" * 64, "c" * 64),
        )
        c.execute(
            "INSERT INTO pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) VALUES(%s,%s,1,400,500,0,'usable','[]')",
            (bid, parse),
        )
        text = "synthetic original nonowner page"
        c.execute(
            "INSERT INTO evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) VALUES(%s,%s,%s,1,0,'text',%s,%s)",
            (evidence, bid, parse, text, sha(text)),
        )
        c.execute("UPDATE bid_profiles SET current_body_id=%s WHERE bid_id=%s", (version, bid))
        root, source = ensure_parse_sources(c, bid, parse, publish_readable=True)
    return {"parse": parse, "evidence": evidence, "root": root, "source": source}


def _confirm_api(payload):
    from packages.assistant.intent_identity import IDENTITY_FACTS, project_identity
    from packages.domain.fact_sets import replace_set
    from packages.domain.runtime import connection

    with connection() as c:
        for name in IDENTITY_FACTS:
            replace_set(
                c,
                UUID(payload["bid"]),
                UUID(payload["actor"]),
                "explicit original page basis",
                kind="add",
                new_fact={
                    "subject": "project",
                    "scope": "current bid",
                    "name": name,
                    "value": "synthetic-" + name + ":" + payload["bid"],
                    "unit": None,
                    "evidence_ids": [payload["evidence"]],
                    "reason": "native original-page confirmation",
                },
            )
        identity = project_identity(c, UUID(payload["bid"]))
    return {"canonical_project_key": identity["canonical_project_key"]}


def _api(payload, mode):
    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from apps.api.assistant_routes import router
    from packages.assistant import coordinator
    from packages.domain.providers.deepseek import DeepSeekClient
    from packages.domain.runtime import DomainError, clean, connection

    def no_api_http(request):
        raise AssertionError("API cannot make model HTTP requests")

    provider = DeepSeekClient(
        api_key="explicit-offline-only", transport=httpx.MockTransport(no_api_http)
    )
    patch = pytest.MonkeyPatch()
    patch.setattr(DeepSeekClient, "from_env", classmethod(lambda cls: provider))

    app = FastAPI()
    app.include_router(router)

    @app.exception_handler(DomainError)
    async def error(request, exc):
        return JSONResponse(
            {"code": exc.code, "details": clean(exc.details)}, status_code=exc.status
        )

    headers = {
        "Cookie": "session=" + payload["actor"] + SYNTHETIC_SESSION,
        "Origin": os.environ["APP_ORIGIN"],
        "X-CSRF-Token": SYNTHETIC_CSRF,
        "Idempotency-Key": uuid4().hex,
    }
    global_scope = payload["scope"] == "global"
    base = (
        "/api/v1/assistant/global-conversations"
        if global_scope
        else f"/api/v1/bids/{payload['bid']}/conversations"
    )
    with TestClient(app) as client:
        if mode == "accept":
            main = client.post(base + "/main", json={}, headers=headers)
            assert main.status_code == 200, main.json()
            body = {
                "client_message_id": str(uuid4()),
                "text": "Explicit synthetic question " + uuid4().hex,
                "source_selection": [],
                "max_tokens": 2048,
            }
            path = base + "/" + main.json()["id"] + "/turns"
            headers |= {"If-Match": main.headers["etag"], "Idempotency-Key": uuid4().hex}
            response = client.post(path, json=body, headers=headers)
            result = {
                "status": response.status_code,
                "response": response.json(),
                "body": body,
                "path": path,
                "headers": headers,
                "conversation_id": main.json()["id"],
            }
            if response.status_code == 202:
                result["id"] = response.json()["id"]
                with connection() as c:
                    if global_scope:
                        row = c.execute(
                            "SELECT payload FROM assistant_global_outbox WHERE run_id=%s",
                            (UUID(result["id"]),),
                        ).fetchone()
                    else:
                        row = c.execute(
                            "SELECT payload FROM outbox WHERE operation_id=%s",
                            (UUID(response.json()["operation"]["id"]),),
                        ).fetchone()
                result["message"] = row["payload"]
            return result
        if mode == "replay":
            response = client.post(
                payload["path"], json=payload["body"], headers=payload["headers"]
            )
            return {"status": response.status_code, "id": response.json().get("id")}
        result = coordinator.publish(UUID(payload["id"]))
        history = client.get(base + "/" + payload["conversation_id"] + "/messages", headers=headers)
        assert history.status_code == 200
        return _inspect(payload) | {
            "published": bool(
                result.get("publication") and result["publication"]["state"] == "published"
            ),
            "history_count": len(history.json()["items"]),
        }


def _inspect(payload):
    from packages.domain.runtime import connection

    with connection() as c:
        reservation = c.execute(
            "SELECT state,reserved_minor AS held_minor,charged_minor AS settled_minor FROM assistant_budget_reservations WHERE job_id=%s",
            (UUID(payload["id"]),),
        ).fetchone()
        events = c.execute(
            "SELECT count(*) AS n FROM assistant_budget_events WHERE job_id=%s AND event_type='dispatched'",
            (UUID(payload["id"]),),
        ).fetchone()["n"]
        table, column = (
            ("assistant_global_calls", "run_id")
            if payload["scope"] == "global"
            else ("model_calls", "operation_id")
        )
        target = (
            payload["id"]
            if payload["scope"] == "global"
            else payload["response"]["operation"]["id"]
        )
        count = c.execute(
            sql.SQL("SELECT count(*) AS n FROM {} WHERE {}=%s").format(
                sql.Identifier(table), sql.Identifier(column)
            ),
            (UUID(target),),
        ).fetchone()["n"]
    return {
        "budget_state": reservation["state"],
        "held_minor": reservation["held_minor"],
        "settled_minor": reservation["settled_minor"],
        "dispatch_events": events,
        "native_calls": count,
    }


def _execute(payload):
    import httpx

    from apps.worker import engine
    from packages.assistant import global_runtime
    from packages.domain import storage
    from packages.domain.providers.deepseek import DeepSeekClient

    objects: dict[str, bytes] = {}
    calls = []
    storage.put = lambda key, data, media: objects.__setitem__(key, data)
    storage.get = lambda key: objects[key]

    def transport(request):
        calls.append(json.loads(request.content))
        if payload.get("timeout"):
            raise httpx.ReadTimeout("explicit offline timeout; unknown billing", request=request)
        return httpx.Response(
            200,
            json={
                "id": "mock-" + uuid4().hex,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "answer": "Explicit offline reference answer",
                                    "citations": [],
                                    "issue_suggestions": [],
                                    "tool_proposals": [],
                                    "gaps": ["Synthetic mechanism only"],
                                }
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 20, "total_tokens": 32},
            },
        )

    client = DeepSeekClient(
        api_key="explicit-offline-only", transport=httpx.MockTransport(transport)
    )
    patch = pytest.MonkeyPatch()
    patch.setattr(DeepSeekClient, "from_env", classmethod(lambda cls: client))
    handler = global_runtime.handle if payload["scope"] == "global" else engine.handle
    handler(payload["message"])
    first = len(calls)
    handler(payload["message"])
    return {"calls": first, "second_calls": len(calls) - first, "real_provider_attempts": 0}


def _child(mode, payload):
    from packages.domain.runtime import assert_role, connection

    worker = "WORKER_DATABASE_DSN" in os.environ
    assert sum(key.endswith("_DATABASE_DSN") for key in os.environ) == 1
    assert (
        "OWNER_DATABASE_DSN" not in os.environ
        and "ASSISTANT_BUDGET_ADMIN_DATABASE_DSN" not in os.environ
    )
    assert_role(worker)
    if mode == "seed_api":
        return _seed_api()
    if mode == "seed_worker":
        return _seed_worker(payload)
    if mode == "confirm_api":
        return _confirm_api(payload)
    if mode in {"accept", "replay", "publish"}:
        return _api(payload, mode)
    if mode == "execute":
        return _execute(payload)
    if mode == "inspect":
        return _inspect(payload)
    if mode == "tick":
        from packages.assistant import coordinator

        coordinator.tick([UUID(payload["id"])])
        return _inspect(payload)
    if mode == "withdraw":
        from packages.rag.indexing import withdraw_source

        with connection(True) as c:
            revision = c.execute(
                "SELECT revision FROM retrieval.source_heads WHERE source_id=%s",
                (UUID(payload["root"]),),
            ).fetchone()["revision"]
            withdraw_source(c, UUID(payload["bid"]), UUID(payload["root"]), revision)
        return {"withdrawn": True}
    if mode == "probe":
        with connection(worker) as c:
            return c.execute("""SELECT r.rolsuper AS superuser,
              EXISTS(SELECT FROM pg_class WHERE relnamespace='design'::regnamespace AND relowner=r.oid) AS owns,
              has_function_privilege(current_user,'design.assistant_assert_job_authority(uuid)','EXECUTE') AS direct_job_authority,
              has_function_privilege(current_user,'design.assistant_assert_live_fact(uuid,jsonb)','EXECUTE') AS direct_live_fact,
              has_table_privilege(current_user,'design.assistant_price_versions','INSERT') AS write_prices,
              has_table_privilege(current_user,'design.assistant_budget_versions','INSERT') AS write_limits,
              true AS one_business_dsn FROM pg_roles r WHERE rolname=current_user""").fetchone()
    raise AssertionError("Unknown isolated child mode")


if __name__ == "__main__":
    assert sys.argv[1] == "--child"
    print(json.dumps(_child(sys.argv[2], json.load(sys.stdin)), default=str))
