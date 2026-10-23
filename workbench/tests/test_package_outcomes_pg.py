"""Real nonowner official-result association over the one native submission chain."""
# ruff: noqa: F401,F811

import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from psycopg.types.json import Jsonb
from test_bid_package_submissions_pg import (
    api,
    catalog,
    database,
    exact,
    headers,
    inventory,
    register,
    request,
    requirements,
    uid,
    world,
)

from packages.contracts.package_outcomes_api import valid
from packages.domain import bid_package_repository
from packages.domain.runtime import DomainError, connection, etag, sha
from packages.identity.repository import record_binding, register_bidder
from packages.rag.indexing import ensure_parse_sources, original_source_id
from packages.research import outcomes, package_outcomes

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="isolated nonowner package outcome PG17 required",
)
QUOTE = "Synthetic official technical total: 0 points out of 60."


def setup(w, *, with_authority=True, trailing_zero=False):
    selection = deepcopy(w["selection"])
    if with_authority:
        with connection() as c:
            assert not c.execute(
                "SELECT rolsuper FROM pg_roles WHERE rolname=current_user"
            ).fetchone()["rolsuper"]
            authority = bid_package_repository.load_revision(
                c, w["scope"].bid_id, w["inventory_body"]["authority_revision_id"]
            )
            for member in authority.members:
                ensure_parse_sources(
                    c,
                    UUID(w["scope"].bid_id),
                    UUID(member.parse.parse_run_id),
                    publish_readable=True,
                )
            if trailing_zero:
                c.execute(
                    "UPDATE retrieval.source_heads h SET valid_from=date_trunc('day',clock_timestamp())-interval '1 day'+interval '0.123450 seconds' "
                    "FROM retrieval.source_nodes n WHERE h.source_id=n.id AND n.document_version_id=ANY(%s::uuid[])",
                    ([member.document_version_id for member in authority.members],),
                )
        response = inventory(w)
        assert response.status_code == 201, response.text
        inv = response.json()
        selection["inventory"] = {"id": inv["manifest"]["id"], "digest": inv["digest"]}
    preview, body = request(w, selection=selection)
    # The synthetic originals were obtained before this declared actual event;
    # a default old timestamp would correctly fail the prebid source check.
    body["submitted_at"] = datetime.now(timezone.utc).isoformat()
    saved, _ = register(w, body, preview["bid_etag"])
    submission = saved["body"]["submission"]
    version, blob, parse, block = uid(), uid(), uid(), uid()
    raw = ("Synthetic official result " + version).encode()
    with connection() as c:
        bid = w["scope"].bid_id
        c.execute(
            "INSERT INTO blobs(id,digest,byte_size,object_key,media_type) VALUES(%s,%s,%s,%s,'text/plain')",
            (blob, sha(raw), len(raw), "synthetic/package-outcome/" + blob),
        )
        c.execute(
            "INSERT INTO document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) VALUES(%s,%s,%s,'synthetic-official-result.txt',clock_timestamp(),'source_original',%s)",
            (version, bid, blob, w["actor"]),
        )
        c.execute(
            "INSERT INTO parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) VALUES(%s,%s,%s,%s,%s,1,'complete','[]')",
            (parse, bid, version, sha("synthetic-package-outcome-parser"), sha("synthetic")),
        )
        c.execute(
            "INSERT INTO pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) VALUES(%s,%s,1,100,100,0,'usable','[]')",
            (bid, parse),
        )
        c.execute(
            "INSERT INTO evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) VALUES(%s,%s,%s,1,0,'text',%s,%s)",
            (block, bid, parse, QUOTE, sha(QUOTE.encode())),
        )
        material = c.execute(
            "SELECT material_id FROM rule_sets WHERE bid_id=%s AND id=%s",
            (bid, w["inventory_body"]["rule_set_id"]),
        ).fetchone()["material_id"]
        c.execute(
            "INSERT INTO material_assignments(snapshot_id,bid_id,document_version_id,role,ordinal) VALUES(%s,%s,%s,'official_result',0)",
            (material, bid, version),
        )
        ensure_parse_sources(c, UUID(bid), UUID(parse), publish_readable=True)
    with connection() as c:
        known = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
    body = {
        "submission_id": submission["id"],
        "score_kind": "technical_total",
        "value": "0",
        "maximum": "60",
        "source_version_id": version,
        "known_at": known.isoformat(),
    }
    response = w["client"].post(f"/api/v1/bids/{bid}/outcomes", json=body, headers=headers(w))
    assert response.status_code == 201, response.text
    context = w["client"].get(
        f"/api/v1/bids/{bid}/outcome-context", params={"submission_id": submission["id"]}
    )
    assert context.status_code == 200, context.text
    context = context.json()
    assert valid("PackageOutcomeContext", context)
    verification = {
        "version": "package-outcome-verification/1",
        "subject_kind": "bid_package",
        "state": "verified",
        "reason": "Synthetic exact package and official original checked",
        "identity": context["identity"],
        "authority": context["authority"],
        "aggregation": "Technical total stated on original page",
        "published_at": known.isoformat(),
        "evidence_refs": [
            {
                "document_version_id": version,
                "evidence_id": block,
                "physical_page": 1,
                "quote": QUOTE,
            }
        ],
    }
    return w | {
        "submission": submission,
        "result": response.json(),
        "result_headers": dict(response.headers),
        "result_request": body,
        "context": context,
        "verification": verification,
        "source": version,
        "parse": parse,
        "block": block,
    }


