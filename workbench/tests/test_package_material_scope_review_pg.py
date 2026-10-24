"""Native frozen material to complete review denominator, no semantic qualification."""
# ruff: noqa: F401,F811

import json
import os
from copy import deepcopy
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
from test_package_material_scope_review import refresh
from test_package_technical_material import context

from packages.model_governance import package_material_scope_review as review

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_MATERIAL_SCOPE_REVIEW_PG") != "1",
    reason="explicit grouped native scope review required",
)


def test_native_checklist_retains_complete_packages_and_entire_inventory(wire):
    w, state, url = wire
    acquired = native_collect(w, url)
    ctx = context(acquired)
    packet = review.build(
        ctx,
        expected_context_digest=ctx.metadata["digest"],
        expected_method_digest=review.method_digest(),
    )
    m = packet.metadata
    assert len(m["requirements"]) == len(acquired.material["inventory"]["manifest"]["requirements"])
    assert len(m["documents"]) == sum(
        len(acquired.material[role]["manifest"]["members"]) for role in ("target", "authority")
    )
    assert len(m["parts"]) == sum(
        len(member["parts"])
        for role in ("target", "authority")
        for member in acquired.material[role]["manifest"]["members"]
    )
    selected = next(row for row in m["requirements"] if row["rule_id"] == w["multi_source_rule"])
    assert (
        len(selected["available_source_evidence_ids"]) == 3
        and len(selected["frozen_inventory_binding"]["rule_snapshot"]["bands"]) == 2
    )
    assert any(row["declared_selection"] == "exclude" for row in m["requirements"])
    assert (
        m["frozen_scope_coverage"]
        == ctx.metadata["material"]["scope"]["manifest"]["preview"]["manifest"]["coverage"]
    )
    assert state["attempts"] == 2 and m["necessary_scope_verified"] is False
    assert review.verify(packet, expected_digest=m["digest"]).metadata == m
    directory = os.environ.get("FUSION_MATERIAL_SCOPE_REVIEW_EVIDENCE")
    if directory:
        (Path(directory) / "material-scope-review-native-proof.json").write_text(
            json.dumps(
                {
                    "scope_review_digest": m["digest"],
                    "scope_review_method_digest": review.method_digest(),
                    "context_digest": ctx.metadata["digest"],
                    "document_rows": len(m["documents"]),
                    "part_rows": len(m["parts"]),
                    "inventory_requirements": len(m["requirements"]),
                    "review_items": len(m["check_items"]),
                    "selected_rule_sources": 3,
                    "selected_rule_bands": 2,
                    "actual_loopback_gets": 2,
                    "synthetic_content": True,
                    "all_items_unreviewed": all(
                        item["state"] == "unreviewed" for item in m["check_items"]
                    ),
                    "input_authority_granted": False,
                    "native_binding_registered": False,
                    "provider_attempts": 0,
                    "body_exported": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize("fault", ["inventory", "part_projection"])
def test_post_acquisition_projection_fault_cannot_hide_review_items(wire, fault):
    w, state, url = wire
    acquired = deepcopy(native_collect(w, url))
    if fault == "inventory":
        rows = acquired.material["inventory"]["manifest"]["requirements"]
        rows[:] = [r for r in rows if r["rule_id"] != w["multi_source_rule"]]
    else:
        acquired.material["scope"]["manifest"]["preview"]["manifest"]["parts"][0][
            "read_physical_pages"
        ].clear()
    ctx = context(refresh(acquired))
    with pytest.raises(review.MaterialScopeReviewError):
        review.build(
            ctx,
            expected_context_digest=ctx.metadata["digest"],
            expected_method_digest=review.method_digest(),
        )
