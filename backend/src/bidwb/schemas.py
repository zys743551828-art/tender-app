"""对外数据结构（请求与响应）。

与 ``contracts/domain.schema.json`` 逐字段对应；``tests/test_contract_conformance.py`` 比对两者的字段集合与必填性，
任何一边改动而另一边没跟上都会让测试失败。请求模型一律 ``extra="forbid"``：多余字段（例如客户端试图自报操作者或成绩）
直接 422，而不是被静默忽略。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

ID_PATTERN = r"^[a-z][a-z0-9_-]{2,80}$"
Id = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonEmpty = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


def _decimal_string(value: str) -> str:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        msg = "必须是十进制数字字符串"
        raise ValueError(msg) from exc
    if not parsed.is_finite():
        msg = "不允许 NaN 或无穷"
        raise ValueError(msg)
    return value


DecimalStr = Annotated[str, AfterValidator(_decimal_string)]

FileRole = Literal["tender", "supplement", "drawing", "boq", "body", "submission", "official_result", "other"]
TaskKind = Literal["parse", "rules", "diagnosis", "revision", "recheck", "prediction", "experiment", "export"]
ProjectState = Literal[
    "materials_pending",
    "ready_to_analyze",
    "analyzing",
    "analysis_failed",
    "issues_open",
    "ready_to_submit",
    "submitted",
    "archived",
    "cancelled",
    "failed_tender",
]
TaskState = Literal["queued", "running", "waiting_input", "succeeded", "failed", "cancel_requested", "cancelled"]
Purpose = Literal["research", "shadow", "business"]
FindingStatus = Literal["candidate", "confirmed", "rejected", "deferred", "revision_pending", "recheck_pending", "resolved"]
Decision = Literal["confirm", "reject", "defer", "resolve", "request_facts", "reopen"]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


# ------------------------------------------------------------------ 通用
class ErrorBody(Response):
    code: NonEmpty
    message: NonEmpty
    request_id: str
    retryable: bool
    details: dict[str, Any]


class ArtifactRef(Response):
    artifact_id: Id
    sha256: Sha256
    media_type: NonEmpty
    byte_size: Annotated[int, Field(ge=0)]
    contract_version: NonEmpty


# ------------------------------------------------------------------ 身份与项目
class Me(Response):
    member_id: Id
    display_name: NonEmpty
    csrf_token: NonEmpty


class LoginRequest(Request):
    username: NonEmpty
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class ProjectSettings(Request):
    """项目级功能开关：用户可以只用自己需要的部分。默认全部开启，只有“规则按原文接受”默认关闭。

    废标／否决检测与证据溯源是核心，不提供开关。
    """

    auto_start: bool = True  # 资料齐了自动开始评审；关闭后解析照常进行，评审等人点“开始评审”
    accept_rules_as_written: bool = False  # 未人工确认的废标／否决／强制类规则按原文接受，不再阻止登记提交
    consistency_check: bool = True  # 前后矛盾检测
    scope_check: bool = True  # 范围残留检测
    show_score: bool = True  # 报告显示预测分数与区间；关闭后只显示失分点
    price: bool = True  # 报价模块（报价由其他部门负责时关闭）
    outcome_tracking: bool = True  # 提交后提示登记开标结果


class ProjectFields(Request):
    """只有项目名称必填；招标编号、标段、地区、工程类别、截止时间可以以后补。"""

    title: NonEmpty
    tender_number: str | None = None
    lot: str | None = None
    round: Annotated[int, Field(ge=1)] = 1
    region: str | None = None
    engineering_type: str | None = None
    deadline: datetime | None = None


class ProjectCreate(ProjectFields):
    settings: ProjectSettings = Field(default_factory=ProjectSettings)


class ProjectUpdate(Request):
    title: NonEmpty | None = None
    tender_number: str | None = None
    lot: str | None = None
    round: Annotated[int, Field(ge=1)] | None = None
    region: str | None = None
    engineering_type: str | None = None
    deadline: datetime | None = None
    settings: ProjectSettings | None = None  # 整体替换


class Project(Response):
    project_id: Id
    title: str
    tender_number: str | None
    lot: str | None
    round: int
    region: str | None
    engineering_type: str | None
    deadline: datetime | None
    state: ProjectState
    revision: int
    owner_id: Id
    created_at: datetime
    settings: ProjectSettings


# ------------------------------------------------------------------ 资料上传
class UploadRequest(Request):
    original_name: NonEmpty
    role: FileRole
    byte_size: Annotated[int, Field(ge=1, le=104857600)]
    sha256: Sha256
    media_type: NonEmpty
    version_of_file_id: Id | None = None
    source_word_version_id: Id | None = None


class PartUrl(Response):
    part_number: Annotated[int, Field(ge=1)]
    url: str
    expires_at: datetime


class UploadSession(Response):
    upload_id: Id
    part_bytes: int
    part_count: Annotated[int, Field(ge=1, le=13)]
    parts: list[PartUrl]
    expires_at: datetime


class CompletedPart(Request):
    part_number: Annotated[int, Field(ge=1, le=13)]
    etag: NonEmpty


class UploadComplete(Request):
    sha256: Sha256
    parts: Annotated[list[CompletedPart], Field(min_length=1, max_length=13)]


class WordPdfCandidate(Response):
    link_id: Id
    pdf_version_id: Id
    method: Literal["controlled_render", "user_declared"]
    gaps: list[str]


class WordStatus(Response):
    current: bool
    state: Literal["waiting", "converted", "needs_review", "failed"]
    error_code: str | None
    adopted_pdf_version_id: Id | None
    candidates: list[WordPdfCandidate]


class WordAdoptRequest(Request):
    link_id: Id
    reason: NonEmpty
    reviewed_pdf: bool


class WordRetryRequest(Request):
    pass


class FileVersion(Response):
    version_id: Id
    project_id: Id
    file_id: Id
    version_number: Annotated[int, Field(ge=1)]
    original_name: str
    role: FileRole
    artifact: ArtifactRef
    obtained_at: datetime
    document_date: str | None
    association_status: Literal["pending", "confirmed", "conflict"]
    supersedes: Id | None
    word: WordStatus | None = None
    source_word_version_id: Id | None = None


class UploadResult(FileVersion):
    duplicate: bool
    new_file: bool


# ------------------------------------------------------------------ 输入快照
class SnapshotRequest(Request):
    body_version_id: Id
    rule_set_id: Id
    fact_set_id: Id | None
    file_version_ids: Annotated[list[Id], Field(min_length=1)]
    reference_dataset_id: Id | None


class InputSnapshot(Response):
    snapshot_id: Id
    project_id: Id
    contract_version: Literal["input-v1"]
    file_version_ids: list[Id]
    body_version_id: Id
    rule_set_id: Id
    fact_set_id: Id | None
    as_of: datetime
    reference_dataset_id: Id | None
    coverage_gaps: list[str]
    sha256: Sha256
    word_sources: list[dict[str, Any]] = Field(default_factory=list)


# ------------------------------------------------------------------ 任务
class TaskRequest(Request):
    snapshot_id: Id
    kind: TaskKind
    purpose: Purpose
    bundle_id: Id


class DiagnosisRequest(Request):
    snapshot_id: Id


class TaskCoverage(Response):
    """诊断覆盖度：只有 complete 才允许项目进入“可登记提交”；partial / empty 的结论不完整，需要重新诊断。"""

    status: Literal["complete", "partial", "empty"]
    rules_total: int
    rules_checked: int
    rules_failed: int
    candidates_dropped: int


class Task(Response):
    task_id: Id
    project_id: Id
    snapshot_id: Id | None  # 解析与规则提取任务没有快照；契约扩展，见 CHANGES
    bundle_id: Id | None  # 诊断、改稿、复检使用内置方法，没有方法包；契约扩展
    kind: TaskKind
    purpose: Purpose
    state: TaskState
    stage: str
    attempt: int
    input_sha256: Sha256
    output_artifact: ArtifactRef | None
    error_code: str | None
    created_at: datetime
    message: str | None = None  # 面向人的中文说明：失败原因，或诊断覆盖不完整的提示；契约扩展
    coverage: TaskCoverage | None = None  # 诊断任务的覆盖度；契约扩展


class TaskEvent(Response):
    task_id: Id
    attempt: int
    kind: str
    state: TaskState
    stage: str
    at: datetime
    message: str | None = None  # 契约扩展
    coverage: TaskCoverage | None = None  # 契约扩展


# ------------------------------------------------------------------ 证据与检索
class EvidenceRef(Response):
    evidence_id: Id
    project_id: Id
    version_id: Id
    file_role: FileRole  # 证据出自哪类资料：招标文件、补遗、施组正文……界面据此把招标要求与正文写法并排对照
    file_name: str
    source_sha256: Sha256
    physical_page: Annotated[int, Field(ge=1)]
    printed_page: str | None
    quote: str
    kind: Literal["text", "table", "visual_observation"]
    parser_version: str
    bbox: list[float] | None
    semantic_review: Literal["pending", "supported", "unsupported"]
    effectivity_notes: list[str] = Field(default_factory=list)


class SearchRequest(Request):
    snapshot_id: Id | None = None  # 不给＝检索项目当前资料；给了＝限定在该轮诊断固定下来的文件版本内
    query: Annotated[str, StringConstraints(min_length=1, max_length=500, strip_whitespace=True)]
    top_k: Annotated[int, Field(ge=1, le=50)]
    mode: Literal["hybrid", "keyword"]


class SearchHit(Response):
    evidence: EvidenceRef
    score: float
    channel: Literal["dense", "sparse", "fused", "keyword"]


class SearchResult(Response):
    snapshot_id: Id | None  # 检索项目当前资料时为 null
    mode_used: Literal["hybrid", "keyword"]
    index_state: Literal["ready", "building", "unavailable"]
    hits: list[SearchHit]
    gaps: list[str]


# ------------------------------------------------------------------ 规则、问题与审核
class ConfirmRulesRequest(Request):
    """一次确认多条还没有人看过的规则（按原文接受）。已有决定的规则不受影响。"""

    object_version: NonEmpty
    rule_ids: Annotated[list[Id], Field(min_length=1, max_length=200)]


class ConfirmRulesResult(Response):
    confirmed: Annotated[int, Field(ge=0)]
    skipped: Annotated[int, Field(ge=0)]  # 已有人工决定的规则


class ReviewRequest(Request):
    """审核请求。确认可以不写理由；驳回、暂缓、重新打开等偏离或改变结论的决定必须写明理由。"""

    object_version: NonEmpty
    decision: Decision
    reason: str = ""

    @model_validator(mode="after")
    def _reason_required_unless_confirm(self) -> ReviewRequest:
        if self.decision != "confirm" and not self.reason.strip():
            raise ValueError("驳回、暂缓等决定必须填写理由")
        return self


class Review(Response):
    review_id: Id
    project_id: Id
    object_id: Id
    object_version: str
    decision: Decision
    reason: str
    actor_id: Id
    reviewed_at: datetime


RuleKind = Literal["mandatory", "scoring", "disqualification", "recommendation", "exception"]


class Rule(Response):
    rule_id: Id
    kind: RuleKind
    statement: NonEmpty
    conditions: list[str]
    exceptions: list[str]
    evidence: Annotated[list[EvidenceRef], Field(min_length=1)]
    confirmation: Literal["pending", "confirmed", "rejected"]
    carried_from_rule_id: Id | None
    max_points: str | None
    source_status: Literal["active", "superseded", "needs_confirmation"] = "active"


class FullScoreTerm(Response):
    """评标办法写明的技术标满分。"""

    value: str
    quote: str
    evidence: list[EvidenceRef]


class PriceRuleTerm(Response):
    """评标办法写明的评标价得分规则；没写的项为空。数值都出自 ``quote`` 原文。"""

    full_score: str | None = None
    above_deduct_per_pct: str | None = None
    below_deduct_per_pct: str | None = None
    method: Literal["fixed", "average", "trimmed_average"] | None = None
    coefficient: str | None = None
    trim_pct: str | None = None
    max_limit: str | None = None
    abnormal_low_pct: str | None = None
    quote: str
    evidence: list[EvidenceRef]


class TermAlternative(Response):
    option_id: Id
    values: dict[str, str]
    quote: str
    evidence: list[EvidenceRef]


class TermConflict(Response):
    term: Literal["technical_full_score", "price_rule"]
    alternatives: list[TermAlternative]


class ResolveTermRequest(Request):
    object_version: NonEmpty
    term: Literal["technical_full_score", "price_rule"]
    option_id: Id
    reason: NonEmpty


class BidTerms(Response):
    """从评标办法提取的投标条件，带原文出处；没有提取到的项为空。"""

    technical_full_score: FullScoreTerm | None
    price_rule: PriceRuleTerm | None
    conflicts: list[TermConflict] = Field(default_factory=list)


class EffectivityQuote(Request):
    evidence_id: Id
    quote: Annotated[str, StringConstraints(min_length=1, max_length=2000, strip_whitespace=True)]


EffectivityAction = Literal["whole_replace", "partial_replace", "defer", "retain"]


class EffectivityPreviewRequest(Request):
    object_version: NonEmpty
    old_version_id: Id
    new_version_id: Id
    action: EffectivityAction
    rule_ids: Annotated[list[Id], Field(max_length=200)] = Field(default_factory=list)


class EffectivityRequest(EffectivityPreviewRequest):
    scope_basis: Annotated[list[EffectivityQuote], Field(max_length=5)] = Field(default_factory=list)
    reason: NonEmpty


class AffectedSection(Response):
    title: str
    evidence: list[EvidenceRef]


class EffectivityPreview(Response):
    rule_set_id: Id
    revision: int
    affected_rule_ids: list[Id]
    mixed_source_rule_ids: list[Id]
    related_sections: list[AffectedSection]
    gaps: list[str]


class EffectivityDecision(Response):
    decision_id: Id
    old_version_id: Id
    new_version_id: Id
    action: EffectivityAction
    reason: str
    scope_basis: list[EffectivityQuote]
    ended_rule_ids: list[Id]
    pending_rule_ids: list[Id]


class RuleSet(Response):
    rule_set_id: Id
    project_id: Id
    source_version_ids: list[Id]
    status: Literal["candidate", "conflict", "confirmed"]
    revision: Annotated[int, Field(ge=1)]
    rules: list[Rule]
    terms: BidTerms
    effectivity_decisions: list[EffectivityDecision] = Field(default_factory=list)


class FactRequest(Request):
    name: NonEmpty
    subject: NonEmpty
    scope: NonEmpty
    value_decimal: DecimalStr | None
    unit: str | None
    statement: NonEmpty
    evidence_ids: Annotated[list[Id], Field(min_length=1)]


class FactWithdrawRequest(Request):
    reason: NonEmpty


class FactSetResult(Response):
    fact_set_id: Id
    fact_id: Id
    item_count: int


class Fact(Response):
    fact_id: Id
    name: str
    subject: str
    scope: str
    value_decimal: str | None
    unit: str | None
    statement: str
    confirmation: Literal["pending", "confirmed", "rejected"]
    evidence_ids: list[Id]


class FactList(Response):
    """项目当前（最新）事实集；还没有录入过事实时 fact_set_id 为 null、items 为空。"""

    fact_set_id: Id | None
    items: list[Fact]


FindingCategory = Literal["disqualification", "response", "consistency", "scope", "improvement"]
FindingSource = Literal["rule", "consistency", "scope"]
RuleBasis = Literal["confirmed", "unconfirmed"]


class Finding(Response):
    finding_id: Id
    project_id: Id
    snapshot_id: Id
    run_id: Id
    rule_id: Id | None  # 来自规则核对的问题带规则；一致性与范围检测的问题没有规则
    source: FindingSource
    category: FindingCategory
    rule_basis: RuleBasis | None  # 判断时所依据的规则是否已由人工确认；非规则来源为 null
    nature: Literal["fact_conflict", "needs_confirmation", "suggestion"]
    impact: Literal["qualification", "technical", "delivery"]
    severity: Literal["critical", "normal", "improvement"]
    statement: str
    evidence: list[EvidenceRef]
    required_facts: list[str]
    status: FindingStatus
    revision: Annotated[int, Field(ge=1)]  # 审核时作为 object_version 回传（乐观锁）；契约扩展，见 CHANGES
    official_score_effect: None = None


# ------------------------------------------------------------------ 改稿建议
class RevisionRequest(Request):
    base_version_id: Id
    snapshot_id: Id
    finding_ids: Annotated[list[Id], Field(min_length=1, max_length=20)]
    allowed_fact_ids: Annotated[list[Id], Field(max_length=50)]
    scope: NonEmpty


class AdoptRequest(Request):
    base_version_id: Id
    edited_diff_artifact_id: Id | None  # 暂不支持人工编辑后的差异；必须为 null


class RejectRevisionRequest(Request):
    base_version_id: Id
    reason: NonEmpty


class Revision(Response):
    revision_id: Id
    project_id: Id
    base_version_id: Id
    finding_ids: list[Id]
    allowed_fact_ids: list[Id]
    status: Literal["proposed", "adopted", "rejected", "stale"]  # 契约另有 recheck_pending/reviewed，随复检功能实现
    diff_artifact: ArtifactRef
    target_version_id: Id | None = None
    review_ids: list[Id]


class DiffEdit(Response):
    evidence_id: Id
    original: str
    replacement: str
    finding_id: Id
    facts_used: list[str]
    note: str


class DiffDropped(Response):
    """被丢弃的候选及原因（reason 为机器码，如 invented_number、original_not_verbatim）。"""

    model_config = ConfigDict(extra="allow", from_attributes=True)
    reason: str
    finding_id: str | None = None


class RevisionDiff(Response):
    model_config = ConfigDict(extra="allow", from_attributes=True)
    prompt_version: str
    model: str
    base_version_id: Id
    edits: list[DiffEdit]
    dropped: list[DiffDropped]


# ------------------------------------------------------------------ 提交与结果
class SubmissionRequest(Request):
    body_version_id: Id
    snapshot_id: Id
    submitted_at: datetime
    receipt_artifact_id: Id | None


class Submission(Response):
    submission_id: Id
    project_id: Id
    body_version_id: Id
    snapshot_id: Id
    submitted_at: datetime
    confirmation_review_id: Id
    receipt_artifact: ArtifactRef | None
    supersedes: Id | None


StageResult = Literal[
    "pending", "technical_shortlisted", "not_shortlisted", "rejected", "candidate", "awarded", "not_awarded", "cancelled", "failed_tender"
]
OutcomeTarget = Literal["technical_total", "composite_total", "no_score"]
_NONNEG_DECIMAL = r"^(0|[1-9][0-9]*)(\.[0-9]+)?$"
NonNegativeDecimal = Annotated[str, StringConstraints(pattern=_NONNEG_DECIMAL, max_length=24)]


class OutcomeRequest(Request):
    submission_id: Id
    source_kind: Literal["user_reported", "official"]
    target: OutcomeTarget
    value: NonNegativeDecimal | None
    maximum: NonNegativeDecimal | None
    aggregation: str | None
    stage_result: StageResult
    source_page: Annotated[int, Field(ge=1)] | None
    published_at: datetime | None
    supersedes: Id | None
    source_artifact_id: Id | None
    source_description: NonEmpty


class OutcomeVerifyRequest(Request):
    source_artifact_id: Id
    source_page: Annotated[int, Field(ge=1)]
    aggregation: NonEmpty
    reason: NonEmpty


class Outcome(Response):
    outcome_id: Id
    project_id: Id
    submission_id: Id
    source_kind: Literal["user_reported", "official"]
    verification_status: Literal["pending", "verified", "conflict"]
    target: OutcomeTarget
    value: str | None
    maximum: str | None
    aggregation: str | None
    stage_result: StageResult
    source_artifact: ArtifactRef | None
    source_page: int | None
    published_at: datetime | None
    known_at: datetime
    verified_by: Id | None
    supersedes: Id | None


# ------------------------------------------------------------------ 响应矩阵（废标／否决／强制与评分条款逐条核对）
Verdict = Literal["satisfied", "violated", "unclear", "failed"]


class RuleVerdict(Response):
    rule_id: Id
    kind: RuleKind
    statement: str
    rule_basis: RuleBasis
    verdict: Verdict
    note: str
    evidence: list[EvidenceRef]  # 支持该判定的正文依据；判定为“满足”时至少一条
    finding_ids: list[Id]


class VerdictCounts(Response):
    total: int
    satisfied: int
    violated: int
    unclear: int
    failed: int


class Compliance(Response):
    """一次评审里每条规则的判定。``qualification`` 统计废标／否决与强制类规则，``scoring`` 统计评分条款。"""

    snapshot_id: Id
    run_id: Id | None
    coverage: TaskCoverage | None
    qualification: VerdictCounts
    scoring: VerdictCounts
    rows: list[RuleVerdict]


# ------------------------------------------------------------------ 评分预测
ValidationStatus = Literal["not_validated", "validated_in_scope", "out_of_scope"]


class PredictionTopic(Response):
    topic: str  # 评分条款及其满分
    points_lost: str  # 估计失分
    assessment: str
    evidence: list[EvidenceRef]
    limitations: str


class Calibration(Response):
    """预测与官方成绩的对照。样本不足时不给误差：``state`` 为 insufficient，``mae``、``bias`` 为 null。"""

    state: Literal["uncalibrated", "insufficient", "calibrated"]
    pairs: int
    needed_pairs: int
    mae: str | None
    bias: str | None


class ScoringModelRef(Response):
    """校准所用的打分模型：用多少组官方成绩训练与评估、误差多大、适用于哪些项目。"""

    model_id: str
    pairs: int
    mae: str  # 评估的平均绝对误差（满分百分制）
    scope: str


class Prediction(Response):
    prediction_id: Id
    project_id: Id
    snapshot_id: Id
    run_id: Id
    target: Literal["technical_total"]
    status: Literal["candidate", "abstained", "failed"]
    purpose: Purpose
    estimated_value: str | None
    low: str | None
    high: str | None
    # 未校准时为参与估计的评分条款分值合计（与 technical_full_score 对照即覆盖程度）；校准后为技术标满分
    maximum: str | None
    technical_full_score: str | None  # 评标办法写明的技术标满分
    # validated_in_scope：业务环境的打分模型适用，分数与区间（约 80% 把握）已校准；
    # not_validated：没有生效的打分模型；out_of_scope：有模型但本项目不在其适用范围。后两者给出未校准的逐项评估合计
    validation_status: ValidationStatus
    reason: str
    scoring_model: ScoringModelRef | None  # 仅 validated_in_scope 时给出
    topics: list[PredictionTopic]
    created_at: datetime
    calibration: Calibration  # 系统内置的在线对照（预测与登记的官方成绩），作为监控信息


# ------------------------------------------------------------------ 报价
BenchmarkMethod = Literal["fixed", "average", "trimmed_average"]
_POSITIVE_DECIMAL = r"^(0\.[0-9]*[1-9][0-9]*|[1-9][0-9]*(\.[0-9]+)?)$"
# 十进制字符串至多 24 个字符：足够表达以元计的工程报价与分数，也让计算精度有确定的上界
PositiveDecimal = Annotated[str, StringConstraints(pattern=_POSITIVE_DECIMAL, max_length=24)]


class BenchmarkSpec(Request):
    """评标基准价的取法：固定值，或竞争对手（可含己方）报价的平均值／去极值平均值乘以系数。"""

    method: BenchmarkMethod
    fixed_value: PositiveDecimal | None = None
    coefficient: PositiveDecimal = "1"
    trim_pct: NonNegativeDecimal = "0"
    include_own: bool = False

    @model_validator(mode="after")
    def _fixed_needs_value(self) -> BenchmarkSpec:
        if self.method == "fixed" and self.fixed_value is None:
            raise ValueError("固定基准价必须给出 fixed_value")
        return self


class PriceParams(Request):
    """评标价得分规则：高于基准价每 1% 扣 ``above_deduct_per_pct`` 分，低于每 1% 扣 ``below_deduct_per_pct`` 分，满分 ``full_score``。"""

    full_score: PositiveDecimal
    above_deduct_per_pct: NonNegativeDecimal
    below_deduct_per_pct: NonNegativeDecimal
    max_limit: PositiveDecimal | None = None  # 最高投标限价，超过即否决
    abnormal_low_pct: NonNegativeDecimal | None = None  # 低于基准价该百分比视为异常低价风险
    benchmark: BenchmarkSpec


class PricePlanRequest(Request):
    params: PriceParams
    competitor_prices: Annotated[list[PositiveDecimal], Field(max_length=200)]
    candidate_prices: Annotated[list[PositiveDecimal], Field(max_length=20)]
    note: Annotated[str, StringConstraints(max_length=500, strip_whitespace=True)] = ""


class PricePlan(Response):
    plan_id: Id
    project_id: Id
    params: PriceParams
    competitor_prices: list[str]
    candidate_prices: list[str]
    note: str
    supersedes: Id | None
    created_by: Id
    created_at: datetime


class PricePoint(Response):
    price: str
    deviation_pct: str
    score: str
    flags: list[Literal["over_max_limit", "abnormal_low"]]


class ExchangeRate(Response):
    """技术分与报价的换算：高于基准价 1% 失去 ``points_per_pct_above`` 分，即 1 个技术分约相当于 ``pct_per_point_above`` % 的报价。"""

    points_per_pct_above: str
    pct_per_point_above: str | None


class PriceSimulation(Response):
    benchmark: str | None
    exchange_rate: ExchangeRate
    candidates: list[PricePoint]
    curve: list[PricePoint]
    best: PricePoint | None
    notes: list[str]


class PricePlanWithSimulation(Response):
    plan: PricePlan
    simulation: PriceSimulation


# ------------------------------------------------------------------ 流水线、报告与度量
PipelineStepKey = Literal["materials", "rules", "review", "prediction"]
PipelineStepState = Literal["waiting", "running", "done", "failed"]


class PipelineStep(Response):
    key: PipelineStepKey
    state: PipelineStepState
    task_id: Id | None
    message: str | None


class PipelineStatus(Response):
    project_id: Id
    stage: Literal["waiting_materials", "waiting_start", "running", "done", "failed"]
    steps: list[PipelineStep]
    missing: list[Literal["tender", "body"]]
    snapshot_id: Id | None  # 最近一次已完成评审的输入快照
    round_no: int | None
    stale_reasons: list[Literal["body_updated", "tender_updated", "rules_changed", "facts_changed"]]
    rules_total: int
    rules_unconfirmed: int
    input_verification_required: bool = False
    word_pdf_required: bool = False


class PredictionBrief(Response):
    status: Literal["candidate", "abstained", "failed"]
    estimated_value: str | None
    low: str | None
    high: str | None
    maximum: str | None
    technical_full_score: str | None
    validation_status: ValidationStatus
    reason: str


class ProjectSummary(Response):
    """项目总览上的一行摘要，与报告同源：下一步就是报告“下一步”的第一条。"""

    reviewed: bool  # 是否已有完成的评审
    qualification_open: int  # 未处理的废标／否决与强制性要求问题
    prediction: PredictionBrief | None
    next_action: NextAction | None


class ProjectOverview(Project):
    summary: ProjectSummary


class CategoryCount(Response):
    category: FindingCategory
    total: int
    open: int
    resolved: int


class NextAction(Response):
    key: Literal[
        "upload_materials",
        "start_analysis",
        "wait_analysis",
        "retry_analysis",
        "handle_disqualification",
        "review_unclear",
        "handle_findings",
        "reanalyze",
        "confirm_rules",
        "verify_sources",
        "set_price",
        "submit",
        "record_outcome",
    ]
    title: str
    detail: str
    target: Literal["materials", "report", "findings", "rules", "price", "submit", "outcomes"]
    count: int | None


class ReportBasis(Response):
    rules_total: int
    rules_confirmed: int
    rules_unconfirmed: int
    coverage: TaskCoverage | None
    generated_from_snapshot_at: datetime


class PriceSummary(Response):
    plan_id: Id
    exchange_rate: ExchangeRate
    best: PricePoint | None
    candidates: list[PricePoint]
    created_at: datetime


class Report(Response):
    project_id: Id
    snapshot_id: Id
    round_no: int
    basis: ReportBasis
    qualification: Compliance
    categories: list[CategoryCount]
    prediction: Prediction | None
    price: PriceSummary | None
    next_actions: list[NextAction]
    pipeline: PipelineStatus


class OutcomeMetrics(Response):
    submissions: int
    decided: int
    shortlisted: int
    not_shortlisted: int
    rejected: int
    awarded: int
    not_awarded: int
    shortlist_rate: str | None
    award_rate: str | None


class QualificationMetrics(Response):
    """废标／否决风险的闭环：评审发现了多少、提交前处理了多少、提交时仍未处理多少，以及招标方实际否决了多少。"""

    identified: int
    resolved_or_dismissed: int
    open_at_submission: int
    rejected_by_buyer: int


class RoundPoint(Response):
    round_no: int
    snapshot_id: Id
    estimated_value: str | None
    open_findings: int
    resolved_findings: int
    open_qualification: int


class RoundTrend(Response):
    project_id: Id
    title: str
    maximum: str | None
    actual_value: str | None
    rounds: list[RoundPoint]


class Metrics(Response):
    outcomes: OutcomeMetrics
    qualification: QualificationMetrics
    calibration: Calibration
    trends: list[RoundTrend]
