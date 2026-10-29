"""Real native read ports, private Linux filesystem and loopback original GETs."""
# ruff: noqa: F401,F811

import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path

import psycopg
import pytest
from psycopg.pq import TransactionStatus
from test_package_current_material_pg import (
    api,
    database,
    exact,
    pdf_data,
    requirements,
    saved,
    world,
)
from test_package_current_material_pg import collect as native_collect
from test_package_current_original_set_pg import wire
from test_package_technical_material import bound

from packages.domain.review_identity import canonical
from packages.model_governance import package_current_parse_material as parses
from packages.model_governance import package_material_recovery as recovery
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import PrivateContentStore

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_MATERIAL_RECOVERY_PG") != "1",
    reason="explicit grouped native recovery required",
)


def setup(wire, tmp_path):
    w, state, url = wire
    original = native_collect(w, url)
    bundle = bound(original)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    with PrivateContentStore(root) as store:
        key = recovery.save(
            store,
            bundle.context,
            expected_context_digest=bundle.metadata["context_digest"],
            expected_method_digest=recovery.method_digest(),
        )
    return root, key, bundle


def restore(root, key, bundle, wire, **changes):
    w, state, url = wire
    args = {
        "recovery_commit_digest": key,
        "expected_context_digest": bundle.metadata["context_digest"],
        "expected_method_digest": recovery.method_digest(),
        "bid_id": w["technical_scope"][0],
        "scope_id": w["saved_scope"]["manifest"]["id"],
        "expected_scope_digest": w["saved_scope"]["digest"],
        "profile": "development_s3",
        "url_for_locator": url,
    } | changes
    with PrivateContentStore(root) as store:
        return asyncio.run(
            recovery.restore(
                store,
                w["database"]["scope_verifier"],
                w["database"]["original_verifier"],
                w["database"]["parse_verifier"],
                **args,
            )
        )


