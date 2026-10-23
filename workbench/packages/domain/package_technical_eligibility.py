"""Exact scope/authority joins, without granting scores or historical samples.

Inputs to this module come only from the server repository adapter. A scope
declaration is never a complete-range/visual certificate. The two purposes keep
labels separate and never replace original times with the time of this read.
"""

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from packages.contracts import package_technical_eligibility_api as contract
from packages.domain import package_technical_scope as scopes
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, sha
from packages.model_governance.scale_evidence import validate_maximum_declaration
from packages.rag.indexing import parse_source_id

JUDGMENTS = {
    "required_valid_independent": 3,
    "recorded_valid_independent": 0,
    "producer_authority": "not_configured_for_exact_package",
    "previous_answers_in_input": False,
    "retries_count_as_independent": False,
    "unknown_send_auto_retry": False,
    "execution_enabled": False,
}


def reason(code, message, subject=None):
    return scopes.gap(code, subject, message)


def distinct(values):
    return list({value["id"]: value for value in values}.values())


def instant(value):
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("aware event time required")
    return result.astimezone(timezone.utc)


def plain_decimal(value):
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed < 0 or parsed > Decimal("1000000000"):
        raise ValueError("finite nonnegative bounded decimal required")
    return format(parsed, "f")


def reference(saved):
    manifest = saved["manifest"]
    return {
        **manifest["preview"]["manifest"]["scope"],
        "scope_id": manifest["id"],
        "scope_digest": saved["digest"],
    }


def missing_scale(purpose, scale_id=None, *, configured=True, unavailable=False):
    code, message, state = (
        ("TECHNICAL_SCALE_NOT_SELECTED", "尚未选择有据技术满分权威，满分保持未知。", "unselected")
        if scale_id is None
        else (
            "TECHNICAL_SCALE_AUTHORITY_NOT_CONFIGURED",
            "独立满分权威未安装，不能从逐项分值或官方标签推算技术满分。",
            "not_configured",
        )
        if not configured
        else (
            "TECHNICAL_SCALE_UNAVAILABLE",
            "所选满分权威当前不可用，不能以登记值代替有据有效值。",
            "unavailable",
        )
    )
    return {
        "state": state,
        "scale_id": scale_id,
        "scale_digest": None,
        "purpose": purpose,
        "technical_maximum": None,
        "scale_description": None,
        "aggregation": None,
        "maximum_usable": False,
        "aggregation_usable": False,
        "evidence_refs": [],
        "reasons": [reason(code, message, scale_id)],
    }


