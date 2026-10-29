"""Native material to private synthetic findings; not an actual review or grant."""
# ruff: noqa: F401,F811

import json
import os
from pathlib import Path

import pytest
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
from test_package_material_scope_findings import checked, draft_for
from test_package_technical_material import context

from packages.model_governance import package_material_scope_findings as findings
from packages.model_governance import package_material_scope_review as review
from packages.model_governance import package_scope_findings_store as store_port
from packages.storage.private_cas import PrivateContentStore

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_MATERIAL_SCOPE_FINDINGS_PG") != "1",
    reason="explicit grouped evidence findings required",
)


def test_native_frozen_review_items_bind_complete_citations_without_issuer_authority(
    wire, tmp_path
):
    w, state, url = wire
    acquired = native_collect(w, url)
    ctx = context(acquired)
    packet = review.build(
        ctx,
        expected_context_digest=ctx.metadata["digest"],
        expected_method_digest=review.method_digest(),
    )
    result = checked(packet, draft_for(packet))
    m = result.metadata
    assert m["all_findings_claimed_confirmed"] and m["all_images_claimed_reviewed"]
    assert len(m["draft"]["findings"]) == 15 and state["attempts"] == 2
    assert m["reviewer_identity_verified"] is False and m["necessary_scope_verified"] is False
    item = next(
        r
        for r in packet.metadata["check_items"]
        if r["subject"] == {"rule_id": w["multi_source_rule"]}
    )
    row = next(r for r in m["draft"]["findings"] if r["check_id"] == item["check_id"])
    assert len(row["citations"]) == 3
    assert findings.verify(result, expected_digest=m["digest"]).metadata == m
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    with PrivateContentStore(root) as store:
        key = store_port.save(
            store,
            result,
            expected_findings_digest=m["digest"],
            expected_method_digest=store_port.method_digest(),
        )
    with PrivateContentStore(root) as reopened:
        restored = store_port.load(
            reopened,
            packet,
            commit_digest=key,
            expected_findings_digest=m["digest"],
            expected_method_digest=store_port.method_digest(),
        )
    assert restored.metadata == m
    directory = os.environ.get("FUSION_MATERIAL_SCOPE_FINDINGS_EVIDENCE")
    if directory:
        (Path(directory) / "material-scope-findings-native-proof.json").write_text(
            json.dumps(
                {
                    "checked_findings_digest": m["digest"],
                    "findings_method_digest": findings.method_digest(),
                    "findings_store_method_digest": store_port.method_digest(),
                    "findings_commit_digest": key,
                    "private_store_closed_and_reopened": True,
                    "review_digest": m["review_digest"],
                    "context_digest": m["context_digest"],
                    "finding_count": 15,
                    "selected_rule_citations": 3,
                    "actual_loopback_gets": 2,
                    "synthetic_review_claims": True,
                    "actual_human_review": False,
                    "reviewer_identity_verified": False,
                    "necessary_scope_verified": False,
                    "input_authority_granted": False,
                    "provider_attempts": 0,
                    "body_exported": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