def verify(w, body=None, *, tag=None, result_id=None):
    with connection() as c:
        return outcomes.verify(
            c,
            actor=UUID(w["actor"]),
            outcome_id=UUID(result_id or w["result"]["id"]),
            body=body or w["verification"],
            condition=tag or w["result_headers"]["verification-etag"],
            command=None,
        )


def sample_count(w):
    with connection() as c:
        return c.execute(
            "SELECT count(*) AS n FROM samples WHERE bid_id=%s", (w["scope"].bid_id,)
        ).fetchone()["n"]


def current_reasons(w, details, *, as_of=None):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        submission = c.execute(
            "SELECT * FROM submission_records WHERE id=%s", (w["submission"]["id"],)
        ).fetchone()
        result = c.execute("SELECT * FROM outcomes WHERE id=%s", (w["result"]["id"],)).fetchone()
        return package_outcomes.current_reasons(c, submission, result, details, as_of=as_of)


def test_native_result_context_verification_zero_and_explicit_sample_block(exact):
    w = setup(exact)
    context = w["context"]
    assert context["subject_kind"] == "bid_package" and context["body_version_id"] is None
    assert context["package_binding"] == w["submission"]["package_binding"]
    assert context["package_identity"] == w["submission"]["identity"]
    assert context["verification_blockers"] == []
    value, tag = verify(w)
    assert value["verification"] == "verified" and value["value"] == "0"
    details = value["verification_details"]
    assert valid("PackageOutcomeVerificationDetails", details)
    assert details["authority_proof"] and details["official_source_proof"]
    assert details["binding_digest"] == w["submission"]["package_binding"]["digest"]
    assert details["formal_sample_eligible"] is False
    with connection() as c:
        native = c.execute(
            "SELECT h.submission_id,h.outcome_id,d.object_revision,d.decision FROM outcome_heads h "
            "JOIN decision_heads q ON q.object_id=h.outcome_id AND q.object_kind='outcome' "
            "JOIN decisions d ON d.id=q.decision_id WHERE h.bid_id=%s",
            (w["scope"].bid_id,),
        ).fetchone()
        assert str(native["submission_id"]) == w["submission"]["id"]
        assert str(native["outcome_id"]) == w["result"]["id"]
        assert native["decision"] == "verified" and native["object_revision"] == 1
    rejected = w["client"].post(
        f"/api/v1/bids/{w['scope'].bid_id}/submissions/{w['submission']['id']}/sample-admission",
        json={},
        headers=headers(w),
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "PACKAGE_OUTCOME_FORMAL_SAMPLE_UNSUPPORTED"
    assert sample_count(w) == 0
    replay = w["client"].get("/api/v1/outcomes/" + w["result"]["id"])
    assert replay.status_code == 200 and replay.headers["etag"] == tag
    assert replay.json()["verification_details"] == details


def test_missing_materials_retain_pending_conflict_and_rejected_but_never_verified(exact):
    w = setup(exact, with_authority=False)
    assert w["context"]["authority"] is None
    assert "PACKAGE_OUTCOME_AUTHORITY_MISSING" in w["context"]["verification_blockers"]
    with pytest.raises(DomainError) as caught:
        verify(w)
    assert caught.value.code == "PACKAGE_OUTCOME_AUTHORITY_MISSING"
    tag = None
    for state in ("pending", "conflict", "rejected"):
        view, tag = verify(w, w["verification"] | {"state": state}, tag=tag)
        assert view["verification"] == state
        assert view["verification_details"]["authority_proof"] is None
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM outcomes WHERE bid_id=%s", (w["scope"].bid_id,)
            ).fetchone()["n"]
            == 1
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM decisions WHERE bid_id=%s AND object_kind='outcome'",
                (w["scope"].bid_id,),
            ).fetchone()["n"]
            == 3
        )
    assert sample_count(w) == 0