def scale_assessment(saved, snapshot, scale, *, purpose, submission_id=None):
    """Bind the registry's current authority to this exact frozen authority parse.

    The registry verifies identity/proofs/complete ancestor currentness. This
    additional join rejects a later parse or a different authority with the same
    text. A maximum never establishes an executable aggregation formula.
    """
    preview = saved["manifest"]["preview"]["manifest"]
    scale_id = scale["id"]
    result = missing_scale(purpose, scale_id, unavailable=True)
    result["scale_digest"] = digest(scale)
    gaps = []
    identity = snapshot["target"]["identity"]
    if (
        scale["bid_id"] != preview["scope"]["bid_id"]
        or scale["purpose"] != purpose
        or scale["submission_id"] != submission_id
        or scale["identity"] != identity
    ):
        gaps.append(
            reason(
                "TECHNICAL_SCALE_SCOPE_MISMATCH",
                "满分用途、实交或完整工程／标段／轮次／主体身份与确切范围不一致。",
                scale_id,
            )
        )
    if not (
        scale["maximum_usable"] is True
        and scale["current_applicability"] is True
        and scale["is_current_head"] is True
        and scale["state"] == "confirmed"
        and scale["decision"] is not None
        and scale["decision"]["state"] == "confirmed"
    ):
        gaps.append(
            reason(
                "TECHNICAL_SCALE_NOT_CURRENT",
                "独立满分权威未确认、已更正、已撤回或其原件／来源效力已失效。",
                scale_id,
            )
        )
    authority = {
        document["document_version_id"]: document
        for document in preview["documents"]
        if document["package_role"] == "authority"
    }
    source_rows = {
        (row["source_id"], row["ancestor_id"]): row for row in preview["source_snapshot"]
    }
    valid_refs, maximum_proven = [], False
    refs = scale["evidence_refs"]
    if not refs or len({ref["id"] for ref in refs}) != len(refs):
        gaps.append(
            reason("TECHNICAL_SCALE_EVIDENCE_UNPROVEN", "满分缺少不重复的确切原页依据。", scale_id)
        )
    for ref in refs:
        document = authority.get(ref["document_version_id"])
        block = (
            next((row for row in document["blocks"] if row["id"] == ref["evidence_id"]), None)
            if document
            else None
        )
        row = source_rows.get((ref["source_id"], ref["source_id"]))
        try:
            matches = (
                document is not None
                and document["parse"]["status"] == "frozen"
                and document["parse"]["parse_run_id"] == ref["parse_id"]
                and document["file_digest"] == ref["blob_digest"]
                and block is not None
                and block["physical_page"] == ref["physical_page"]
                and block["digest"] == ref["evidence_digest"]
                and sha(block["text_content"].encode()) == block["digest"]
                and block["text_content"] == ref["quote"]
                and ref["source_id"] == str(parse_source_id(UUID(ref["parse_id"])))
                and row is not None
                and row["revision"] == ref["source_revision"]
                and row["document_version_id"] == document["document_version_id"]
                and row["digest"] == document["file_digest"]
            )
            if not matches or block is None:
                raise ValueError("exact authority evidence mismatch")
            if {"technical_maximum", "scale_description"} & set(ref["supported_fields"]):
                validate_maximum_declaration(
                    source_text=block["text_content"],
                    quote=ref["quote"],
                    maximum=scale["technical_maximum"],
                    scale_description=scale["scale_description"],
                )
                maximum_proven |= {"technical_maximum", "scale_description"} <= set(
                    ref["supported_fields"]
                )
            valid_refs.append(deepcopy(ref))
        except (KeyError, TypeError, ValueError, InvalidOperation, DomainError):
            gaps.append(
                reason(
                    "TECHNICAL_SCALE_EXACT_EVIDENCE_MISMATCH",
                    "满分依据不属于此范围冻结的权威原件、解析、原页全文或来源修订。",
                    ref["evidence_id"],
                )
            )
    if not maximum_proven:
        gaps.append(
            reason(
                "TECHNICAL_SCALE_DECLARATION_UNPROVEN",
                "同一完整原文须明确技术总满分和量尺，不能以条款和、权重或结果标签替代。",
                scale_id,
            )
        )
    if gaps:
        result.update(state="mismatched", reasons=distinct(gaps))
        return result
    try:
        maximum = plain_decimal(scale["technical_maximum"])
        if Decimal(maximum) <= 0:
            raise ValueError("positive maximum required")
    except (ValueError, InvalidOperation):
        return result
    result.update(
        state="matched",
        technical_maximum=maximum,
        scale_description=scale["scale_description"],
        aggregation=deepcopy(scale["aggregation"]),
        maximum_usable=True,
        evidence_refs=valid_refs,
        reasons=[
            reason(
                "TECHNICAL_AGGREGATION_NOT_EXECUTABLE",
                "满分已有据绑定，官方聚合规则尚未形成可执行协议，不能生成数值估分。",
                scale_id,
            )
        ],
    )
    return result


def execution_gaps(preview):
    return [
        *deepcopy(preview["coverage"]["gaps"]),
        reason(
            "PACKAGE_TECHNICAL_PRODUCER_NOT_CONFIGURED",
            "多册确切范围尚未配置专用评分生产者；单正文生产者不能替代此范围。",
        ),
        reason(
            "THREE_VALID_INDEPENDENT_JUDGMENTS_REQUIRED",
            "每个适用评分项须有同一冻结输入的三次有效独立判断；失败和重试不计入三次。",
        ),
        reason(
            "ORIGINAL_BYTES_RECHECK_REQUIRED",
            "本上下文只核对数据库原件身份；正式执行前须再次核对实际原字节。",
        ),
    ]


