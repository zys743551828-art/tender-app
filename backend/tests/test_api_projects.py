"""认证、项目与幂等：通过 HTTP 接口验证（真实 PostgreSQL，内存对象存储）。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

PROJECT = {
    "title": "合肥某道路工程",
    "tender_number": None,
    "lot": "一标段",
    "round": 1,
    "region": "合肥",
    "engineering_type": "市政道路",
    "deadline": None,
}


def test_login_cookie_csrf_and_logout(api_factory, make_member) -> None:  # type: ignore[no-untyped-def]
    make_member("lead")
    api = api_factory()
    assert api.get("/me").status_code == 401
    assert api.http.post("/api/v1/auth/login", json={"username": "lead", "password": "wrong-password-xx"}).status_code == 401
    api.login("lead")
    cookie = api.http.cookies.get("sid")
    assert cookie and api.get("/me").json()["member_id"].startswith("mem_")
    # 缺 CSRF 令牌的写请求被拒绝
    r = api.http.post("/api/v1/projects", json=PROJECT, headers={"Idempotency-Key": "abcdefgh12345"})
    assert r.status_code == 403 and r.json()["code"] == "csrf_failed"
    # 缺幂等键 → 428
    r = api.http.post("/api/v1/projects", json=PROJECT, headers={"X-CSRF-Token": api.csrf})
    assert r.status_code == 428
    assert api.post("/auth/logout").status_code == 204
    assert api.get("/me").status_code == 401  # 会话已撤销，即使还带着旧 cookie


def test_login_failure_is_uniform_and_audited(api_factory, make_member, engine) -> None:  # type: ignore[no-untyped-def]
    from bidwb import db

    make_member("lead")
    api = api_factory()
    unknown = api.http.post("/api/v1/auth/login", json={"username": "nobody", "password": "x" * 12})
    wrong = api.http.post("/api/v1/auth/login", json={"username": "lead", "password": "x" * 12})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["code"] == wrong.json()["code"] == "invalid_credentials"
    with engine.connect() as conn:
        assert db.scalar(conn, "SELECT count(*) FROM audit_events WHERE action='auth.login_failed'") == 2


def test_deactivated_member_loses_access_immediately(api_factory, make_member, engine) -> None:  # type: ignore[no-untyped-def]
    from bidwb import db
    from bidwb.services import auth

    member = make_member("lead")
    api = api_factory().login("lead")
    assert api.get("/me").status_code == 200
    with db.transaction(engine) as conn:
        auth.deactivate_member(conn, member, actor_id=None, request_id="test")
    assert api.get("/me").status_code == 401


def test_create_project_replays_idempotently(api_factory, make_member) -> None:  # type: ignore[no-untyped-def]
    make_member("lead")
    api = api_factory().login("lead")
    first = api.post("/projects", PROJECT, key="create-project-0001")
    again = api.post("/projects", PROJECT, key="create-project-0001")
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert len(api.get("/projects").json()) == 1  # 重放没有重复创建
    other = api.post("/projects", {**PROJECT, "title": "不同请求"}, key="create-project-0001")
    assert other.status_code == 409 and other.json()["code"] == "idempotency_conflict"


def test_only_title_is_required_and_every_member_sees_every_project(api_factory, make_member) -> None:  # type: ignore[no-untyped-def]
    make_member("lead")
    make_member("other")
    owner = api_factory().login("lead")
    created = owner.post("/projects", {"title": "只填名称"})
    assert created.status_code == 200, created.text
    project = created.json()
    assert (project["lot"], project["region"], project["engineering_type"], project["round"]) == (None, None, None, 1)
    other = api_factory().login("other")
    assert other.get(f"/projects/{project['project_id']}").status_code == 200  # 登录即可访问，不区分岗位
    assert [p["project_id"] for p in other.get("/projects").json()] == [project["project_id"]]
    assert other.get("/projects/prj_missing0001").status_code == 404
    assert owner.post("/projects", {"title": " "}).status_code == 422


def test_update_requires_if_match_and_detects_stale(api_factory, make_member) -> None:  # type: ignore[no-untyped-def]
    make_member("lead")
    api = api_factory().login("lead")
    project = api.post("/projects", PROJECT).json()
    pid = project["project_id"]
    assert api.patch(f"/projects/{pid}", {"title": "新名称"}).status_code == 428
    ok = api.patch(f"/projects/{pid}", {"title": "新名称"}, headers={"If-Match": "1"})
    assert ok.status_code == 200 and ok.json()["revision"] == 2 and ok.json()["title"] == "新名称"
    stale = api.patch(f"/projects/{pid}", {"title": "又改"}, headers={"If-Match": "1"})
    assert stale.status_code == 412 and stale.json()["details"]["current_revision"] == 2
    assert api.patch(f"/projects/{pid}", {}, headers={"If-Match": "2"}).status_code == 422


def test_extra_and_invalid_fields_rejected_without_echo(api_factory, make_member) -> None:  # type: ignore[no-untyped-def]
    make_member("lead")
    api = api_factory().login("lead")
    r = api.post("/projects", {**PROJECT, "owner_id": "mem_hacker"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_contract"
    assert "mem_hacker" not in r.text


def test_error_shape_matches_contract(api_factory) -> None:  # type: ignore[no-untyped-def]
    r = api_factory().get("/projects")
    assert r.status_code == 401
    assert set(r.json()) == {"code", "message", "request_id", "retryable", "details"}
    assert r.headers["X-Request-ID"] == r.json()["request_id"]