def test_append_only_result_correction_reuses_native_head_and_old_verification_is_read_only(exact):
    w = setup(exact)
    original, verification_tag = verify(w)
    correction = w["result_request"] | {"value": "1"}
    result = w["client"].post(
        "/api/v1/outcomes/" + w["result"]["id"] + "/corrections",
        json=correction,
        headers=headers(w, etag=w["result_headers"]["etag"]),
    )
    assert result.status_code == 201, result.text
    assert result.json()["supersedes_id"] == w["result"]["id"]
    assert result.json()["verification"] == "pending"
    with pytest.raises(DomainError) as caught:
        verify(w, tag=verification_tag)
    assert caught.value.code == "OUTCOME_NOT_CURRENT"
    old = w["client"].get("/api/v1/outcomes/" + w["result"]["id"]).json()
    assert old["verification_details"] == original["verification_details"] and not old["current"]
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM outcome_heads WHERE bid_id=%s", (w["scope"].bid_id,)
            ).fetchone()["n"]
            == 1
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM outcomes WHERE bid_id=%s", (w["scope"].bid_id,)
            ).fetchone()["n"]
            == 2
        )


@pytest.mark.parametrize(
    "field", ["package_id", "revision_id", "package_digest", "binding_digest", "identity_digest"]
)
def test_exact_package_identity_substitution_fails_without_new_decision(exact, field):
    w = setup(exact)
    body = deepcopy(w["verification"])
    body["identity"][field] = "f" * 64 if field.endswith("digest") else uid()
    with pytest.raises(DomainError) as caught:
        verify(w, body)
    assert caught.value.code == "PACKAGE_OUTCOME_IDENTITY_MISMATCH"
    with connection() as c:
        assert not c.execute(
            "SELECT 1 FROM decision_heads WHERE object_kind='outcome' AND object_id=%s",
            (w["result"]["id"],),
        ).fetchone()


@pytest.mark.parametrize(
    "mutation", ["quote", "page", "authority_revision", "official_source", "authority_source"]
)
def test_wrong_original_page_authority_or_withdrawn_ancestor_blocks_verified(exact, mutation):
    w = setup(exact)
    body = deepcopy(w["verification"])
    if mutation == "quote":
        body["evidence_refs"][0]["quote"] = "Fabricated statement not on the official original"
    elif mutation == "page":
        body["evidence_refs"][0]["physical_page"] = 2
    elif mutation == "authority_revision":
        body["authority"]["revision_id"] = uid()
    else:
        source = (
            original_source_id(UUID(w["source"]))
            if mutation == "official_source"
            else original_source_id(
                UUID(
                    w["submission"]["package_binding"]["manifest"]["selection"]["authority"][
                        "manifest"
                    ]["members"][0]["document_version_id"]
                )
            )
        )
        with connection() as c:
            c.execute(
                "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                (source,),
            )
    with pytest.raises(DomainError) as caught:
        verify(w, body)
    assert caught.value.code in {
        "PACKAGE_OUTCOME_SOURCE_MISMATCH",
        "PACKAGE_OUTCOME_AUTHORITY_MISMATCH",
        "PACKAGE_OUTCOME_SOURCE_INVALID",
        "PACKAGE_OUTCOME_AUTHORITY_SOURCE_CHANGED",
    }
    assert sample_count(w) == 0


