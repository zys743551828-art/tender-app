"""整包领域契约 /1；纯模型，不改变现有单正文 API 或数据库。

包修订是值对象，JSON 输出总是重新构造。解析身份只能精确冻结或明确缺失，
不允许根据时间猜测。文件的逻辑部分不采用手工章节树的层级限制。
"""

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from packages.domain.review_identity import digest

MAX_SAFE_INTEGER = 9007199254740991


class PackageError(ValueError):
    """稳定的领域错误码，可由未来 API 映射；不含正文或密钥。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise PackageError(code)


def identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 200


def sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def safe_integer(value: object, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= MAX_SAFE_INTEGER


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value.value if isinstance(value, StrEnum) else value


class PackageKind(StrEnum):
    AUTHORITY = "authority"
    BID = "bid"


class CoverageState(StrEnum):
    NOT_PROVIDED = "not_provided"
    MISSING = "missing"
    PENDING_PARSE = "pending_parse"
    PARSE_GAP = "parse_gap"
    UNSUPPORTED = "unsupported"
    VERIFIED = "verified"
    NOT_APPLICABLE = "not_applicable"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BidScope:
    engineering_project_id: str
    lot_id: str
    round_id: str
    bid_id: str
    bidder_id: str
    bidder_status: str = "confirmed"

    def __post_init__(self) -> None:
        require(
            all(
                identifier(v)
                for v in (
                    self.engineering_project_id,
                    self.lot_id,
                    self.round_id,
                    self.bid_id,
                    self.bidder_id,
                )
            ),
            "PACKAGE_SCOPE_INVALID",
        )
        require(self.bidder_status in {"confirmed", "pending"}, "PACKAGE_BIDDER_STATUS_INVALID")


@dataclass(frozen=True)
class ParseIdentity:
    status: str
    parse_run_id: str | None = None
    parser_digest: str | None = None
    config_digest: str | None = None
    evidence_digest: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        require(self.status in {"frozen", "not_frozen"}, "PACKAGE_PARSE_STATUS_INVALID")
        if self.status == "frozen":
            require(identifier(self.parse_run_id), "PACKAGE_PARSE_ID_REQUIRED")
            require(
                all(
                    sha(v)
                    for v in (
                        self.parser_digest,
                        self.config_digest,
                        self.evidence_digest,
                    )
                ),
                "PACKAGE_PARSE_DIGEST_REQUIRED",
            )
            require(self.reason is None, "PACKAGE_PARSE_REASON_UNEXPECTED")
        else:
            require(
                all(
                    v is None
                    for v in (
                        self.parse_run_id,
                        self.parser_digest,
                        self.config_digest,
                        self.evidence_digest,
                    )
                ),
                "PACKAGE_PARSE_INFERRED_ID_FORBIDDEN",
            )
            require(identifier(self.reason), "PACKAGE_PARSE_REASON_REQUIRED")


@dataclass(frozen=True)
class DocumentPart:
    part_id: str
    category: str
    first_page: int
    last_page: int
    shared_attachment: bool = False
    heading_path: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        require(identifier(self.part_id) and identifier(self.category), "PACKAGE_PART_ID_INVALID")
        require(
            safe_integer(self.first_page, 1)
            and safe_integer(self.last_page, 1)
            and self.first_page <= self.last_page,
            "PACKAGE_PAGE_RANGE_INVALID",
        )
        require(type(self.shared_attachment) is bool, "PACKAGE_SHARED_FLAG_INVALID")
        require(
            isinstance(self.heading_path, tuple)
            and all(safe_integer(level, 1) for level in self.heading_path),
            "PACKAGE_HEADING_PATH_INVALID",
        )


@dataclass(frozen=True)
class PackageMember:
    member_id: str
    document_version_id: str
    file_digest: str
    source_kind: str
    source_ref: str
    scope: BidScope
    purposes: tuple[str, ...]
    page_count: int | None
    parse: ParseIdentity
    parts: tuple[DocumentPart, ...]

    def __post_init__(self) -> None:
        require(
            all(
                identifier(v)
                for v in (
                    self.member_id,
                    self.document_version_id,
                    self.source_ref,
                )
            ),
            "PACKAGE_MEMBER_ID_INVALID",
        )
        require(sha(self.file_digest), "PACKAGE_FILE_DIGEST_INVALID")
        require(self.source_kind in {"authority", "own"}, "PACKAGE_SOURCE_KIND_INVALID")
        require(
            isinstance(self.scope, BidScope) and isinstance(self.parse, ParseIdentity),
            "PACKAGE_MEMBER_BINDING_INVALID",
        )
        require(
            isinstance(self.purposes, tuple)
            and bool(self.purposes)
            and all(identifier(v) for v in self.purposes)
            and len(set(self.purposes)) == len(self.purposes),
            "PACKAGE_PURPOSE_INVALID",
        )
        require(
            self.page_count is None or safe_integer(self.page_count, 1),
            "PACKAGE_PAGE_COUNT_INVALID",
        )
        require(
            isinstance(self.parts, tuple)
            and all(isinstance(part, DocumentPart) for part in self.parts),
            "PACKAGE_PARTS_INVALID",
        )
        if self.page_count is None:
            require(not self.parts, "PACKAGE_UNKNOWN_PAGE_SCOPE_FORBIDDEN")
        if self.page_count is None or not self.parts:
            require(self.parse.status == "not_frozen", "PACKAGE_UNKNOWN_SCOPE_PARSE_FROZEN")
        require(len({p.part_id for p in self.parts}) == len(self.parts), "PACKAGE_PART_DUPLICATE")
        for index, part in enumerate(self.parts):
            require(
                self.page_count is not None and part.last_page <= self.page_count,
                "PACKAGE_PAGE_OUT_OF_BOUNDS",
            )
            for other in self.parts[:index]:
                overlap = max(part.first_page, other.first_page) <= min(
                    part.last_page, other.last_page
                )
                require(
                    not overlap or (part.shared_attachment and other.shared_attachment),
                    "PACKAGE_PART_OVERLAP_UNDECLARED",
                )


@dataclass(frozen=True)
class PackageRevision:
    package_id: str
    revision_id: str
    revision: int
    kind: PackageKind
    scope: BidScope
    members: tuple[PackageMember, ...]
    predecessor_digest: str | None = None
    identity_version: str = "bid-package/1"

    def __post_init__(self) -> None:
        require(identifier(self.package_id) and identifier(self.revision_id), "PACKAGE_ID_INVALID")
        require(safe_integer(self.revision, 1), "PACKAGE_REVISION_INVALID")
        require(
            isinstance(self.kind, PackageKind) and isinstance(self.scope, BidScope),
            "PACKAGE_BINDING_INVALID",
        )
        require(self.identity_version == "bid-package/1", "PACKAGE_IDENTITY_VERSION_INVALID")
        require(
            (self.revision == 1 and self.predecessor_digest is None)
            or (self.revision > 1 and sha(self.predecessor_digest)),
            "PACKAGE_PREDECESSOR_REQUIRED",
        )
        require(
            isinstance(self.members, tuple)
            and bool(self.members)
            and all(isinstance(member, PackageMember) for member in self.members),
            "PACKAGE_MEMBERS_INVALID",
        )
        require(
            len({m.member_id for m in self.members}) == len(self.members),
            "PACKAGE_MEMBER_DUPLICATE",
        )
        require(
            len({m.document_version_id for m in self.members}) == len(self.members),
            "PACKAGE_VERSION_DUPLICATE",
        )
        parse_ids = [m.parse.parse_run_id for m in self.members if m.parse.status == "frozen"]
        require(len(set(parse_ids)) == len(parse_ids), "PACKAGE_PARSE_ID_REUSED")
        part_ids: set[str] = set()
        for member in self.members:
            require(member.scope == self.scope, "PACKAGE_SCOPE_MISMATCH")
            expected = "authority" if self.kind == PackageKind.AUTHORITY else "own"
            require(member.source_kind == expected, "PACKAGE_SOURCE_KIND_MISMATCH")
            for part in member.parts:
                require(part.part_id not in part_ids, "PACKAGE_PART_DUPLICATE")
                part_ids.add(part.part_id)

    @property
    def formal_eligible(self) -> bool:
        return self.scope.bidder_status == "confirmed" and all(
            member.parse.status == "frozen" and member.page_count is not None and bool(member.parts)
            for member in self.members
        )

    def require_formal(self) -> None:
        require(self.scope.bidder_status == "confirmed", "PACKAGE_BIDDER_UNCONFIRMED")
        require(self.formal_eligible, "PACKAGE_PARSE_NOT_FROZEN")

    def manifest(self) -> dict[str, Any]:
        # 不持有外部可变dict；返回内容可序列化，数组顺序也是协议身份的一部分。
        return _json_value(asdict(self))

    @property
    def manifest_digest(self) -> str:
        return digest(self.manifest())

    def next_revision(
        self, revision_id: str, members: tuple[PackageMember, ...]
    ) -> "PackageRevision":
        require(revision_id != self.revision_id, "PACKAGE_REVISION_ID_REUSED")
        bindings = {
            member.parse.parse_run_id: _parse_binding(member)
            for member in self.members
            if member.parse.status == "frozen"
        }
        for member in members:
            if member.parse.status == "frozen" and member.parse.parse_run_id in bindings:
                require(
                    bindings[member.parse.parse_run_id] == _parse_binding(member),
                    "PACKAGE_PARSE_ID_REBOUND",
                )
        return PackageRevision(
            self.package_id,
            revision_id,
            self.revision + 1,
            self.kind,
            self.scope,
            members,
            self.manifest_digest,
        )


@dataclass(frozen=True)
class Requirement:
    requirement_id: str
    scope: BidScope
    origin: str
    source_refs: tuple[str, ...]
    categories: tuple[str, ...]
    target_part_ids: tuple[str, ...] = ()
    minimum_count: int | None = None
    applicability: str = "unknown"
    applicability_evidence: tuple[str, ...] = ()
    valid_at: str | None = None
    conditions: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    identity_version: str = "bid-requirement/1"

    def __post_init__(self) -> None:
        require(
            identifier(self.requirement_id) and isinstance(self.scope, BidScope),
            "PACKAGE_REQUIREMENT_ID_INVALID",
        )
        require(
            self.origin in {"authority", "company", "manual"}, "PACKAGE_REQUIREMENT_ORIGIN_INVALID"
        )
        for values in (
            self.source_refs,
            self.categories,
            self.target_part_ids,
            self.applicability_evidence,
            self.conditions,
            self.checks,
        ):
            require(
                isinstance(values, tuple)
                and all(identifier(v) for v in values)
                and len(set(values)) == len(values),
                "PACKAGE_REQUIREMENT_LIST_INVALID",
            )
        require(
            bool(self.source_refs) and bool(self.categories), "PACKAGE_REQUIREMENT_SOURCE_REQUIRED"
        )
        require(
            self.minimum_count is None or safe_integer(self.minimum_count),
            "PACKAGE_REQUIREMENT_COUNT_INVALID",
        )
        require(
            self.applicability in {"applicable", "unknown", "not_applicable"},
            "PACKAGE_APPLICABILITY_INVALID",
        )
        require(
            self.identity_version == "bid-requirement/1",
            "PACKAGE_REQUIREMENT_IDENTITY_VERSION_INVALID",
        )
        if self.applicability == "not_applicable":
            require(bool(self.applicability_evidence), "PACKAGE_NOT_APPLICABLE_EVIDENCE_REQUIRED")
        if self.valid_at is not None:
            require(
                isinstance(self.valid_at, str)
                and re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
                    self.valid_at,
                )
                is not None,
                "PACKAGE_VALID_AT_INVALID",
            )
            try:
                parsed = datetime.fromisoformat(self.valid_at.replace("Z", "+00:00"))
                require(parsed.utcoffset() is not None, "PACKAGE_TIMEZONE_REQUIRED")
            except (ValueError, AttributeError) as error:
                raise PackageError("PACKAGE_VALID_AT_INVALID") from error

    def manifest(self) -> dict[str, Any]:
        return _json_value(asdict(self))

    @property
    def manifest_digest(self) -> str:
        return digest(self.manifest())


@dataclass(frozen=True)
class InspectedRange:
    part_id: str
    first_page: int
    last_page: int

    def __post_init__(self) -> None:
        require(
            identifier(self.part_id)
            and safe_integer(self.first_page, 1)
            and safe_integer(self.last_page, 1)
            and self.first_page <= self.last_page,
            "PACKAGE_INSPECTED_RANGE_INVALID",
        )


@dataclass(frozen=True)
class RequirementCoverage:
    requirement_id: str
    package_digest: str
    requirement_digest: str
    state: CoverageState
    inspected: tuple[InspectedRange, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        require(
            identifier(self.requirement_id)
            and sha(self.package_digest)
            and sha(self.requirement_digest),
            "PACKAGE_COVERAGE_BINDING_INVALID",
        )
        require(isinstance(self.state, CoverageState), "PACKAGE_COVERAGE_STATE_INVALID")
        require(
            isinstance(self.inspected, tuple)
            and all(isinstance(r, InspectedRange) for r in self.inspected),
            "PACKAGE_INSPECTED_RANGE_INVALID",
        )
        require(
            isinstance(self.evidence_refs, tuple)
            and all(identifier(v) for v in self.evidence_refs),
            "PACKAGE_COVERAGE_EVIDENCE_INVALID",
        )
        require(self.reason is None or identifier(self.reason), "PACKAGE_COVERAGE_REASON_INVALID")
        if self.state in {CoverageState.VERIFIED, CoverageState.NOT_APPLICABLE}:
            require(bool(self.evidence_refs), "PACKAGE_COVERAGE_EVIDENCE_REQUIRED")
        else:
            require(identifier(self.reason), "PACKAGE_COVERAGE_REASON_REQUIRED")


def assess_coverage(
    package: PackageRevision,
    requirements: tuple[Requirement, ...],
    results: tuple[RequirementCoverage, ...],
    *,
    requirement_inventory_complete: bool = False,
) -> dict[str, Any]:
    """输出实际受检范围和全部状态；只有已声明完整的非空清单可整包通过。

    verified证明目标范围已经核验，不证明材料项合规，更不证明平台接受。
    缺件等状态由上层证据检查器提供；本函数绝不从空检索自动推断无要求。
    """
    require(type(requirement_inventory_complete) is bool, "PACKAGE_INVENTORY_FLAG_INVALID")
    require(
        len({r.requirement_id for r in requirements}) == len(requirements),
        "PACKAGE_REQUIREMENT_DUPLICATE",
    )
    require(len({r.requirement_id for r in results}) == len(results), "PACKAGE_COVERAGE_DUPLICATE")
    required = {r.requirement_id: r for r in requirements}
    package_identity = package.manifest_digest
    requirement_identities = {r.requirement_id: r.manifest_digest for r in requirements}
    require(all(r.requirement_id in required for r in results), "PACKAGE_REQUIREMENT_UNKNOWN")
    parts = {part.part_id: (member, part) for member in package.members for part in member.parts}
    statuses: dict[str, str] = {}
    inspected_output: list[dict[str, Any]] = []
    for requirement in requirements:
        require(requirement.scope == package.scope, "PACKAGE_REQUIREMENT_SCOPE_MISMATCH")
        require(
            all(part_id in parts for part_id in requirement.target_part_ids),
            "PACKAGE_TARGET_PART_UNKNOWN",
        )
        require(
            all(
                parts[part_id][1].category in requirement.categories
                for part_id in requirement.target_part_ids
            ),
            "PACKAGE_TARGET_CATEGORY_MISMATCH",
        )
        statuses[requirement.requirement_id] = CoverageState.UNKNOWN.value
    for result in results:
        require(result.package_digest == package_identity, "PACKAGE_COVERAGE_STALE")
        requirement = required[result.requirement_id]
        require(
            result.requirement_digest == requirement_identities[requirement.requirement_id],
            "PACKAGE_COVERAGE_REQUIREMENT_STALE",
        )
        targets = set(requirement.target_part_ids) or {
            part_id
            for part_id, (_, part) in parts.items()
            if part.category in requirement.categories
        }
        covered: dict[str, list[tuple[int, int]]] = {}
        for inspected in result.inspected:
            require(inspected.part_id in targets, "PACKAGE_INSPECTED_TARGET_MISMATCH")
            member, part = parts[inspected.part_id]
            require(
                part.first_page <= inspected.first_page <= inspected.last_page <= part.last_page,
                "PACKAGE_INSPECTED_OUT_OF_BOUNDS",
            )
            if result.state == CoverageState.VERIFIED:
                require(member.parse.status == "frozen", "PACKAGE_PARSE_NOT_FROZEN")
            covered.setdefault(inspected.part_id, []).append(
                (inspected.first_page, inspected.last_page)
            )
            inspected_output.append(
                {
                    "requirement_id": result.requirement_id,
                    "requirement_digest": result.requirement_digest,
                    "document_version_id": member.document_version_id,
                    **asdict(inspected),
                }
            )
        if result.state == CoverageState.NOT_APPLICABLE:
            require(
                requirement.applicability == "not_applicable"
                and bool(requirement.applicability_evidence),
                "PACKAGE_NOT_APPLICABLE_UNPROVEN",
            )
        if result.state == CoverageState.VERIFIED:
            require(requirement.applicability == "applicable", "PACKAGE_APPLICABILITY_UNRESOLVED")
            require(bool(targets), "PACKAGE_VERIFIED_TARGET_EMPTY")
            require(
                all(_covers(parts[t][1], covered.get(t, [])) for t in targets),
                "PACKAGE_VERIFIED_SCOPE_INCOMPLETE",
            )
            if requirement.minimum_count is not None:
                # 数量只由核验器给结论；不能用物理文件数推断材料项数。
                require("quantity" in requirement.checks, "PACKAGE_QUANTITY_CHECK_UNDECLARED")
        statuses[result.requirement_id] = result.state.value
    complete = (
        requirement_inventory_complete
        and bool(requirements)
        and package.formal_eligible
        and all(
            state
            in {
                CoverageState.VERIFIED.value,
                CoverageState.NOT_APPLICABLE.value,
            }
            for state in statuses.values()
        )
    )
    return {
        "package_digest": package_identity,
        "complete": complete,
        "requirement_inventory_complete": requirement_inventory_complete,
        "requirement_states": statuses,
        "requirement_digests": requirement_identities,
        "inspected_ranges": inspected_output,
        "member_gaps": _member_gaps(package),
    }


def _parse_binding(member: PackageMember) -> tuple[Any, ...]:
    return (
        member.document_version_id,
        member.file_digest,
        member.page_count,
        member.parse.parser_digest,
        member.parse.config_digest,
        member.parse.evidence_digest,
    )


def _member_gaps(package: PackageRevision) -> list[dict[str, Any]]:
    gaps = []
    for member in package.members:
        codes = []
        if member.page_count is None:
            codes.append("page_count_unknown")
        if not member.parts:
            codes.append("parts_unassigned")
        if member.parse.status != "frozen":
            codes.append("parse_identity_not_frozen")
        if codes:
            gaps.append(
                {
                    "member_id": member.member_id,
                    "document_version_id": member.document_version_id,
                    "purposes": list(member.purposes),
                    "codes": codes,
                    "reason": member.parse.reason,
                }
            )
    return gaps


def _covers(part: DocumentPart, ranges: list[tuple[int, int]]) -> bool:
    next_page = part.first_page
    for first, last in sorted(ranges):
        if first > next_page:
            return False
        next_page = max(next_page, last + 1)
    return next_page > part.last_page
