"""Derive append-only technical outline suggestions from a current locked package basis."""

import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from packages.authoring.structure_model import MAX_ACTIVE, ordered
from packages.domain import bid_package_requirement_repository as requirements
from packages.domain.bid_packages import PackageError
from packages.domain.rule_sets import current_decision
from packages.domain.runtime import DomainError, sha

HEADINGS = {
    "overview": ("工程概况与施工部署", ("概况", "范围", "部署", "重难点")),
    "method": ("主要施工方法与技术措施", ("工法", "工艺", "技术措施", "施工方法", "专项方案")),
    "schedule": ("施工进度与资源配置", ("工期", "进度", "资源", "机械", "设备", "劳动力")),
    "quality": ("质量管理与验收", ("质量", "验收", "检验", "检测")),
    "safety": ("安全文明施工与环境保护", ("安全", "文明施工", "环保", "环境", "应急")),
}
KEY_PREFIX = "technical-bid-"
_KEY = re.compile(KEY_PREFIX + r"[a-f0-9]{64}-(?:" + "|".join(HEADINGS) + ")")


def is_outline_key(key: str) -> bool:
    return _KEY.fullmatch(key) is not None


@dataclass(frozen=True)
class LockedOutline:
    # Only references, hashes, and fixed heading keys enter the proposed action.
    basis: dict
    suggested: tuple[str, ...]


def _stale():
    return DomainError(
        "TECHNICAL_OUTLINE_BASIS_STALE",
        "大纲的投标包、依据包、要求清单或确认已变化，请重新选择当前依据并预览。",
        409,
    )


def _rule_suggestions(bindings) -> tuple[str, ...]:
    statements = []
    for row in bindings:
        rule = row["rule_snapshot"]
        requirement = row["requirement"]
        if (
            row["annotation"]["mapped"]
            and any(category in ("技术", "technical") for category in requirement["categories"])
            and row["source_bound"]
            and (row["decision_snapshot"] or {}).get("decision") == "confirmed"
            and rule["provenance_status"] == "effective"
            and requirement["applicability"] == "applicable"
            and rule.get("evidence_ids")
        ):
            statements.append(rule["statement"])
    return tuple(
        key
        for key, (_, terms) in HEADINGS.items()
        if any(term in statement for statement in statements for term in terms)
    )


def capture(c, bid: UUID, basis: dict) -> LockedOutline:
    """Caller holds the project's write lock; requirement context also locks source effectivity."""
    target, authority, selected = basis["target"], basis["authority"], basis["inventory"]
    project = str(bid)
    try:
        inventory = requirements.load_inventory(
            c, project, target["package_id"], target["revision_id"], selected["id"]
        )
        manifest = inventory["manifest"]
        own, source, ident, rules, sources = requirements._context(
            c,
            project,
            target["package_id"],
            target["revision_id"],
            authority["revision_id"],
            manifest["rule_set_id"],
        )
        head = requirements.head(c, own.revision_id, lock=True)
    except PackageError as error:
        if error.code.endswith("CORRUPT"):
            raise DomainError(
                "TECHNICAL_OUTLINE_BASIS_CORRUPT", "固定的要求清单或资料包无法核验。", 503
            ) from error
        raise _stale() from None
    except DomainError as error:
        if error.code != "NOT_FOUND":
            raise
        raise _stale() from None
    if (
        not head
        or head["id"] != selected["id"]
        or head["digest"] != selected["digest"]
        or inventory["digest"] != selected["digest"]
        or own.manifest_digest != target["digest"]
        or own.manifest_digest != manifest["package_digest"]
        or source.package_id != authority["package_id"]
        or source.revision_id != manifest["authority_revision_id"]
        or source.manifest_digest != authority["digest"]
        or source.manifest_digest != manifest["authority_digest"]
        or rules["digest"] != manifest["rule_set_digest"]
        or ident["digest"] != manifest["identity_digest"]
        or not sources
        or sources != manifest["source_snapshot"]
    ):
        raise _stale()
    for row in manifest["requirements"]:
        decision = current_decision(c, project, "rule", row["rule_id"])
        if (str(decision["id"]) if decision else None) != row["decision_id"] or (
            decision and decision["decision"] != (row["decision_snapshot"] or {}).get("decision")
        ):
            raise _stale()
    # Bind the semantics as well as the identities; both are checked at confirmation.
    return LockedOutline(basis, _rule_suggestions(manifest["requirements"]))


def build_changes(state, contents, selected, captured: LockedOutline):
    if len(selected) != len(set(selected)) or not set(selected) <= set(captured.suggested):
        raise DomainError(
            "TECHNICAL_OUTLINE_SELECTION_INVALID", "只能选择当前已核对要求支持的大纲章节。", 422
        )
    live = list(ordered(state["nodes"]))
    known = {
        unicodedata.normalize("NFKC", contents[item["section_id"]]["attrs"]["title"]).strip()
        for item in live
    }
    roots = sum(item["parent_id"] is None for item in live)
    result: list[dict[str, object]] = []
    for key in captured.suggested:
        if key not in selected:
            continue
        title = HEADINGS[key][0]
        if title in known:
            continue
        ordinal = roots + len(result)
        if len(live) + len(result) >= MAX_ACTIVE:
            raise DomainError(
                "TECHNICAL_OUTLINE_TREE_LIMIT", "章节数量已达目录限制，请先调整目录。", 422
            )
        result.append(
            {
                "op": "add",
                "client_key": f"{KEY_PREFIX}{captured.basis['inventory']['digest']}-{key}",
                "title": title,
                "node_type": "chapter",
                "parent": None,
                "ordinal": ordinal,
            }
        )
    if not result:
        raise DomainError(
            "TECHNICAL_OUTLINE_NO_NEW_CHAPTERS", "没有需要追加的新章，未覆盖现有目录。", 422
        )
    return result


def verify_apply(c, bid: UUID, stored: dict):
    captured = capture(c, bid, stored["basis"])
    if sha(captured.suggested) != stored["suggested_digest"]:
        raise _stale()