def test_later_identity_cannot_replace_original_package_identity(exact):
    w = setup(exact)
    frozen = deepcopy(w["context"]["package_identity"])
    with connection() as c:
        bidder = register_bidder(
            c, UUID(w["actor"]), "Synthetic corrected bidder", "Synthetic explicit correction", None
        )
        c.execute(
            "UPDATE bid_profiles SET bidder_id=%s WHERE bid_id=%s",
            (bidder["id"], w["scope"].bid_id),
        )
        record_binding(
            c,
            UUID(w["scope"].bid_id),
            UUID(w["actor"]),
            None,
            reason="Synthetic later identity correction",
            confirmed=True,
        )
    with pytest.raises(DomainError) as caught:
        verify(w)
    assert caught.value.code == "OUTCOME_IDENTITY_UNVERIFIED"
    context = (
        w["client"]
        .get(
            f"/api/v1/bids/{w['scope'].bid_id}/outcome-context",
            params={"submission_id": w["submission"]["id"]},
        )
        .json()
    )
    assert context["identity_status"] == "changed"
    assert context["package_identity"] == frozen
    assert context["identity"] == w["context"]["identity"]
    # The adverse opinion remains recordable for the old fact.
    rejected, _ = verify(w, w["verification"] | {"state": "conflict"})
    assert rejected["verification_details"]["package_identity"] == frozen


def test_old_package_revision_stays_exact_after_new_package_head(exact):
    w = setup(exact)
    old = w["own"]["manifest"]
    newer = w["client"].post(
        f"{w['base']}/{old['package_id']}/revisions",
        json={"members": [w["item"]]},
        headers=headers(w, etag=etag("bid-package-head", old["package_id"], w["own"]["digest"])),
    )
    assert newer.status_code == 201, newer.text
    result, _ = verify(w)
    assert result["verification"] == "verified"
    assert (
        result["verification_details"]["request"]["identity"]["revision_id"] == old["revision_id"]
    )
    assert (
        result["verification_details"]["request"]["identity"]["revision_id"]
        != newer.json()["manifest"]["revision_id"]
    )


def test_pg_json_timestamp_trailing_zero_does_not_create_false_source_change(exact):
    w = setup(exact, trailing_zero=True)
    sources = w["submission"]["package_binding"]["manifest"]["context"]["current"]["sources"]
    assert any(
        datetime.fromisoformat(row["valid_from"].replace("Z", "+00:00")).microsecond == 123450
        for row in sources
    ), [row["valid_from"] for row in sources]
    before = deepcopy(w["submission"]["package_binding"])
    result, _ = verify(w)
    assert result["verification"] == "verified"
    assert w["submission"]["package_binding"] == before


@pytest.mark.parametrize("change", ["official_source", "authority_source", "identity"])
def test_current_association_excludes_changed_authority_without_rewriting_old_decision(
    exact, change
):
    w = setup(exact)
    verified, _ = verify(w)
    details = verified["verification_details"]
    assert current_reasons(w, details) == []
    with connection() as c:
        if change == "identity":
            bidder = register_bidder(
                c,
                UUID(w["actor"]),
                "Synthetic changed current bidder",
                "Synthetic later correction",
                None,
            )
            c.execute(
                "UPDATE bid_profiles SET bidder_id=%s WHERE bid_id=%s",
                (bidder["id"], w["scope"].bid_id),
            )
            record_binding(
                c,
                UUID(w["scope"].bid_id),
                UUID(w["actor"]),
                None,
                reason="Synthetic later correction",
                confirmed=True,
            )
        else:
            version = (
                w["source"]
                if change == "official_source"
                else w["submission"]["package_binding"]["manifest"]["selection"]["authority"][
                    "manifest"
                ]["members"][0]["document_version_id"]
            )
            c.execute(
                "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                (original_source_id(UUID(version)),),
            )
    assert current_reasons(w, details)
    old = w["client"].get("/api/v1/outcomes/" + w["result"]["id"]).json()
    assert old["verification"] == "verified"
    assert old["verification_details"] == details


def test_current_association_respects_observation_time_and_never_uses_frozen_proof_as_live_authority(
    exact,
):
    w = setup(exact)
    verified, _ = verify(w)
    details = verified["verification_details"]
    assert current_reasons(w, details) == []
    assert current_reasons(w, details, as_of=w["result_request"]["known_at"]) == [
        "package_outcome_not_observed_at_as_of"
    ]
    before = deepcopy(details)
    forged = deepcopy(details)
    forged["authority_proof"]["snapshot"]["sources"].clear()
    forged["authority_proof"]["digest"] = sha(forged["authority_proof"]["snapshot"])
    assert current_reasons(w, forged) == ["package_outcome_verification_changed"]
    assert details == before
    assert sample_count(w) == 0


