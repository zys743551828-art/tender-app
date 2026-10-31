"""Generated-body new-use guards with explicit read-only observations, no providers."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator
from test_bid_package_frozen_originals import snapshots  # noqa: F401
from test_bid_package_scope_review import observe, ports  # noqa: F401
from test_package_scope_review import case  # noqa: F401

from packages.authoring import package_outputs
from packages.contracts.bid_package_requirements_api import SCHEMAS
from packages.domain import bid_package_frozen_originals as originals
from packages.domain import bid_package_review_documents as documents
from packages.domain import bid_package_review_policy as policy
from packages.domain import bid_package_review_repository as repository
from packages.domain import bid_package_scope_review as scope_review
from packages.domain.runtime import DomainError


def uid(number):
    return str(UUID(int=number))


@pytest.fixture
def member_db(monkeypatch):
    bid, document, parse = uid(1), uid(2), uid(3)
    member = {
        "member_id": "generated-body",
        "document_version_id": document,
        "file_digest": "a" * 64,
        "page_count": 1,
        "parse": {
            "status": "frozen",
            "parse_run_id": parse,
            "parser_digest": "b" * 64,
            "config_digest": "c" * 64,
            "evidence_digest": "d" * 64,
        },
    }
    row = {
        "document_version_id": document,
        "blob_id": uid(4),
        "digest": "a" * 64,
        "byte_size": 10,
        "object_key": "private-original",
        "parse_id": parse,
        "parser_digest": "b" * 64,
        "config_digest": "c" * 64,
        "page_count": 1,
        "coverage": "complete",
        "gaps": [],
    }
    state = {
        "row": row,
        "observation": {"state": "matched", "proof_digest": "e" * 64, "image_heads": []},
        "calls": [],
    }

    class Connection:
        def execute(self, sql, params=()):
            assert sql.lstrip().startswith("SELECT")
            assert "FOR UPDATE" not in sql and "FOR SHARE" not in sql
            if sql == (
                "SELECT to_regclass('design.word_render_runs') IS NOT NULL AND "
                "to_regclass('design.word_intake_receipts') IS NOT NULL AS ready, "
                "to_regclass('design.build_outputs') IS NOT NULL AS authoring_ready"
            ):
                assert params == ()
                # This fixture models authoring outputs without the optional
                # Word runtime tables. Authoring admission still runs below.
                result = [{"ready": False, "authoring_ready": True}]
            elif "FROM design.document_versions" in sql:
                result = [state["row"]] if params == (bid, document, parse) else []
            elif "FROM design.pages" in sql:
                result = [{"physical_page": 1, "quality": "usable", "gaps": []}]
            elif "FROM design.evidence_blocks" in sql:
                result = []
            else:
                raise AssertionError(sql)
            return SimpleNamespace(
                fetchone=lambda: deepcopy(result[0]) if result else None,
                fetchall=lambda: deepcopy(result),
            )

    connection = Connection()

    def observe(c, selected_bid, selected_document):
        assert c is connection and (selected_bid, selected_document) == (bid, document)
        state["calls"].append((selected_bid, selected_document))
        return deepcopy(state["observation"])

    monkeypatch.setattr(package_outputs, "observe_admission", observe, raising=False)
    monkeypatch.setattr(
        documents,
        "read_parse_identity",
        lambda *_args, **_kwargs: SimpleNamespace(
            parser_digest="b" * 64, config_digest="c" * 64, evidence_digest="d" * 64
        ),
    )
    return connection, bid, member, state


@pytest.mark.parametrize(
    "observation",
    [
        {"state": "blocked", "blockers": ["AUTHORING_IMAGE_STALE"]},
        {"state": "blocked", "blockers": ["AUTHORING_OUTPUT_NOT_QUALIFIED"]},
        {"state": "unknown", "blockers": []},
    ],
)
def test_previously_adopted_member_cannot_be_read_for_new_use_after_qualification_changes(
    member_db, observation
):
    c, bid, member, state = member_db
    state["observation"] = observation
    with pytest.raises(DomainError) as error:
        documents.read_member(c, bid, member)
    assert error.value.code == "PACKAGE_REVIEW_GENERATED_OUTPUT_UNPROVEN"
    assert state["calls"] == [(bid, member["document_version_id"])]


@pytest.mark.parametrize("generated", [False, True])
def test_standard_original_and_valid_generated_member_keep_existing_frozen_document_shape(
    member_db, generated
):
    c, bid, member, state = member_db
    if not generated:
        state["observation"] = None
    value = documents.read_member(c, bid, member)
    assert state["calls"] == [(bid, member["document_version_id"])]
    assert value == state["row"] | {
        "member_id": member["member_id"],
        "pages": [{"physical_page": 1, "quality": "usable", "gaps": []}],
        "blocks": [],
    }


def test_parse_matching_does_not_mislabel_a_withdrawn_image_as_parse_corruption(member_db):
    c, bid, member, state = member_db
    state["observation"] = {"state": "blocked", "blockers": ["AUTHORING_IMAGE_STALE"]}
    manifest = {
        "bid_id": bid,
        "target": {"manifest": {"members": [member]}},
        "authority": {"manifest": {"members": []}},
    }
    assert documents.evidence_matches(c, manifest)
    # The dedicated source-policy observation, rather than this parse-only check,
    # explains the new-use blocker in previews and eligibility observations.
    assert state["calls"] == []


def selection():
    source = {
        "policy_class": "prebid_content",
        "status": "published",
        "known_at": "2026-01-01T00:00:00+00:00",
        "valid_from": "2026-01-01T00:00:00+00:00",
        "valid_until": None,
    }
    manifest = {
        "bid_id": uid(1),
        **{
            role: {
                "identity": {"digest": "identity"},
                "storage_eligible": True,
                "manifest": {
                    "package_id": role,
                    "revision_id": role + "-revision",
                    "scope": {"bidder_status": "confirmed"},
                    "members": [
                        {
                            "member_id": role,
                            "document_version_id": uid(index),
                            "page_count": 1,
                            "parts": [{"first_page": 1, "last_page": 1}],
                        }
                    ],
                },
            }
            for role, index in (("target", 2), ("authority", 3))
        },
        "inventory": {
            "manifest": {
                "id": "inventory",
                "rule_set_id": "rules",
                "source_snapshot": [source],
                "extraction_binding": "exact_frozen_input_result",
                "inventory_complete": False,
            }
        },
    }
    observed = {
        "current": {"identity": {"digest": "identity"}, "current_rule_set_id": "rules"},
        "lifecycle": {"phase": "working", "archived_at": None},
        "package_heads": {"target": "target-revision", "authority": "authority-revision"},
        "inventory_head": {"id": "inventory"},
        "sources": [source],
        "at": datetime(2026, 10, 21, tzinfo=timezone.utc),
    }
    return manifest, observed


def test_generated_observation_is_bound_to_each_exact_logical_package_use(monkeypatch):
    selected, expected = selection()
    c = object()
    seen = []
    receipt = {"state": "matched", "proof_digest": "f" * 64, "image_heads": []}

    def fetch(_c, sql, params=()):
        assert _c is c
        if "identity_snapshot" in sql:
            return deepcopy(expected["current"])
        assert "clock_timestamp" in sql
        return {"at": expected["at"]}

    def observe(_c, bid, document):
        assert _c is c and bid == uid(1)
        seen.append(document)
        return deepcopy(receipt) if document == uid(2) else None

    monkeypatch.setattr(repository, "fetch", fetch)
    monkeypatch.setattr(repository, "profile", lambda *_args: expected["lifecycle"])
    monkeypatch.setattr(
        repository.packages,
        "_all",
        lambda *_args: [
            {"package_id": key, "revision_id": value}
            for key, value in expected["package_heads"].items()
        ],
    )
    monkeypatch.setattr(repository.requirements, "head", lambda *_args: expected["inventory_head"])
    monkeypatch.setattr(
        repository.requirements, "_source_snapshot", lambda *_args: expected["sources"]
    )
    monkeypatch.setattr(package_outputs, "observe_admission", observe, raising=False)
    value = repository.observations(c, selected)
    assert seen == [uid(2), uid(3)]
    assert value["generated_outputs"] == [
        {
            "package_role": "target",
            "member_id": "target",
            "document_version_id": uid(2),
            "admission": receipt,
        }
    ]


@pytest.mark.parametrize("state", ["blocked", "unknown"])
def test_preview_preserves_parse_match_but_blocks_invalid_generated_qualification(state):
    selected, observed = selection()
    baseline = policy.evaluate(selected, observed, evidence_matches=True)
    observed["generated_outputs"] = [
        {
            "package_role": "target",
            "member_id": "target",
            "document_version_id": uid(2),
            "admission": {"state": state, "blockers": ["AUTHORING_IMAGE_STALE"]},
        }
    ]
    result = policy.evaluate(selected, observed, evidence_matches=True)
    assert set(result["blockers"]) == set(baseline["blockers"]) | {
        "PACKAGE_REVIEW_GENERATED_OUTPUT_UNPROVEN"
    }
    assert "PACKAGE_REVIEW_EVIDENCE_CHANGED" not in result["blockers"]


def test_matched_generated_observation_does_not_grant_any_new_readiness():
    selected, observed = selection()
    baseline = policy.evaluate(selected, observed, evidence_matches=True)
    observed["generated_outputs"] = [{"admission": {"state": "matched", "proof_digest": "f" * 64}}]
    assert policy.evaluate(selected, observed, evidence_matches=True) == baseline


def test_generated_qualification_blocker_is_part_of_public_observation_contracts():
    code = "PACKAGE_REVIEW_GENERATED_OUTPUT_UNPROVEN"
    for name in (
        "PackageReviewInputPreview",
        "PackageReviewEligibilityObservation",
        "PackageExecutionInputManifest",
    ):
        assert Draft202012Validator(SCHEMAS[name]["properties"]["blockers"]).is_valid([code]), name


def test_generated_asset_observation_changes_across_original_io_prevent_verification(
    snapshots,  # noqa: F811
):
    snapshots["snapshot"]["observations"]["generated_outputs"] = [
        {"admission": {"state": "matched", "images": [{"head_revision": 1}]}}
    ]

    def withdraw():
        snapshots["snapshot"]["observations"]["generated_outputs"][0]["admission"] = {
            "state": "blocked",
            "reason_code": "AUTHORING_IMAGE_STALE",
        }

    snapshots["during_io"] = withdraw
    with pytest.raises(DomainError) as error:
        originals.verify(
            ("bid", "package", "revision", "inventory"), "input", "frozen-digest", "context"
        )
    assert error.value.code == "PACKAGE_REVIEW_INPUT_CHANGED"
    assert snapshots["active"] == 0


def test_final_scope_publication_rechecks_new_use_qualification_after_provider_return(
    ports,  # noqa: F811
):
    verified = scope_review.verify(observe(ports))
    ports["snapshot"]["observations"]["generated_outputs"] = [
        {
            "package_role": "target",
            "member_id": "main-bid",
            "admission": {"state": "blocked", "reason_code": "AUTHORING_IMAGE_STALE"},
        }
    ]
    ports["events"].clear()
    with pytest.raises(DomainError) as error:
        scope_review.recheck(ports["Connection"](), verified)
    assert error.value.code == "PACKAGE_REVIEW_INPUT_CHANGED"
    assert ports["events"][:4] == [
        "SHOW transaction_isolation",
        "bid-lock",
        ("writable", False),
        "graph-lock",
    ]
    assert "original-io" not in ports["events"]
