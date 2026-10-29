"""Explicit synthetic extraction receipts inside the grouped checks database; no model."""

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_bid_package_requirements_api import package_extraction_document, uid

from packages.domain.bid_package_extraction import freeze_matching_input, record_completion
from packages.domain.bid_package_repository import load_revision
from packages.domain.review_data import save_json
from packages.domain.review_identity import digest
from packages.domain.runtime import enqueue_plan


def seed_receipt(w, monkeypatch, coverage="complete"):
    from packages.domain import storage

    c = w["database"]["owner"]
    assert c.info.dbname == "fusion_package_requirements_api"
    bid = w["scope"].bid_id
    authority = load_revision(c, bid, w["inventory_body"]["authority_revision_id"])
    document = package_extraction_document(c, authority)
    method = {"engine": "synthetic-inventory-scope-only", "version": "1"}
    frozen = freeze_matching_input(c, bid, str(uid()), [document], method, digest(method))
    assert frozen is not None
    objects = {}
    monkeypatch.setattr(storage, "put", lambda key, data, media: objects.__setitem__(key, data))
    monkeypatch.setattr(storage, "get", lambda key: objects[key])
    monkeypatch.setenv("WORKER_DATABASE_DSN", w["database"]["worker_dsn"])
    blob = save_json(
        {"documents": [document], "package_rule_extraction_input": frozen}, worker=True
    )
    command_id, operation_digest = uid(), digest({"synthetic": frozen["digest"]})
    with c.transaction():
        c.execute(
            "INSERT INTO design.commands(id,actor_id,command_kind,target_id,idempotency_key,request_digest) VALUES(%s,%s,'synthetic-inventory-scope',%s,%s,%s)",
            (command_id, w["actor"], bid, uid(), operation_digest),
        )
        operation = enqueue_plan(
            c,
            bid,
            command_id,
            "prepare-review",
            {"id": blob["id"]},
            stages=[{"key": "extract-rules", "depends_on": []}],
            handler_version="prepare/1",
            topic="tender.task.review.v1",
            input_digest=operation_digest,
        )
    result = {
        "input_digest": frozen["digest"],
        "rule_set_id": w["inventory_body"]["rule_set_id"],
        "authority_revision_id": authority.revision_id,
        "authority_digest": authority.manifest_digest,
        "method_digest": digest(method),
        "range_status": "all_frozen_evidence_submitted",
        "read_evidence_ids_digest": digest(sorted(block["id"] for block in document["blocks"])),
        "extraction_coverage": coverage,
        "quality_status": "not_measured",
    }
    message = {
        "bid_id": bid,
        "operation_id": operation["id"],
        "input_digest": operation_digest,
        "payload_ref": blob["id"],
    }
    with psycopg.connect(w["database"]["worker_dsn"], row_factory=dict_row) as worker:
        worker.execute("SET search_path=design,public")
        record_completion(worker, message, frozen, w["inventory_body"]["rule_set_id"], result)
        worker.execute(
            "INSERT INTO design.effect_receipts(operation_id,effect_key,result) VALUES(%s,'extract-rules',%s)",
            (
                operation["id"],
                Jsonb(
                    {
                        "result_ref": result["rule_set_id"],
                        "method_digest": result["method_digest"],
                        "extraction_input_digest": frozen["digest"],
                    }
                ),
            ),
        )
        worker.execute(
            "UPDATE design.operations SET state='succeeded',finished_at=now() WHERE id=%s",
            (operation["id"],),
        )
    return c.execute(
        "SELECT id::text FROM design.bid_package_requirement_extraction_runs WHERE operation_id=%s",
        (operation["id"],),
    ).fetchone()["id"]