def test_legacy_single_body_result_verification_and_admission_still_work(exact):
    # This is a genuine single-body subject using the already confirmed stable
    # lot identity. It does not upgrade an old identity-v1 fixture or a package.
    w = exact
    bid, submission, parse, block = w["scope"].bid_id, uid(), uid(), uid()
    with connection() as c:
        frozen = c.execute("SELECT design.identity_snapshot_v2(%s) AS value", (bid,)).fetchone()[
            "value"
        ]
        assert frozen["binding_status"] == "confirmed"
        c.execute(
            "INSERT INTO submission_records(id,bid_id,body_version_id,kind,evidence,submitted_at,created_by) "
            "VALUES(%s,%s,%s,'offline_fact',%s,clock_timestamp(),%s)",
            (
                submission,
                bid,
                w["member"].document_version_id,
                Jsonb({"identity": frozen}),
                w["actor"],
            ),
        )
        c.execute(
            "INSERT INTO submission_heads(bid_id,submission_id,revision) VALUES(%s,%s,1)",
            (bid, submission),
        )
        material = c.execute(
            "SELECT material_id FROM rule_sets WHERE id=%s", (w["inventory_body"]["rule_set_id"],)
        ).fetchone()["material_id"]
        authority = bid_package_repository.load_revision(
            c, bid, w["inventory_body"]["authority_revision_id"]
        )
        c.execute(
            "INSERT INTO material_assignments(snapshot_id,bid_id,document_version_id,role,ordinal) VALUES(%s,%s,%s,'tender',0)",
            (material, bid, authority.members[0].document_version_id),
        )
        c.execute(
            "INSERT INTO parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) VALUES(%s,%s,%s,%s,%s,1,'complete','[]')",
            (
                parse,
                bid,
                w["attachment"]["document_version_id"],
                sha("synthetic-score-parser"),
                sha("synthetic"),
            ),
        )
        c.execute(
            "INSERT INTO pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) VALUES(%s,%s,1,100,100,0,'usable','[]')",
            (bid, parse),
        )
        c.execute(
            "INSERT INTO evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) VALUES(%s,%s,%s,1,0,'text',%s,%s)",
            (block, bid, parse, QUOTE, sha(QUOTE.encode())),
        )
        known = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat()
    body = {
        "submission_id": submission,
        "score_kind": "technical_total",
        "value": "0",
        "maximum": "60",
        "source_version_id": w["attachment"]["document_version_id"],
        "known_at": known,
    }
    registered = w["client"].post(f"/api/v1/bids/{bid}/outcomes", json=body, headers=headers(w))
    assert registered.status_code == 201, registered.text
    context = (
        w["client"]
        .get(f"/api/v1/bids/{bid}/outcome-context", params={"submission_id": submission})
        .json()
    )
    assert context["identity"]["body_version_id"] == w["member"].document_version_id
    verified = w["client"].post(
        "/api/v1/outcomes/" + registered.json()["id"] + "/verification",
        json={
            "state": "verified",
            "reason": "Synthetic existing single-body path",
            "identity": context["identity"],
            "aggregation": "Official technical total",
            "published_at": known,
            "evidence_ids": [block],
            "material_snapshot_id": str(material),
            "effective_material_confirmed": True,
        },
        headers=headers(w, etag=registered.headers["Verification-ETag"]),
    )
    assert verified.status_code == 200, verified.text
    path = f"/api/v1/bids/{bid}/submissions/{submission}/sample-admission"
    admitted = w["client"].post(path, json={}, headers=headers(w))
    assert admitted.status_code == 200 and admitted.json()["admission"] == "admitted", admitted.text
    corrected = w["client"].post(
        "/api/v1/outcomes/" + registered.json()["id"] + "/corrections",
        json=body | {"score_kind": "unknown", "value": None, "maximum": None},
        headers=headers(w, etag=registered.headers["ETag"]),
    )
    assert corrected.status_code == 201, corrected.text
    pending = w["client"].post(path, json={}, headers=headers(w))
    assert pending.status_code == 200 and pending.json()["admission"] == "pending", pending.text
