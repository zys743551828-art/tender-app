"""Real nonowner PG/HTTP exact pricing; synthetic original text and in-memory formula blobs."""
# ruff: noqa: F401,F811

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from uuid import UUID

import pytest
from test_bid_package_api import attach, create, world
from test_bid_package_requirements_api import database
from test_pricing_integration import TEXT, formula_request, scenario
from test_stable_lot_identity import api, headers, uid

from packages.domain import storage
from packages.domain.bid_package_repository import read_parse_identity
from packages.domain.runtime import connection, sha
from packages.pricing import sources
from packages.rag.indexing import ensure_parse_sources, original_source_id, parse_source_id

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="isolated nonowner package pricing PG required",
)


@pytest.fixture
def priced(world, monkeypatch):
    w = world
    owner = w["database"]["owner"]
    with owner.transaction():
        owner.execute("SET LOCAL search_path TO design,public")
        version, parse, evidence = uid(), uid(), uid()
        owner.execute(
            "INSERT INTO document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) SELECT %s,bid_id,blob_id,'synthetic-pricing-authority.pdf',now(),'source_original',created_by FROM document_versions WHERE id=%s",
            (version, w["member"].document_version_id),
        )
        owner.execute(
            "INSERT INTO parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) VALUES(%s,%s,%s,%s,%s,1,'complete','[]')",
            (parse, w["scope"].bid_id, version, sha("synthetic-pricing-parser"), sha("synthetic")),
        )
        owner.execute(
            "INSERT INTO pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) VALUES(%s,%s,1,400,500,0,'usable','[]')",
            (w["scope"].bid_id, parse),
        )
        owner.execute(
            "INSERT INTO evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) VALUES(%s,%s,%s,1,0,'text',%s,%s)",
            (evidence, w["scope"].bid_id, parse, TEXT, sha(TEXT.encode())),
        )
        member = replace(
            w["member"],
            document_version_id=version,
            source_kind="authority",
            page_count=1,
            parse=read_parse_identity(owner, w["scope"].bid_id, version, parse),
            parts=(replace(w["member"].parts[0], last_page=1),),
        )
        attach(owner, w["scope"].bid_id, w["actor"], member, "tender")
    with connection() as c:
        who = c.execute(
            "SELECT current_user AS name,(SELECT rolsuper FROM pg_roles WHERE rolname=current_user) AS super"
        ).fetchone()
        assert who["name"] == "fusion_package_requirements_service" and not who["super"]
        for value in (w["member"], member):
            ensure_parse_sources(
                c, w["scope"].bid_id, UUID(value.parse.parse_run_id), publish_readable=True
            )
    own = create(w)
    assert own.status_code == 201, own.text
    authority_item = w["item"] | {
        "member_id": "pricing-authority",
        "document_version_id": member.document_version_id,
        "parse_run_id": member.parse.parse_run_id,
        "purposes": ["pricing"],
        "parts": [w["item"]["parts"][0] | {"last_page": 1}],
    }
    authority = create(w, body={"kind": "authority", "members": [authority_item]})
    assert authority.status_code == 201, authority.text
    binding = {
        "package_id": own.json()["manifest"]["package_id"],
        "revision_id": own.json()["manifest"]["revision_id"],
        "authority_package_id": authority.json()["manifest"]["package_id"],
        "authority_revision_id": authority.json()["manifest"]["revision_id"],
    }
    evidence = owner.execute(
        "SELECT id::text FROM design.evidence_blocks WHERE parse_id=%s AND physical_page=1",
        (member.parse.parse_run_id,),
    ).fetchone()["id"]
    item = {
        "doc": member.document_version_id,
        "parse": member.parse.parse_run_id,
        "evidence": evidence,
    }
    formula = formula_request(item) | {"package_binding": binding}
    objects = {}
    monkeypatch.setattr(storage, "put", lambda key, raw, media: objects.__setitem__(key, raw))
    monkeypatch.setattr(storage, "get", lambda key: objects[key])
    return w | {
        "binding": binding,
        "request": formula,
        "authority": authority.json(),
        "own": own.json(),
        "own_etag": own.headers["etag"],
        "authority_member": member,
        "objects": objects,
        "pricing_base": f"/api/v1/bids/{w['scope'].bid_id}",
    }


