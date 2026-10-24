"""Actual host rendering and independent native private storage, no local CAS."""
# ruff: noqa: F401,F811

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from test_fusion_context_derivation_native import collect, freeze, runtime
from test_native_material_store_pg import database
from test_package_current_material_pg import api, exact, pdf_data, requirements, saved, world
from test_package_current_original_set_pg import wire
from test_package_material_scope_findings import checked, draft_for

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_material_scope_review as review
from packages.model_governance import package_native_material_store as store

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_NATIVE_MATERIAL_STORE_HOST") != "1",
    reason="explicit trusted host native private store integration required",
)


def test_actual_context_derivation_full_report_and_png_reopen_in_native_private_store(
    wire, runtime
):
    w, state, url = wire
    frozen = freeze(wire, runtime)
    live = collect(wire, runtime, frozen)
    plan = review.build(
        live.context,
        expected_context_digest=frozen.metadata["digest"],
        expected_method_digest=review.method_digest(),
    )
    report = checked(plan, draft_for(plan))
    p = store.prepare(
        live,
        report,
        expected_context_digest=frozen.metadata["digest"],
        expected_findings_digest=report.metadata["digest"],
        expected_derivation_digest=live.metadata["digest"],
        expected_producer_method_digest=live.metadata["method_digest"],
        expected_method_digest=store.method_digest(),
    )
    command = str(uuid4())
    packet_digest = digest(p.packet)
    record = store.put(
        w["database"]["material_writer"],
        p,
        command_id=command,
        expected_packet_digest=packet_digest,
        expected_method_digest=store.method_digest(),
    )
    args = {
        "bid_id": frozen.metadata["bid_id"],
        "command_id": command,
        "expected_packet_digest": packet_digest,
        "expected_record_digest": record.metadata["digest"],
        "expected_method_digest": store.method_digest(),
    }
    with w["database"]["material_reader_factory"]() as reopened:
        loaded = store.load(reopened, **args)
    assert canonical(loaded.context_metadata) == canonical(frozen.metadata)
    assert canonical(loaded.derivation_observation) == canonical(live.metadata)
    assert canonical(loaded.findings_metadata) == canonical(report.metadata)
    assert loaded.image_blobs == {
        key: raw
        for bundle in live.context.origin.page_bundles.values()
        for key, raw in bundle.blobs.items()
    }
    assert state["attempts"] == state["idle_checks"] == 4
    assert not any(record.metadata["document"][k] for k in store.FLAGS)
    directory = Path(os.environ["FUSION_NATIVE_MATERIAL_STORE_HOST_EVIDENCE"])
    (directory / "host-native-material-store-proof.json").write_text(
        json.dumps(
            {
                "store_method_digest": store.method_digest(),
                "producer_method_digest": live.metadata["method_digest"],
                "record": record.metadata,
                "object_count": len(p.objects),
                "asset_count": len(p.packet["image_objects"]),
                "actual_loopback_gets": 4,
                "actual_fresh_compose_sessions": 7,
                "physical_pages": 4,
                "frozen_details": 1,
                "actual_renderer_used": True,
                "exact_context_derivation_report_and_png_bytes_recovered_after_reopen": True,
                "private_native_byte_store_verified": True,
                "windows_private_acl_backend_installed": False,
                "synthetic_material": True,
                "synthetic_review_claims": True,
                "actual_human_review": False,
                "input_authority_granted": False,
                "provider_attempts": 0,
                "body_exported": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
