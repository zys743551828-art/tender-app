"""Explicit synthetic pre-existing v1 rows for bridge compatibility tests.

No production verifier is patched or weakened. Fixtures initialize old frozen
facts directly; actual API/CPU guard behavior is tested afterward. These rows
are not real historical samples and cannot establish feature or model quality.
"""

import json

import pytest
from psycopg.types.json import Jsonb

from packages.domain import storage
from packages.domain.runtime import clean, connection, sha, uid
from packages.identity import repository as identities
from packages.model_governance.common import digest
from packages.rag.indexing import ensure_parse_sources, original_source_id, parse_source_id
from packages.research import batches, execution, profile
from tests.test_model_governance_statistics import bundle
from tests.test_research_integration import seed


def old_identity(c, bid, actor, command_id, *, before=None, reason, confirmed):
    after = identities.association(c, bid)
    after.pop("lot_id")
    identities.record(
        c,
        actor,
        bid,
        identities.BOUND,
        {
            "before": None,
            "after": after,
            "confirmed": True,
            "reason": "Synthetic pre-existing v1 identity fixture, not a current v2 qualification",
            "identity_version": "bid-identity/1",
        },
        None,
    )
    authority = c.execute(
        "SELECT id FROM audit_entries WHERE bid_id=%s AND event_type='identity.bound' ORDER BY created_at DESC,id DESC LIMIT 1",
        (bid,),
    ).fetchone()["id"]
    value = after | {
        "authority_id": str(authority),
        "binding_status": "confirmed",
        "identity_version": "bid-identity/1",
    }
    return value | {"digest": digest(value)}


def current_identity(c, bid, actor, command_id, *, before=None, reason, confirmed):
    """Initialize a real stable lot before the normal v2 binding code runs."""
    actual = identities.association(c, bid)
    lot = uid()
    c.execute(
        "INSERT INTO engineering_lots(id,engineering_project_id,label) VALUES(%s,%s,%s)",
        (lot, actual["engineering_project_id"], actual["lot"]),
    )
    c.execute("UPDATE bid_rounds SET lot_id=%s WHERE id=%s", (lot, actual["round_id"]))
    # Saved before the scoped test fixture replaces the caller's binding hook.
    return _normal_binding(c, bid, actor, command_id, reason=reason, confirmed=confirmed)


_normal_binding = identities.record_binding


def item(client, *, year=2024, body_blob_id=None, historical_v1=True, project_id=None, round_no=1):
    web, actor, headers, _ = client
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            identities, "record_binding", old_identity if historical_v1 else current_identity
        )
        value = seed(
            actor, year=year, body_blob_id=body_blob_id, project_id=project_id, round_no=round_no
        )
    with connection() as c:
        c.execute(
            "INSERT INTO material_assignments(snapshot_id,bid_id,document_version_id,role,ordinal) VALUES(%s,%s,%s,'official_result',0)",
            (value["material"], value["bid"], value["source"]),
        )
        parse = c.execute(
            "SELECT id FROM parse_runs WHERE document_version_id=%s", (value["source"],)
        ).fetchone()["id"]
        ensure_parse_sources(c, value["bid"], parse, publish_readable=True)
    if not historical_v1:
        return value
    with connection() as c:
        result, sample, verify, grouping = [uid() for _ in range(4)]
        c.execute(
            "INSERT INTO outcomes(id,bid_id,submission_id,score_kind,value,maximum,source_version_id,known_at,created_by) VALUES(%s,%s,%s,'technical_total',0,60,%s,%s,%s)",
            (result, value["bid"], value["submission"], value["source"], value["known"], actor),
        )
        c.execute(
            "INSERT INTO outcome_heads(submission_id,bid_id,outcome_id,revision) VALUES(%s,%s,%s,1)",
            (value["submission"], value["bid"], result),
        )
        for decision, kind, target, state, reason, evidence in (
            (
                verify,
                "outcome",
                result,
                "verified",
                {"published_at": value["known"], "synthetic": True},
                [value["evidence"]],
            ),
            (
                grouping,
                "sample_group",
                sample,
                "reviewed",
                {
                    "template_key": None,
                    "near_duplicate_key": None,
                    "synthetic": True,
                    "reviewed": True,
                },
                [],
            ),
        ):
            c.execute(
                "INSERT INTO decisions(id,bid_id,object_kind,object_id,object_revision,decision,reason,evidence_ids,actor_id) VALUES(%s,%s,%s,%s,1,%s,%s,%s,%s)",
                (
                    decision,
                    value["bid"],
                    kind,
                    target,
                    state,
                    json.dumps(reason),
                    evidence,
                    actor,
                ),
            )
            c.execute(
                "INSERT INTO decision_heads(bid_id,object_kind,object_id,revision,decision_id) VALUES(%s,%s,%s,1,%s)",
                (value["bid"], kind, target, decision),
            )
        c.execute(
            "INSERT INTO samples(id,bid_id,submission_id,outcome_id,source_group_id,known_at,admission,reasons) VALUES(%s,%s,%s,%s,%s,%s,'admitted','[]')",
            (sample, value["bid"], value["submission"], result, sample, value["known"]),
        )
    prepared = web.post(
        f"/api/v1/research/reviews/{value['review']}/chapter-packages",
        json={},
        headers=headers(),
    )
    assert prepared.status_code == 201, prepared.text
    return value | {
        "sample_id": str(sample),
        "outcome_id": str(result),
        "verification_id": str(verify),
        "grouping_id": str(grouping),
    }