def register(w):
    context = w["client"].get(w["pricing_base"] + "/package-pricing-context", params=w["binding"])
    assert context.status_code == 200, context.text
    response = w["client"].post(
        w["pricing_base"] + "/package-pricing-formulas",
        json=w["request"],
        headers=headers(w, etag=context.headers["etag"]),
    )
    assert response.status_code == 201, response.text
    return response


def simulate(w, formula):
    body = scenario(formula.json()["formula_version_id"])
    response = w["client"].post(
        w["pricing_base"] + "/pricing-simulations",
        json=body,
        headers=headers(w, etag=formula.headers["etag"]),
    )
    assert response.status_code == 201, response.text
    return response


def test_exact_formula_simulation_save_without_legacy_material_selection(priced):
    w = priced
    context = w["client"].get(w["pricing_base"] + "/package-pricing-context", params=w["binding"])
    assert context.status_code == 200, context.text
    assert context.json()["material_snapshot_id"] is None
    assert context.json()["package_binding"] == w["binding"]
    choices = w["client"].get(
        w["pricing_base"] + "/package-pricing-formula-sources", params=w["binding"]
    )
    assert choices.status_code == 200, choices.text
    assert {row["parse_id"] for row in choices.json()["items"]} == {
        w["authority_member"].parse.parse_run_id
    }
    formula = register(w)
    value = formula.json()
    assert value["formula"]["schema"] == "pricing-formula/2"
    assert value["formula"]["package_binding"] == w["binding"]
    assert (
        value["formula"]["source_authority"]["package_snapshot"]["package_digest"]
        == w["own"]["digest"]
    )
    result = simulate(w, formula)
    assert result.json()["price_score"] == "25.00"
    saved = w["client"].post(
        w["pricing_base"] + "/pricing-plans",
        json={"simulation_id": result.json()["id"], "reason": "Synthetic exact package scenario"},
        headers=headers(w, etag=result.headers["etag"]),
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["formula_snapshot"]["package_binding"] == w["binding"]
    listed = w["client"].get(w["pricing_base"] + "/pricing-formulas").json()["items"]
    assert listed[0]["package_binding"] == w["binding"]


def test_package_revision_change_preserves_history_but_blocks_late_simulation_and_save(priced):
    w = priced
    formula = register(w)
    result = simulate(w, formula)
    revised = w["client"].post(
        w["base"] + "/" + w["binding"]["package_id"] + "/revisions",
        json={"members": [w["item"]]},
        headers=headers(w, etag=w["own_etag"]),
    )
    assert revised.status_code == 201, revised.text
    attempted = w["client"].post(
        w["pricing_base"] + "/pricing-simulations",
        json=scenario(formula.json()["formula_version_id"]),
        headers=headers(w, etag=formula.headers["etag"]),
    )
    assert attempted.status_code == 409, attempted.text
    attempted = w["client"].post(
        w["pricing_base"] + "/pricing-plans",
        json={"simulation_id": result.json()["id"], "reason": "Late save must fail"},
        headers=headers(w, etag=result.headers["etag"]),
    )
    assert attempted.status_code == 409, attempted.text
    history = w["client"].get(w["pricing_base"] + "/pricing-simulations/" + result.json()["id"])
    assert history.status_code == 200 and history.json()["price_score"] == "25.00"
    assert history.json()["current_applicability"]["applicable"] is False


def test_rule_version_change_expires_exact_formula_without_rewriting_history(priced):
    w = priced
    owner = w["database"]["owner"]
    material, first, second = uid(), uid(), uid()
    with owner.transaction():
        owner.execute(
            "INSERT INTO design.material_snapshots(id,bid_id,revision,manifest,digest) VALUES(%s,%s,1,'{}',%s)",
            (material, w["scope"].bid_id, sha({})),
        )
        for revision, identity in enumerate((first, second), start=1):
            owner.execute(
                "INSERT INTO design.rule_sets(id,bid_id,material_id,revision,digest,coverage) VALUES(%s,%s,%s,%s,%s,'complete')",
                (identity, w["scope"].bid_id, material, revision, sha(identity)),
            )
        owner.execute(
            "UPDATE design.bid_profiles SET current_rule_set_id=%s WHERE bid_id=%s",
            (first, w["scope"].bid_id),
        )
    formula = register(w)
    result = simulate(w, formula)
    owner.execute(
        "UPDATE design.bid_profiles SET current_rule_set_id=%s WHERE bid_id=%s",
        (second, w["scope"].bid_id),
    )
    current = w["client"].get(
        w["pricing_base"] + "/pricing-formulas/" + formula.json()["formula_version_id"]
    )
    assert current.status_code == 200 and not current.json()["current_applicability"]["applicable"]
    assert current.json()["formula"] == formula.json()["formula"]
    late = w["client"].post(
        w["pricing_base"] + "/pricing-simulations",
        json=scenario(formula.json()["formula_version_id"]),
        headers=headers(w, etag=formula.headers["etag"]),
    )
    assert late.status_code == 409, late.text
    history = w["client"].get(w["pricing_base"] + "/pricing-simulations/" + result.json()["id"])
    assert history.status_code == 200 and history.json()["price_score"] == "25.00"
    assert not history.json()["current_applicability"]["applicable"]


def test_current_formula_read_does_not_take_graph_before_waiting_for_bid(priced, monkeypatch):
    w = priced
    formula = register(w)
    entering_bid_lock = Event()
    original = sources.enabled_bid

    def observed(c, bid, *, lock=False):
        if lock:
            entering_bid_lock.set()
        return original(c, bid, lock=lock)

    monkeypatch.setattr(sources, "enabled_bid", observed)
    owner = w["database"]["owner"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        with owner.transaction():
            owner.execute("SELECT id FROM design.bids WHERE id=%s FOR UPDATE", (w["scope"].bid_id,))
            reading = pool.submit(
                w["client"].get,
                w["pricing_base"] + "/pricing-formulas/" + formula.json()["formula_version_id"],
            )
            assert entering_bid_lock.wait(5), "Reader did not reach the bid authority check"
            graph_available = owner.execute(
                "SELECT pg_try_advisory_xact_lock(90127,1) AS available"
            ).fetchone()["available"]
        response = reading.result(timeout=10)
    assert graph_available, "Reader held graph while waiting for a writer's bid lock"
    assert response.status_code == 200, response.text


def test_withdrawn_package_ancestor_rejects_new_use_and_replay(priced):
    w = priced
    formula = register(w)
    result = simulate(w, formula)
    saved_body = {"simulation_id": result.json()["id"], "reason": "Synthetic before withdrawal"}
    saved_headers = headers(w, etag=result.headers["etag"])
    saved = w["client"].post(
        w["pricing_base"] + "/pricing-plans", json=saved_body, headers=saved_headers
    )
    assert saved.status_code == 201, saved.text
    owner = w["database"]["owner"]
    owner.execute(
        "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
        (original_source_id(UUID(w["authority_member"].document_version_id)),),
    )
    current = w["client"].get(
        w["pricing_base"] + "/pricing-formulas/" + formula.json()["formula_version_id"]
    )
    assert current.status_code == 200 and not current.json()["current_applicability"]["applicable"]
    attempted = w["client"].post(
        w["pricing_base"] + "/pricing-plans",
        json={"simulation_id": result.json()["id"], "reason": "Withdrawn source"},
        headers=headers(w, etag=result.headers["etag"]),
    )
    assert attempted.status_code == 409, attempted.text
    replay = w["client"].post(
        w["pricing_base"] + "/pricing-plans", json=saved_body, headers=saved_headers
    )
    assert replay.status_code == 409, replay.text
    history = w["client"].get(w["pricing_base"] + "/pricing-plans/" + saved.json()["id"])
    assert history.status_code == 200 and history.json()["result"]["price_score"] == "25.00"
    assert not history.json()["current_applicability"]["applicable"]


def test_quote_from_unselected_parse_and_wrong_package_kind_are_rejected(priced):
    w = priced
    context = w["client"].get(w["pricing_base"] + "/package-pricing-context", params=w["binding"])
    w["request"]["evidence_quotes"][0]["parse_id"] = w["member"].parse.parse_run_id
    rejected = w["client"].post(
        w["pricing_base"] + "/package-pricing-formulas",
        json=w["request"],
        headers=headers(w, etag=context.headers["etag"]),
    )
    assert rejected.status_code == 409 and not w["objects"], rejected.text
    wrong = w["binding"] | {
        "authority_package_id": w["binding"]["package_id"],
        "authority_revision_id": w["binding"]["revision_id"],
    }
    rejected = w["client"].get(w["pricing_base"] + "/package-pricing-context", params=wrong)
    assert rejected.status_code == 409, rejected.text


def test_registration_rechecks_package_after_blob_staging(priced, monkeypatch):
    w = priced
    context = w["client"].get(w["pricing_base"] + "/package-pricing-context", params=w["binding"])

    def staged(key, raw, media):
        w["objects"][key] = raw
        revised = w["client"].post(
            w["base"] + "/" + w["binding"]["package_id"] + "/revisions",
            json={"members": [w["item"]]},
            headers=headers(w, etag=w["own_etag"]),
        )
        assert revised.status_code == 201, revised.text

    monkeypatch.setattr(storage, "put", staged)
    rejected = w["client"].post(
        w["pricing_base"] + "/package-pricing-formulas",
        json=w["request"],
        headers=headers(w, etag=context.headers["etag"]),
    )
    assert rejected.status_code == 409, rejected.text
    assert w["client"].get(w["pricing_base"] + "/pricing-formulas").json()["items"] == []


def test_newer_unselected_parse_does_not_replace_explicit_formula_evidence(priced):
    w = priced
    formula = register(w)
    old_parse = w["authority_member"].parse.parse_run_id
    new_parse = uid()
    owner = w["database"]["owner"]
    with owner.transaction():
        owner.execute(
            "INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) SELECT %s,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps FROM design.parse_runs WHERE id=%s",
            (new_parse, old_parse),
        )
        owner.execute(
            "INSERT INTO design.pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) SELECT bid_id,%s,physical_page,width,height,rotation,quality,gaps FROM design.pages WHERE parse_id=%s",
            (new_parse, old_parse),
        )
        owner.execute(
            "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) SELECT gen_random_uuid(),bid_id,%s,physical_page,ordinal,kind,text_content,digest FROM design.evidence_blocks WHERE parse_id=%s",
            (new_parse, old_parse),
        )
    with connection() as c:
        ensure_parse_sources(c, w["scope"].bid_id, UUID(new_parse), publish_readable=True)
    choices = w["client"].get(
        w["pricing_base"] + "/package-pricing-formula-sources", params=w["binding"]
    )
    assert choices.status_code == 200, choices.text
    assert {item["parse_id"] for item in choices.json()["items"]} == {old_parse}
    assert simulate(w, formula).json()["price_score"] == "25.00"


def test_ineligible_exact_package_price_retains_null_and_missing_parameter_is_rejected(priced):
    w = priced
    formula = register(w)
    body = scenario(formula.json()["formula_version_id"]) | {"candidate_price": "0"}
    response = w["client"].post(
        w["pricing_base"] + "/pricing-simulations",
        json=body,
        headers=headers(w, etag=formula.headers["etag"]),
    )
    assert response.status_code == 201, response.text
    assert response.json()["price_score"] is None and response.json()["eligible"] is False
    context = w["client"].get(w["pricing_base"] + "/package-pricing-context", params=w["binding"])
    del w["request"]["formula"]["minimum_valid_bids"]
    rejected = w["client"].post(
        w["pricing_base"] + "/package-pricing-formulas",
        json=w["request"],
        headers=headers(w, etag=context.headers["etag"]),
    )
    assert rejected.status_code == 422, rejected.text