def scoring_context(saved, snapshot, denominator, *, observed_at, observation_error=None):
    preview = saved["manifest"]["preview"]["manifest"]
    gaps = []
    method_matches = preview["method"] == scopes.policy_identity()
    fingerprint = scopes.context_digest(snapshot) if snapshot is not None else None
    if snapshot is None:
        gaps.append(
            reason(
                observation_error or "TECHNICAL_INPUT_UNAVAILABLE",
                "所冻结完整输入当前无法准确还原；原范围记录保留，不能继续评分。",
            )
        )
    else:
        gaps.extend(deepcopy(snapshot["blocking_reasons"]))
        if fingerprint != preview["context_digest"]:
            gaps.append(
                reason("TECHNICAL_INPUT_CHANGED", "当前包、清单、身份或来源与冻结范围不同。")
            )
    if not method_matches:
        gaps.append(reason("TECHNICAL_SCOPE_METHOD_CHANGED", "范围方法已有变化，须显式重新冻结。"))
    result = {
        "version": "package-technical-scoring-context/1",
        "purpose": "current_prebid",
        "scope": reference(saved),
        "basis": deepcopy(preview["basis"]),
        "observed_at": observed_at,
        "current_input": {
            "state": "unavailable" if snapshot is None else "changed" if gaps else "matched",
            "stored_context_digest": preview["context_digest"],
            "current_context_digest": fingerprint,
            "method_matches": method_matches,
            "original_bytes_reverified": False,
            "reasons": distinct(gaps),
        },
        "coverage": deepcopy(preview["coverage"]),
        "denominator": denominator,
        "judgments": deepcopy(JUDGMENTS),
        "numeric_prediction": None,
        "blockers": distinct([*gaps, *denominator["reasons"], *execution_gaps(preview)]),
        "official_label_access": "forbidden",
        **scopes.FLAGS,
    }
    return contract.validate("PackageTechnicalScoringContext", result)