def cohort(client, *, final_blob_id=None):
    """Initialize a complete old frozen cohort, then use actual guarded APIs."""
    web, actor, headers, _ = client
    items = [item(client) for _ in range(4)]
    items.append(item(client, year=2025, body_blob_id=final_blob_id))
    protocol = bundle()["protocol"]
    registered = web.post(
        "/api/v1/model-governance/training-protocols",
        json={"document": protocol, "reason": "Synthetic existing v1 cohort bridge fixture"},
        headers=headers(),
    )
    if registered.status_code == 409:
        registered = web.get(
            "/api/v1/model-governance/training-protocols/"
            + registered.json()["details"]["protocol_id"]
        )
    assert registered.status_code in {200, 201}, registered.text
    cohort_id, experiment, preview, run = [uid() for _ in range(4)]
    members, rows, labels = [], [], []
    with connection() as c:
        blob = c.execute(
            "SELECT blob_id FROM document_versions WHERE id=%s", (items[0]["body"],)
        ).fetchone()["blob_id"]
        c.execute(
            "INSERT INTO experiments(id,protocol_digest,dataset_manifest_blob_id,split_manifest_blob_id,method_digest,seed,state) VALUES(%s,%s,%s,%s,%s,5,'succeeded')",
            (experiment, sha("synthetic-preexisting-v1"), blob, blob, sha("fixture-v1")),
        )
        c.execute(
            "INSERT INTO experiment_previews(id,experiment_id,revision,manifest_digest,request,price_config_digest,estimated_calls,estimated_tokens,estimated_fee,fee_limit,currency,expires_at,created_by) VALUES(%s,%s,1,%s,'{}',%s,0,0,0,0,'USD',clock_timestamp()+interval '1 hour',%s)",
            (preview, experiment, sha("fixture-v1"), sha("fixture-no-provider"), actor),
        )
        c.execute(
            "INSERT INTO research_runs(id,experiment_id,preview_id,revision,manifest_digest,state,fee_limit,currency) VALUES(%s,%s,%s,1,%s,'succeeded',0,'USD')",
            (run, experiment, preview, sha("fixture-v1")),
        )
        c.execute(
            "INSERT INTO model_governance.cohorts(id,research_run_id,protocol_id,digest,origin,test_start,created_by) VALUES(%s,%s,%s,%s,'synthetic','2025-01-01Z',%s)",
            (cohort_id, run, registered.json()["id"], sha(str(cohort_id)), actor),
        )
        for data, purpose in zip(
            items, ("fit", "fit", "development", "calibration", "final"), strict=True
        ):
            c.execute(
                "INSERT INTO model_governance.members(cohort_id,sample_id,purpose,bid_id,submission_id,outcome_id,group_id,project_id,body_digest,grouping_decision_id,verification_decision_id,identity_authority_id,identity_snapshot,submitted_at,known_at) SELECT %s,s.id,%s,s.bid_id,s.submission_id,s.outcome_id,s.source_group_id,(r.evidence#>>'{identity,engineering_project_id}')::uuid,b.digest,%s,%s,(r.evidence#>>'{identity,authority_id}')::uuid,r.evidence->'identity',r.submitted_at,s.known_at FROM samples s JOIN submission_records r ON r.id=s.submission_id JOIN document_versions v ON v.id=r.body_version_id JOIN blobs b ON b.id=v.blob_id WHERE s.id=%s",
                (
                    cohort_id,
                    purpose,
                    data["grouping_id"],
                    data["verification_id"],
                    data["sample_id"],
                ),
            )
            c.execute(
                "INSERT INTO model_governance.chapter_bindings SELECT %s,%s,cp.id FROM chapter_packages cp WHERE cp.review_id=%s",
                (cohort_id, data["sample_id"], data["review"]),
            )
            for version, parse_purpose in (
                (data["body"], "body"),
                (data["tender"], "rule"),
                (data["source"], "official"),
            ):
                parse = c.execute(
                    "SELECT id FROM parse_runs WHERE document_version_id=%s", (version,)
                ).fetchone()["id"]
                source = parse_source_id(parse)
                c.execute(
                    "INSERT INTO model_governance.parse_bindings VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        cohort_id,
                        data["sample_id"],
                        parse,
                        version,
                        source,
                        original_source_id(version),
                        parse_purpose,
                    ),
                )
                c.execute(
                    "INSERT INTO model_governance.evidence_bindings SELECT %s,%s,e.parse_id,e.id,e.physical_page,e.ordinal,e.digest FROM evidence_blocks e WHERE e.parse_id=%s",
                    (cohort_id, data["sample_id"], parse),
                )
                c.execute(
                    "INSERT INTO model_governance.source_bindings SELECT %s,%s,a.source_id,a.ancestor_id,h.revision,n.digest,n.policy_class,n.known_at,h.valid_from,h.valid_until FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.ancestor_id JOIN retrieval.source_heads h ON h.source_id=n.id WHERE a.source_id=%s",
                    (cohort_id, data["sample_id"], source),
                )
            m = clean(
                c.execute(
                    "SELECT * FROM model_governance.members WHERE cohort_id=%s AND sample_id=%s",
                    (cohort_id, data["sample_id"]),
                ).fetchone()
            )
            members.append(
                {
                    key: m[key]
                    for key in (
                        "purpose",
                        "project_id",
                        "group_id",
                        "body_digest",
                        "template_key",
                        "near_duplicate_key",
                        "known_at",
                        "submitted_at",
                    )
                }
                | {"id": m["sample_id"]}
            )
            row = {
                "id": m["sample_id"],
                "features": [0, 1, 0, 1],
                "target": 0,
                "maximum": 60,
                "project_id": m["project_id"],
                "group_id": m["group_id"],
                "method": "explicit-synthetic-existing-v1",
                "purpose": purpose,
                "engineering_type": None,
            }
            if purpose == "final":
                labels.append(row)
            else:
                rows.append(row)
            c.execute(
                "INSERT INTO research_preview_samples SELECT %s,sample_id,group_id,grouping_decision_id,'submission_evidence',identity_authority_id,identity_snapshot FROM model_governance.members WHERE cohort_id=%s AND sample_id=%s",
                (preview, cohort_id, data["sample_id"]),
            )
        exports = {
            "training": {
                "schema": "purpose-bound-training-export/1",
                "origin": "synthetic",
                "protocol": protocol,
                "members": members,
                "rows": rows,
                "test_start": "2025-01-01T00:00:00Z",
            },
            "final_features": {
                "schema": "clean-final-feature-export/1",
                "origin": "synthetic",
                "rows": [{k: v for k, v in row.items() if k != "target"} for row in labels],
            },
            "final_labels": {
                "schema": "sealed-final-label-export/1",
                "origin": "synthetic",
                "rows": [{k: v for k, v in row.items() if k != "features"} for row in labels],
            },
        }
        for name, payload in exports.items():
            c.execute(
                "INSERT INTO model_governance.exports VALUES(%s,%s,%s,%s,%s)",
                (uid(), cohort_id, name, digest(payload), Jsonb(payload)),
            )
        assert c.execute(
            "SELECT model_governance.current_cohort(%s) AS value", (cohort_id,)
        ).fetchone()["value"], (
            "Unchanged legacy guard must pass the complete synthetic historical fixture"
        )
    response = web.get("/api/v1/model-governance/cohorts/" + str(cohort_id))
    assert response.status_code == 200 and response.json()["current"], response.text
    return {"id": str(cohort_id), "run_id": str(run), "items": items, "response": response}


