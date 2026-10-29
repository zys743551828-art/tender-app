"""Native /1 acquisition to complete /3 request and explicit mock provider only."""
# ruff: noqa: F401,F811

import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

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
from test_package_technical_material import bound, reseal, response, send

from packages.model_governance import package_complete_features as features
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import package_technical_material as inputs

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_COMPLETE_MATERIAL_PG") != "1",
    reason="explicit grouped complete model material required",
)


def test_native_full_material_to_actual_v3_wire_and_checked_judgment(wire):
    w, state, url = wire
    acquired = native_collect(w, url)
    bundle = bound(acquired)
    rule_id = w["multi_source_rule"]
    request = vision.prepare_request(
        bundle,
        rule_id,
        expected_input_digest=bundle.metadata["digest"],
        expected_serializer_digest=vision.serializer_digest(),
    )
    payload = json.loads(request.body)
    actual = json.loads(payload["messages"][1]["content"][0]["text"])
    assert len(actual["rule_packet"]["frozen_rule"]["source_evidence"]) == 3
    assert len(actual["rule_packet"]["bands"]) == 2
    assert len(actual["all_rule_declarations"]) == 4
    assert actual["material"] == acquired.material
    packet = next(r for r in bundle.context.metadata["rules"] if r["rule_id"] == rule_id)
    e = bundle.context.metadata["evidence_catalog"][0]
    data = {
        "status": "valid",
        "coverage": "complete",
        "band_id": packet["bands"][0]["band_id"],
        "reason": "Synthetic native scope support",
        "covered_part_ids": packet["required_part_ids"],
        "dimensions": {
            "specificity": "supported",
            "validity": "supported",
            "consistency": "uncertain",
        },
        "evidence": [
            {
                "evidence_id": e["id"],
                "document_version_id": e["document_version_id"],
                "parse_run_id": e["parse_run_id"],
                "physical_page": e["physical_page"],
                "page_image_digest": e["page_image_digest"],
                "quote": e["text_content"],
                "region": None,
            }
        ],
    }
    attempts = []
    wire_calls = 0
    for slot in (1, 2, 3):
        client, count = send(request, response(data, id=f"synthetic-native-response-{slot}"))
        generation = client.generate(
            request,
            expected_request_digest=request.receipt["request_digest"],
            expected_profile_digest=vision.profile_digest(),
        )
        wire_calls += len(count)
        attempts.append(
            features.CompleteJudgmentAttempt(
                rule_id, slot, 1, str(uuid4()), "succeeded", request, generation
            )
        )
    checked = features.aggregate_rule(
        bundle,
        rule_id,
        attempts,
        expected_input_digest=bundle.metadata["digest"],
        expected_method_digest=features.method_digest(),
    )
    assert checked["valid_slots"] == [1, 2, 3] and wire_calls == 3 and state["attempts"] == 2
    assert checked["input_authority_granted"] is False
    directory = os.environ.get("FUSION_COMPLETE_MATERIAL_EVIDENCE")
    if directory:
        (Path(directory) / "complete-material-native-proof.json").write_text(
            json.dumps(
                {
                    "native_observation_digest": acquired.metadata["digest"],
                    "native_material_digest": acquired.metadata["material_digest"],
                    "context_digest": bundle.context.metadata["digest"],
                    "input_digest": bundle.metadata["digest"],
                    "request_receipt": request.receipt,
                    "judgment_check": checked,
                    "synthetic_binding_reference_only": True,
                    "native_binding_registered": False,
                    "mock_provider_attempts": 3,
                    "real_original_loopback_gets": 2,
                    "full_rule_declarations": 4,
                    "selected_rule_source_evidence": 3,
                    "selected_rule_bands": 2,
                    "raw_body_exported": False,
                    "real_external_provider_attempts": 0,
                    "paid_calls": 0,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def test_native_sources_cannot_be_silently_reduced_after_acquisition(wire):
    w, state, url = wire
    acquired = deepcopy(native_collect(w, url))
    row = next(
        r
        for r in acquired.material["scope"]["manifest"]["preview"]["manifest"]["rules"]
        if r["rule_id"] == w["multi_source_rule"]
    )
    row["source_evidence"].pop()
    reseal(acquired)
    with pytest.raises(inputs.MaterialInputError, match="RULE_SOURCES_INCOMPLETE"):
        bound(acquired)