def test_native_reopen_recovers_exact_v3_request_and_separate_fresh_observation(wire, tmp_path):
    w, state, url = wire
    root, key, bundle = setup(wire, tmp_path)
    before = canonical(bundle.context.metadata)
    result = restore(root, key, bundle, wire)
    assert canonical(result.context.metadata) == before
    assert result.context.origin.metadata == bundle.context.origin.metadata
    assert state["attempts"] == state["idle_checks"] == 4
    assert all(
        w["database"][k].info.transaction_status == TransactionStatus.IDLE
        for k in ("scope_verifier", "original_verifier", "parse_verifier")
    )
    new_input = material.bind_input(
        result.context,
        bundle.metadata["binding_reference"],
        expected_context_digest=bundle.metadata["context_digest"],
        expected_binding_digest=bundle.metadata["binding_reference_digest"],
        expected_method_digest=material.method_digest(),
    )
    rule = w["multi_source_rule"]
    first = vision.prepare_request(
        bundle,
        rule,
        expected_input_digest=bundle.metadata["digest"],
        expected_serializer_digest=vision.serializer_digest(),
    )
    second = vision.prepare_request(
        new_input,
        rule,
        expected_input_digest=new_input.metadata["digest"],
        expected_serializer_digest=vision.serializer_digest(),
    )
    assert first.body == second.body and first.receipt == second.receipt
    assert (
        result.metadata["fresh_final_parse_digest"]
        != bundle.context.origin.metadata["final_parse_observation"]["digest"]
    )
    assert result.metadata["exact_frozen_context_recovered"] is True
    assert result.metadata["page_assets_rerendered"] is False
    for field in (
        "native_binding_verified",
        "necessary_scope_verified",
        "input_authority_granted",
        "execution_authorized",
        "historical_existence_verified",
    ):
        assert result.metadata[field] is False
    directory = os.environ.get("FUSION_MATERIAL_RECOVERY_EVIDENCE")
    if directory:
        (Path(directory) / "material-recovery-native-proof.json").write_text(
            json.dumps(
                {
                    "recovery_observation": result.metadata,
                    "synthetic_content": True,
                    "synthetic_binding_reference_only": True,
                    "native_binding_registered": False,
                    "actual_loopback_gets": 4,
                    "recovery_loopback_gets": 2,
                    "exact_request_bytes_preserved": True,
                    "context_time_and_digest_preserved": True,
                    "private_filesystem_closed_and_reopened": True,
                    "provider_attempts": 0,
                    "in_process_renderer_used_only_at_initial_acquisition": True,
                    "body_exported": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize("mutation", ["closed", "withdrawn", "revision"])
def test_stale_native_facts_reject_before_new_get_and_keep_frozen_commit(wire, tmp_path, mutation):
    w, state, url = wire
    root, key, bundle = setup(wire, tmp_path)
    old = (root / "commits" / key).read_bytes()
    owner = w["database"]["owner"]
    if mutation == "closed":
        owner.execute(
            "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
            (w["technical_scope"][0],),
        )
    else:
        source = w["saved_scope"]["manifest"]["preview"]["manifest"]["source_snapshot"][0][
            "source_id"
        ]
        if mutation == "withdrawn":
            owner.execute(
                "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
                (source,),
            )
        else:
            owner.execute(
                "UPDATE retrieval.source_heads SET revision=revision+1 WHERE source_id=%s",
                (source,),
            )
    with pytest.raises(ValueError):
        restore(root, key, bundle, wire)
    assert state["attempts"] == 2
    assert (root / "commits" / key).read_bytes() == old


def test_frozen_native_pages_are_immutable_and_recovery_preserves_them(wire, tmp_path):
    w, state, url = wire
    root, key, bundle = setup(wire, tmp_path)
    parse = bundle.context.origin.material["native_documents"][0]["parse_run_id"]
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable_record"):
        w["database"]["owner"].execute(
            "UPDATE design.pages SET quality='partial' WHERE bid_id=%s AND parse_id=%s AND physical_page=1",
            (w["technical_scope"][0], parse),
        )
    result = restore(root, key, bundle, wire)
    assert result.context.metadata == bundle.context.metadata
    assert state["attempts"] == 4


def test_native_parse_projection_fault_is_rejected_before_original_get(wire, tmp_path, monkeypatch):
    w, state, url = wire
    root, key, bundle = setup(wire, tmp_path)
    observe = parses.observe

    def faulty(*args, **kwargs):
        actual = deepcopy(observe(*args, **kwargs))
        actual.documents[0]["pages"][0]["quality"] = "partial"
        return actual

    monkeypatch.setattr(parses, "observe", faulty)
    with pytest.raises(ValueError, match="FROZEN_PARSE_CONTENT_MISMATCH"):
        restore(root, key, bundle, wire)
    assert state["attempts"] == 2


def test_corrupt_fresh_original_discards_recovery(wire, tmp_path):
    w, state, url = wire
    root, key, bundle = setup(wire, tmp_path)
    state["corrupt"] = True
    with pytest.raises(ValueError, match="BYTES_MISMATCH"):
        restore(root, key, bundle, wire)
    assert state["attempts"] == 3


def test_last_get_scope_close_discards_all_recovered_bytes(wire, tmp_path):
    w, state, url = wire
    root, key, bundle = setup(wire, tmp_path)

    def close():
        if state["attempts"] == 4:
            w["database"]["owner"].execute(
                "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
                (w["technical_scope"][0],),
            )

    state["callback"] = close
    with pytest.raises(ValueError, match="NOT_CURRENT_PREBID"):
        restore(root, key, bundle, wire)
    assert state["attempts"] == 4


def test_cancelled_original_read_returns_no_context_and_connections_idle(wire, tmp_path):
    w, state, url = wire
    root, key, bundle = setup(wire, tmp_path)

    class Cancel:
        async def read(self, *args, **kwargs):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        restore(root, key, bundle, wire, byte_client=Cancel())
    assert state["attempts"] == 2
    assert all(
        w["database"][k].info.transaction_status == TransactionStatus.IDLE
        for k in ("scope_verifier", "original_verifier", "parse_verifier")
    )
