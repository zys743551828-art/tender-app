"""Additive saved-authoring resolutions and choices; preserve frozen A endpoints."""

from contextlib import contextmanager

from packages.contracts import work_context_catalog_api as contract
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError
from packages.work_contexts import (
    authoring_observations,
    authoring_repository,
    catalog,
    catalog_permissions,
    policy,
    repository,
)
from packages.work_contexts import service as base


@contextmanager
def snapshot(kind):
    native = {"package_review_run": "run", "package_submission": "submission"}.get(
        kind, "relations"
    )
    try:
        with base.snapshot(native) as c:
            if kind in {"draft_snapshot", "build"}:
                catalog_permissions.require(c)
            yield c
    except DomainError as error:
        if error.code.startswith("WORK_CONTEXT_"):
            raise
        raise DomainError(
            "WORK_CONTEXT_CORRUPT", "明确选择的历史正文或原生关联证明不能核验", 500
        ) from error


def _context(c, saved, built=None):
    selection = built["selection"] if built else saved["selection"]
    at = repository.at(c)
    value = {
        "version": "authoring-work-context/1",
        "selection": selection,
        "selection_digest": digest(selection),
        "snapshot": saved["metadata"],
        "document": None if built else saved["document"],
        "build": built["details"] if built else None,
        "current_observation": authoring_observations.observe(c, saved, at),
        "summary": {
            "perspective": "saved_authoring_history",
            "whole_package_blocking_risk_count": None,
            "whole_package_passed": None,
            "formal_scoring": {
                "status": "scope_not_selected",
                "scope_id": None,
                "numeric_prediction": None,
            },
            "official_labels_read": False,
            "primary_action": "view_selected_build" if built else "open_selected_snapshot",
            "action_mode": "navigation_only",
        },
        "native_targets": {
            "draft_snapshot": saved["selection"],
            "current_draft": {
                "kind": "draft",
                "bid_id": selection["bid_id"],
                "draft_id": selection["draft_id"],
            },
            "build": built["selection"] if built else None,
            "build_relations": {
                "kind": "build_package_relations",
                "bid_id": selection["bid_id"],
                "build_id": selection["build_id"],
            }
            if built
            else None,
        },
        "original_bytes_reverified": False,
        "qualification_assessed": False,
        "limitations": [
            "SAVED_SNAPSHOT_NOT_CURRENT_EDITOR",
            "AUTHORING_SCOPE_IS_NOT_PACKAGE_SELECTION",
            "SOURCE_GRAPH_HISTORY_NOT_FROZEN",
            "CURRENT_USE_QUALIFICATION_UNASSESSED",
            "ORIGINAL_BYTES_NOT_REVERIFIED",
            "WHOLE_PACKAGE_RISK_NOT_ASSESSED",
            "FORMAL_SCORING_SCOPE_NOT_SELECTED",
            "OFFICIAL_LABELS_NOT_READ",
            "READ_CONTEXT_IS_NOT_WRITE_AUTHORITY",
        ],
    }
    value["observation_digest"] = digest(value)
    value["observed_at"] = at
    return catalog.validated("AuthoringWorkContext", value)


def _expected(value, expected_digest):
    if expected_digest is not None and expected_digest != value["selection_digest"]:
        policy.fail(
            "SELECTION_CHANGED", "返回身份与明确固定的历史选择不一致，请保留原选择后核对", 412
        )
    return value


def resolve_snapshot(bid, snapshot_id, *, expected_selection_digest=None):
    base.request_ids(bid, snapshot_id)
    with snapshot("draft_snapshot") as c:
        saved = authoring_repository.snapshot(c, bid, snapshot_id)
        return _expected(_context(c, saved), expected_selection_digest)


def resolve_build(bid, build_id, *, expected_selection_digest=None):
    base.request_ids(bid, build_id)
    with snapshot("build") as c:
        built = authoring_repository.build(c, bid, build_id)
        return _expected(_context(c, built["snapshot"], built), expected_selection_digest)


def choices(bid, kind, *, limit=20, cursor=None, draft_id=None, package_id=None, revision_id=None):
    base.request_ids(
        bid, *(item for item in (draft_id, package_id, revision_id) if item is not None)
    )
    if kind not in contract.KINDS or type(limit) is not int or not 1 <= limit <= 50:
        policy.fail("REQUEST_INVALID", "请选择一个明确阶段和 1 至 50 的目录页大小", 422)
    with snapshot(kind) as c:
        return catalog.page(
            c,
            bid,
            kind,
            limit=limit,
            cursor=cursor,
            draft_id=draft_id,
            package_id=package_id,
            revision_id=revision_id,
        )