def research_attempt(client, frozen):
    """Explicit pre-existing research preview; actual schedule/acquire/read afterward."""
    actor = client[1]
    with connection() as c:
        rows = [
            {
                "id": item["sample_id"],
                "submission_id": item["submission"],
                "outcome_id": item["outcome_id"],
                "body_version_id": item["body"],
                "chapter_packages": batches.chapter_refs(c, item["submission"]),
            }
            for item in frozen["items"]
        ]
    raw = json.dumps({"synthetic": True, "samples": rows}, ensure_ascii=False).encode()
    blob, experiment, preview, run = [uid() for _ in range(4)]
    object_key = "synthetic-preexisting-research/" + str(blob)
    storage.put(object_key, raw, batches.DATASET_MEDIA)
    request = {
        "dataset_manifest_blob_id": str(blob),
        "sample_ids": [r["id"] for r in rows],
        "profile_digest": profile.digest(),
        "method_digest": profile.digest(),
        "concurrency": 1,
    }
    with connection() as c:
        c.execute(
            "INSERT INTO blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,%s,%s)",
            (blob, sha(raw), object_key, len(raw), batches.DATASET_MEDIA),
        )
        c.execute(
            "INSERT INTO experiments(id,protocol_digest,dataset_manifest_blob_id,split_manifest_blob_id,method_digest,seed,state) VALUES(%s,%s,%s,%s,%s,5,'created')",
            (experiment, sha("explicit-existing-research"), blob, blob, profile.digest()),
        )
        c.execute(
            "INSERT INTO experiment_previews(id,experiment_id,revision,manifest_digest,request,price_config_digest,estimated_calls,estimated_tokens,estimated_fee,fee_limit,currency,expires_at,created_by) VALUES(%s,%s,1,%s,%s,%s,0,0,0,1,'USD',clock_timestamp()+interval '1 hour',%s)",
            (preview, experiment, sha(request), Jsonb(request), sha(batches.price_config()), actor),
        )
        c.execute(
            "INSERT INTO research_runs(id,experiment_id,preview_id,revision,manifest_digest,state,fee_limit,currency) VALUES(%s,%s,%s,1,%s,'queued',1,'USD')",
            (run, experiment, preview, sha(request)),
        )
        c.execute(
            "INSERT INTO research_preview_samples SELECT %s,sample_id,group_id,grouping_decision_id,'submission_evidence',identity_authority_id,identity_snapshot FROM model_governance.members WHERE cohort_id=%s",
            (preview, frozen["id"]),
        )
        c.execute(
            "INSERT INTO research_preview_chapters SELECT %s,sample_id,chapter_package_id FROM model_governance.chapter_bindings WHERE cohort_id=%s",
            (preview, frozen["id"]),
        )
        selected = frozen["items"][0]
        c.execute(
            "INSERT INTO research_run_items(run_id,sample_id,bid_id,repeat_index,state) VALUES(%s,%s,%s,1,'pending')",
            (run, selected["sample_id"], selected["bid"]),
        )
    message = execution.schedule_one(run)
    assert message is not None
    lease = execution.acquire(message)
    assert lease is not None
    return message, lease