def sample_context(
    saved,
    snapshot,
    submission,
    binding,
    official,
    denominator,
    *,
    observed_at,
    submission_current,
    observation_error=None,
):
    preview = saved["manifest"]["preview"]["manifest"]
    original = binding["manifest"]
    selection = original["selection"]
    scope = preview["scope"]
    basis = preview["basis"]
    gaps = []
    target, authority, inventory = (
        selection[name] for name in ("target", "authority", "inventory")
    )
    matches = (
        submission["subject_kind"] == "bid_package"
        and original["subject"]
        == {
            "kind": "bid_package",
            "bid_id": scope["bid_id"],
            "package_id": scope["package_id"],
            "revision_id": scope["revision_id"],
            "package_digest": basis["package_digest"],
        }
        and target["identity"]["digest"] == basis["identity_digest"]
        and original["package_identity"] == target["identity"]
        and authority is not None
        and authority["manifest"]["revision_id"] == basis["authority_revision_id"]
        and authority["digest"] == basis["authority_digest"]
        and authority["identity"] == original["package_identity"]
        and inventory is not None
        and inventory["manifest"]["id"] == scope["inventory_id"]
        and inventory["digest"] == basis["inventory_digest"]
    )
    if not matches:
        gaps.append(
            reason(
                "SAMPLE_EXACT_SCOPE_MISMATCH",
                "实交必须逐项绑定同一技术子范围、包、权威、清单及完整主体／标段／轮次身份。",
                submission["id"],
            )
        )
    if not submission_current:
        gaps.append(
            reason("SAMPLE_SUBMISSION_SUPERSEDED", "所选实交已被更正，不能授予新样本资格。")
        )
    before = instant(saved["manifest"]["frozen_at"]) <= instant(submission["submitted_at"])
    if not before:
        gaps.append(
            reason(
                "SAMPLE_SCOPE_FROZEN_AFTER_SUBMISSION",
                "技术范围或原字节在实交后才冻结，不能伪装当时已存在的严格事前输入。",
            )
        )
    sources_match = (
        snapshot is not None
        and snapshot["documents"] == preview["documents"]
        and snapshot["source_snapshot"] == preview["source_snapshot"]
    )
    if not sources_match:
        gaps.append(
            reason(
                observation_error or "SAMPLE_SOURCE_METADATA_CHANGED",
                "精确原件／解析／全部来源祖先当前无法还原原冻结内容，不能只信历史回执。",
            )
        )
    # Current package and inventory heads may legitimately move after submission;
    # they do not rewrite this historical subject. Source and identity invalidity
    # still block a new sample and are never converted into historical proof.
    if snapshot is not None:
        gaps.extend(
            deepcopy(row)
            for row in snapshot["blocking_reasons"]
            if row["code"] not in {"AFTER_SUBMISSION", "PACKAGE_HEAD_CHANGED", "INVENTORY_CHANGED"}
        )
    submitted = instant(submission["submitted_at"])
    for row in preview["source_snapshot"]:
        try:
            valid = (
                instant(row["known_at"]) <= submitted
                and instant(row["valid_from"]) <= submitted
                and (row["valid_until"] is None or instant(row["valid_until"]) > submitted)
                and row["policy_class"] == "prebid_content"
                and row["status"] == "published"
            )
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            gaps.append(
                reason(
                    "SAMPLE_HISTORICAL_SOURCE_TIME_UNPROVEN",
                    "完整来源祖先必须在原实交时已知且有效，当前有效不能补写过去。",
                    row.get("ancestor_id"),
                )
            )
    gaps.extend(
        [
            reason(
                "PACKAGE_HISTORICAL_PROOF_AUTHORITY_NOT_CONFIGURED",
                "逐原件的历史存在、本方知晓与条款生效证明尚无整包专用权威；范围登记不能替代。",
            ),
            reason(
                "PACKAGE_RESEARCH_TIMING_NOT_FROZEN",
                "训练冻结、实交分割和标签可用截止时间尚未由独立研究权威冻结，不补默认值。",
            ),
            reason(
                "PACKAGE_TECHNICAL_SAMPLE_ADMISSION_NOT_CONFIGURED",
                "整包正式样本准入尚未开放，本次只读核对不创建或提升样本。",
            ),
        ]
    )
    result = {
        "version": "package-technical-sample-context/1",
        "purpose": "historical_backtest",
        "scope": reference(saved),
        "basis": deepcopy(basis),
        "observed_at": observed_at,
        "submission": {
            "id": submission["id"],
            "binding_digest": binding["digest"],
            "submitted_at": submission["submitted_at"],
            "recorded_at": submission["created_at"],
            "is_current_head": submission_current,
            "matches_scope": matches,
            "platform_submission_verified": False,
        },
        "official_result": official,
        "timing": {
            "scope_frozen_at": saved["manifest"]["frozen_at"],
            "historical_as_of": submission["submitted_at"],
            "submitted_at": submission["submitted_at"],
            "label_known_at": official["label_known_at"],
            "training_frozen_at": None,
            "submission_split_at": None,
            "label_available_as_of": None,
            "strict_timing_ready": False,
        },
        "original_scope_precedes_submission": before,
        "source_metadata_matches": sources_match,
        "coverage": deepcopy(preview["coverage"]),
        "denominator": denominator,
        "judgments": deepcopy(JUDGMENTS),
        "numeric_prediction": None,
        "blockers": distinct(
            [*gaps, *official["reasons"], *denominator["reasons"], *execution_gaps(preview)]
        ),
        "sample_state": "pending",
        "sample_created": False,
        "official_label_access": "association_check_only",
        **scopes.FLAGS,
    }
    return contract.validate("PackageTechnicalSampleContext", result)
