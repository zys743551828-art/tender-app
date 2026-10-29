"""Native material and synthetic price policy, without a real pricing registry."""
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
from test_package_material_cost import quote

from packages.model_governance import package_material_cost as cost

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_MATERIAL_COST_PG") != "1",
    reason="explicit grouped native cost preview required",
)


def test_native_whole_input_quote_counts_all_included_rules_and_retry_capacity(wire):
    w, state, url = wire
    acquired = native_collect(w, url)
    result = quote(acquired, max_attempts_per_slot=2, budget_ceiling_minor=cost.SAFE_INTEGER)
    m = result.metadata
    included = [
        r["rule_id"] for r in result.context.metadata["rules"] if r["selection"] == "include"
    ]
    assert m["rule_ids"] == included and m["required_valid_slots"] == 3 * len(included)
    assert m["maximum_external_calls"] == 6 * len(included) and m[
        "required_reservation_minor"
    ] == 319488 * 6 * len(included)
    assert (
        cost.require_budget(
            result,
            expected_digest=m["digest"],
            expected_policy_digest=m["policy_digest"],
            as_of=m["as_of"],
        ).metadata
        == m
    )
    assert state["attempts"] == 2
    assert m["price_policy_native_verified"] is False and m["execution_authorized"] is False
    directory = os.environ.get("FUSION_MATERIAL_COST_EVIDENCE")
    if directory:
        (Path(directory) / "material-cost-native-proof.json").write_text(
            json.dumps(
                {
                    "quote": m,
                    "synthetic_price_policy": True,
                    "native_price_registry_installed": False,
                    "actual_loopback_gets": 2,
                    "provider_attempts": 0,
                    "paid_calls": 0,
                    "body_exported": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
