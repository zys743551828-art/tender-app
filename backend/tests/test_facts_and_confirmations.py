"""事实录入与读取、提交登记可选的负责人确认记录。"""

from __future__ import annotations

import pytest

from bidwb import db
from tests.pdfs import make_pdf
from tests.test_files_and_parse import _setup, _upload

pytestmark = pytest.mark.integration


def test_fact_entry_and_listing(api_factory, make_member, store, engine) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    assert api.get(f"/projects/{pid}/facts").json() == {"fact_set_id": None, "items": []}
    _upload(api, store, pid, make_pdf([["第一章 资料", "本公司项目经理持有一级建造师证书。"]]), role="supplement")
    with engine.begin() as conn:  # 证据通常由解析任务产生；这里直接植入一条，聚焦事实本身
        version = db.scalar(conn, "SELECT id FROM file_versions LIMIT 1")
        db.run(
            conn,
            """INSERT INTO parses(id,project_id,file_version_id,parser_version,page_count,coverage,gaps_json,artifact_id,created_at)
                        SELECT 'prs_fact0001',:p,:v,'t',1,'complete','[]'::jsonb,artifact_id,now() FROM file_versions WHERE id=:v""",
            {"p": pid, "v": version},
        )
        db.run(
            conn,
            """INSERT INTO evidence(id,project_id,file_version_id,parse_id,physical_page,quote,kind,seq,semantic_review)
                        VALUES ('evd_fact0001',:p,:v,'prs_fact0001',1,'项目经理持有一级建造师证书','text',0,'pending')""",
            {"p": pid, "v": version},
        )
    make_member("eng")
    engineer = api_factory().login("eng")
    body = {
        "name": "项目经理资质",
        "subject": "项目经理",
        "scope": "本项目",
        "value_decimal": None,
        "unit": None,
        "statement": "项目经理持有一级建造师证书",
        "evidence_ids": ["evd_fact0001"],
    }
    assert engineer.post(f"/projects/{pid}/facts", body).status_code == 200
    listed = engineer.get(f"/projects/{pid}/facts").json()
    assert (
        len(listed["items"]) == 1
        and listed["items"][0]["confirmation"] == "confirmed"
        and listed["items"][0]["evidence_ids"] == ["evd_fact0001"]
    )
    engineer.post(f"/projects/{pid}/facts", {**body, "name": "安全员证书", "statement": "安全员持有 C 证"})
    assert len(engineer.get(f"/projects/{pid}/facts").json()["items"]) == 2  # 新事实集带上此前的条目


def test_withdraw_fact(api_factory, make_member, store, engine) -> None:  # type: ignore[no-untyped-def]
    api, pid = _setup(api_factory, make_member)
    _upload(api, store, pid, make_pdf([["第一章 资料", "本公司项目经理持有一级建造师证书。"]]), role="supplement")
    with engine.begin() as conn:
        version = db.scalar(conn, "SELECT id FROM file_versions LIMIT 1")
        db.run(
            conn,
            """INSERT INTO parses(id,project_id,file_version_id,parser_version,page_count,coverage,gaps_json,artifact_id,created_at)
                        SELECT 'prs_fact0002',:p,:v,'t',1,'complete','[]'::jsonb,artifact_id,now() FROM file_versions WHERE id=:v""",
            {"p": pid, "v": version},
        )
        db.run(
            conn,
            """INSERT INTO evidence(id,project_id,file_version_id,parse_id,physical_page,quote,kind,seq,semantic_review)
                        VALUES ('evd_fact0002',:p,:v,'prs_fact0002',1,'项目经理持有一级建造师证书','text',0,'pending')""",
            {"p": pid, "v": version},
        )
    make_member("eng")
    eng = api_factory().login("eng")
    body = {
        "name": "项目经理资质",
        "subject": "项目经理",
        "scope": "本项目",
        "value_decimal": None,
        "unit": None,
        "statement": "项目经理持有一级建造师证书",
        "evidence_ids": ["evd_fact0002"],
    }
    first = eng.post(f"/projects/{pid}/facts", body).json()
    second = eng.post(f"/projects/{pid}/facts", {**body, "name": "安全员证书", "statement": "安全员持有 C 证"}).json()
    url = f"/projects/{pid}/facts/{first['fact_id']}/withdraw"

    assert eng.post(url, {"reason": ""}).status_code == 422
    assert eng.post(f"/projects/{pid}/facts/fai_nonexistent/withdraw", {"reason": "x"}).status_code == 404

    # first 的 ID 属于旧事实集（second 的集里是新 ID 的副本），不是“当前”事实
    stale = eng.post(url, {"reason": "录错了"})
    assert stale.status_code == 409 and stale.json()["code"] == "fact_not_current"

    current = eng.get(f"/projects/{pid}/facts").json()
    target = next(i for i in current["items"] if i["name"] == "项目经理资质")
    res = eng.post(f"/projects/{pid}/facts/{target['fact_id']}/withdraw", {"reason": "证书已过期"})
    assert res.status_code == 200, res.text
    out = res.json()
    assert (
        out["item_count"] == 1
        and out["fact_id"] == target["fact_id"]
        and out["fact_set_id"] not in {first["fact_set_id"], second["fact_set_id"]}
    )
    listed = eng.get(f"/projects/{pid}/facts").json()
    assert listed["fact_set_id"] == out["fact_set_id"] and [i["name"] for i in listed["items"]] == ["安全员证书"]
    with engine.connect() as conn:
        aud = db.one(conn, "SELECT details_json, object_id FROM audit_events WHERE action='fact.withdraw'")
    assert aud is not None and aud["object_id"] == target["fact_id"]
    assert aud["details_json"]["reason"] == "证书已过期" and aud["details_json"]["statement"] == "项目经理持有一级建造师证书"

    # 再次撤回同一条：已不在最新集
    assert eng.post(f"/projects/{pid}/facts/{target['fact_id']}/withdraw", {"reason": "再撤"}).status_code == 409
    # 撤回最后一条 -> 空事实集
    last = eng.post(f"/projects/{pid}/facts/{listed['items'][0]['fact_id']}/withdraw", {"reason": "全部作废"}).json()
    assert last["item_count"] == 0
    assert eng.get(f"/projects/{pid}/facts").json() == {"fact_set_id": last["fact_set_id"], "items": []}
