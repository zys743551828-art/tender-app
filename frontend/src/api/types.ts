/**
 * 与 contracts/domain.schema.json 及 openapi.json 对应的手写类型。
 * 字段名、枚举以契约为准；每个类型上的注释标明对应的 `$defs` 名称。
 * 与契约不一致或契约未规定之处（Project 响应、列表信封等）在注释中标 [差异] 并写入 README。
 */

export type Id = string;
export type IsoDateTime = string;
/** 十进制字符串（契约要求 ^(0|[1-9][0-9]*)(\.[0-9]+)?$），前端不用 number 表示分值。 */
export type DecimalString = string;

/** $defs/ArtifactRef */
export interface ArtifactRef {
  artifact_id: Id;
  sha256: string;
  media_type: string;
  byte_size: number;
  contract_version: string;
}

/** $defs/Error */
export interface ErrorBody {
  code: string;
  message: string;
  request_id: string;
  retryable: boolean;
  details: Record<string, unknown>;
}

/** $defs/Me */
export interface Me {
  member_id: Id;
  display_name: string;
  csrf_token: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export const FILE_ROLES = [
  'tender',
  'supplement',
  'drawing',
  'boq',
  'body',
  'submission',
  'official_result',
  'other',
] as const;
export type FileRole = (typeof FILE_ROLES)[number];

/** schema.sql projects.state 的 CHECK 枚举。 */
export const PROJECT_STATES = [
  'materials_pending',
  'ready_to_analyze',
  'analyzing',
  'analysis_failed',
  'issues_open',
  'ready_to_submit',
  'submitted',
  'archived',
  'cancelled',
  'failed_tender',
] as const;
export type ProjectState = (typeof PROJECT_STATES)[number];

/**
 * 项目（后端 schemas.py 的 Project 响应模型；domain.schema.json 只定义了创建与更新请求）。
 * state 用 string：遇到不认识的状态按“未知状态”显示，不崩溃。
 */
export interface Project {
  project_id: Id;
  title: string;
  tender_number: string | null;
  lot: string | null;
  round: number;
  region: string | null;
  engineering_type: string | null;
  deadline: IsoDateTime | null;
  state: string;
  revision: number;
  owner_id: Id;
  created_at: IsoDateTime;
  settings: ProjectSettings;
}

/** $defs/PredictionBrief：项目总览用的预测摘要。 */
export interface PredictionBrief {
  status: 'candidate' | 'abstained' | 'failed';
  estimated_value: DecimalString | null;
  low: DecimalString | null;
  high: DecimalString | null;
  maximum: DecimalString | null;
  technical_full_score: DecimalString | null;
  validation_status: ValidationStatus;
  reason: string;
}

/** $defs/ProjectSummary：与报告同源，next_action 就是报告“下一步”的第一条。 */
export interface ProjectSummary {
  reviewed: boolean;
  qualification_open: number;
  prediction: PredictionBrief | null;
  next_action: NextAction | null;
}

/** $defs/ProjectOverview：GET /projects 的元素。 */
export interface ProjectOverview extends Project {
  summary: ProjectSummary;
}

/**
 * $defs/ProjectSettings：项目级功能开关。默认全部开启，只有“规则按原文接受”默认关闭。
 * 废标／否决检测与证据溯源是核心，没有开关。
 */
export interface ProjectSettings {
  /** 资料齐了自动开始评审；关闭后解析照常进行，评审等人点“开始评审”。 */
  auto_start: boolean;
  /** 未人工确认的废标／否决／强制类规则按原文接受，不再阻止登记提交。 */
  accept_rules_as_written: boolean;
  consistency_check: boolean;
  scope_check: boolean;
  /** 报告显示预测分数与区间；关闭后只显示失分点。 */
  show_score: boolean;
  /** 报价模块。 */
  price: boolean;
  /** 提交后提示登记开标结果。 */
  outcome_tracking: boolean;
}

export const DEFAULT_PROJECT_SETTINGS: ProjectSettings = {
  auto_start: true,
  accept_rules_as_written: false,
  consistency_check: true,
  scope_check: true,
  show_score: true,
  price: true,
  outcome_tracking: true,
};

/** $defs/ProjectCreate：只有项目名称必填。 */
export interface ProjectCreate {
  title: string;
  tender_number?: string | null;
  lot?: string | null;
  round?: number;
  region?: string | null;
  engineering_type?: string | null;
  deadline?: IsoDateTime | null;
  settings?: ProjectSettings;
}

/** $defs/ProjectUpdate（全部可选，settings 整体替换；更新需 If-Match: project.revision） */
export type ProjectUpdate = Partial<ProjectCreate>;

export interface WordStatus {
  current: boolean;
  state: 'waiting' | 'converted' | 'needs_review' | 'failed';
  error_code: string | null;
  adopted_pdf_version_id: Id | null;
  candidates: {
    link_id: Id;
    pdf_version_id: Id;
    method: 'controlled_render' | 'user_declared';
    gaps: string[];
  }[];
}

/** $defs/FileVersion */
export interface FileVersion {
  version_id: Id;
  project_id: Id;
  file_id: Id;
  /** 在所属文件里是第几版（从 1 起）。 */
  version_number: number;
  original_name: string;
  role: FileRole;
  artifact: ArtifactRef;
  obtained_at: IsoDateTime;
  document_date: string | null;
  association_status: 'pending' | 'confirmed' | 'conflict';
  supersedes: Id | null;
  word?: WordStatus | null;
  source_word_version_id?: Id | null;
}

/** $defs/UploadRequest */
export interface UploadRequest {
  original_name: string;
  role: FileRole;
  byte_size: number;
  sha256: string;
  media_type: string;
  /** 给出时，本次上传记为该已有文件的下一版（须同项目、同用途，否则 422 version_of_invalid）；省略／null 一律是新文件。 */
  version_of_file_id?: Id | null;
  source_word_version_id?: Id | null;
}

/** $defs/PartUrl */
export interface PartUrl {
  part_number: number;
  url: string;
  expires_at: IsoDateTime;
}

/** $defs/UploadSession（part_bytes 固定 8 MiB，最多 13 片） */
export interface UploadSession {
  upload_id: Id;
  part_bytes: number;
  part_count: number;
  parts: PartUrl[];
  expires_at: IsoDateTime;
}

/** $defs/UploadComplete 中 parts 的元素（后端 CompletedPart） */
export interface CompletedPart {
  part_number: number;
  etag: string;
}

/** $defs/UploadComplete */
export interface UploadComplete {
  sha256: string;
  parts: CompletedPart[];
}

/** $defs/EvidenceRef。bbox 为归一化 [x0,y0,x1,y1]，原点左上；null 表示无坐标，只显示整页。 */
export interface EvidenceRef {
  evidence_id: Id;
  project_id: Id;
  version_id: Id;
  /** 证据出自哪类资料；界面据此把招标要求与正文写法并排对照。 */
  file_role: FileRole;
  file_name: string;
  source_sha256: string;
  physical_page: number;
  printed_page: string | null;
  quote: string;
  kind: 'text' | 'table' | 'visual_observation';
  parser_version: string;
  bbox: number[] | null;
  semantic_review: 'pending' | 'supported' | 'unsupported';
  effectivity_notes?: string[];
}

/** $defs/InputSnapshot */
export interface InputSnapshot {
  snapshot_id: Id;
  project_id: Id;
  contract_version: 'input-v1';
  file_version_ids: Id[];
  body_version_id: Id;
  rule_set_id: Id;
  fact_set_id: Id | null;
  as_of: IsoDateTime;
  reference_dataset_id: Id | null;
  coverage_gaps: string[];
  sha256: string;
  word_sources?: Record<string, unknown>[];
}

/** $defs/SnapshotRequest */
export interface SnapshotRequest {
  body_version_id: Id;
  rule_set_id: Id;
  fact_set_id: Id | null;
  file_version_ids: Id[];
  reference_dataset_id: Id | null;
}

export type RuleKind =
  'mandatory' | 'scoring' | 'disqualification' | 'recommendation' | 'exception';
export type Confirmation = 'pending' | 'confirmed' | 'rejected';

/** $defs/RuleSet.rules 的元素 */
export interface Rule {
  rule_id: Id;
  kind: RuleKind;
  statement: string;
  conditions: string[];
  exceptions: string[];
  evidence: EvidenceRef[];
  confirmation: Confirmation;
  /** 重新提取时，与上一版规则集中相同规则的 rule_id；非 null 表示该规则的决定是沿用来的。 */
  carried_from_rule_id?: Id | null;
  /** 评分条款的满分值（十进制字符串）；没有分值或不是评分条款时为 null。 */
  max_points?: DecimalString | null;
  source_status?: 'active' | 'superseded' | 'needs_confirmation';
}

/** $defs/RuleSet（revision 作为规则审核的 object_version） */
export interface RuleSet {
  rule_set_id: Id;
  project_id: Id;
  source_version_ids: Id[];
  status: 'candidate' | 'conflict' | 'confirmed';
  revision: number;
  rules: Rule[];
  terms: BidTerms;
  effectivity_decisions?: EffectivityDecision[];
}

export type EffectivityAction = 'whole_replace' | 'partial_replace' | 'defer' | 'retain';
export interface EffectivityQuote {
  evidence_id: Id;
  quote: string;
}
export interface EffectivityPreviewRequest {
  object_version: string;
  old_version_id: Id;
  new_version_id: Id;
  action: EffectivityAction;
  rule_ids: Id[];
}
export interface EffectivityRequest extends EffectivityPreviewRequest {
  scope_basis: EffectivityQuote[];
  reason: string;
}
export interface EffectivityPreview {
  rule_set_id: Id;
  revision: number;
  affected_rule_ids: Id[];
  mixed_source_rule_ids: Id[];
  related_sections: { title: string; evidence: EvidenceRef[] }[];
  gaps: string[];
}
export interface EffectivityDecision {
  decision_id: Id;
  old_version_id: Id;
  new_version_id: Id;
  action: EffectivityAction;
  reason: string;
  scope_basis: EffectivityQuote[];
  ended_rule_ids: Id[];
  pending_rule_ids: Id[];
}

/** $defs/FullScoreTerm：评标办法写明的技术标满分。 */
export interface FullScoreTerm {
  value: DecimalString;
  quote: string;
  evidence: EvidenceRef[];
}

/** $defs/PriceRuleTerm：评标办法写明的评标价得分规则；没写的项为 null，数值都出自 quote 原文。 */
export interface PriceRuleTerm {
  full_score: DecimalString | null;
  above_deduct_per_pct: DecimalString | null;
  below_deduct_per_pct: DecimalString | null;
  method: BenchmarkMethod | null;
  coefficient: DecimalString | null;
  trim_pct: DecimalString | null;
  max_limit: DecimalString | null;
  abnormal_low_pct: DecimalString | null;
  quote: string;
  evidence: EvidenceRef[];
}

/** $defs/BidTerms */
export interface BidTerms {
  technical_full_score: FullScoreTerm | null;
  price_rule: PriceRuleTerm | null;
  conflicts?: TermConflict[];
}

export interface TermAlternative {
  option_id: Id;
  values: Record<string, string>;
  quote: string;
  evidence: EvidenceRef[];
}

export interface TermConflict {
  term: 'technical_full_score' | 'price_rule';
  alternatives: TermAlternative[];
}

export interface ResolveTermRequest {
  object_version: string;
  term: TermConflict['term'];
  option_id: Id;
  reason: string;
}

/** $defs/ConfirmRulesRequest：一次确认多条还没有人看过的规则。 */
export interface ConfirmRulesRequest {
  object_version: string;
  rule_ids: Id[];
  expected_context?: string | null;
}

export interface AssistantCard {
  kind: 'analysis' | 'confirm_rules';
  title: string;
  detail: string;
  expected_context: string;
  object_version: string | null;
  rule_ids: Id[];
  rule_statements: string[];
}

export interface AssistantReply {
  project_id: Id;
  project_title: string;
  lot: string | null;
  round: number;
  snapshot_id: Id | null;
  body_version_id: Id | null;
  answer: string;
  mode: 'model' | 'project_summary';
  materials: { version_id: string; filename: string }[];
  cards: AssistantCard[];
  links: ('materials' | 'basis' | 'findings' | 'submit' | 'outcomes')[];
}

/** $defs/ConfirmRulesResult */
export interface ConfirmRulesResult {
  confirmed: number;
  skipped: number;
}

export const FINDING_CATEGORIES = [
  'disqualification',
  'response',
  'consistency',
  'scope',
  'improvement',
] as const;
export type FindingCategory = (typeof FINDING_CATEGORIES)[number];
export type FindingSource = 'rule' | 'consistency' | 'scope';
/** 判断时所依据的规则是否已由人工确认。 */
export type RuleBasis = 'confirmed' | 'unconfirmed';

export type FindingNature = 'fact_conflict' | 'needs_confirmation' | 'suggestion';
export type FindingImpact = 'qualification' | 'technical' | 'delivery';
export type FindingSeverity = 'critical' | 'normal' | 'improvement';
export type FindingStatus =
  | 'candidate'
  | 'confirmed'
  | 'rejected'
  | 'deferred'
  | 'revision_pending'
  | 'recheck_pending'
  | 'resolved';

/**
 * $defs/Finding。official_score_effect 恒为 null：前端不显示任何官方扣分或分数影响。
 * revision 是对象版本，审核时作为 object_version 回传（乐观锁）。
 */
export interface Finding {
  finding_id: Id;
  project_id: Id;
  snapshot_id: Id;
  run_id: Id;
  /** 一致性与范围检测的问题没有规则。 */
  rule_id: Id | null;
  source: FindingSource;
  category: FindingCategory;
  /** 非规则来源为 null。 */
  rule_basis: RuleBasis | null;
  nature: FindingNature;
  impact: FindingImpact;
  severity: FindingSeverity;
  statement: string;
  evidence: EvidenceRef[];
  required_facts: string[];
  status: FindingStatus;
  official_score_effect: null;
  revision: number;
}

export type Decision = 'confirm' | 'reject' | 'defer' | 'resolve' | 'request_facts' | 'reopen';

/** $defs/ReviewRequest */
export interface ReviewRequest {
  object_version: string;
  decision: Decision;
  /** 确认可以不写；驳回、暂缓、重新打开等决定必须写明理由。 */
  reason?: string;
}

/** $defs/Review */
export interface Review {
  review_id: Id;
  project_id: Id;
  object_id: Id;
  object_version: string;
  decision: Decision;
  reason: string;
  actor_id: Id;
  reviewed_at: IsoDateTime;
}

/** $defs/SearchRequest（openapi 路径为 POST /projects/{id}/search） */
export interface SearchRequest {
  /** 不给＝检索项目当前资料；给了＝限定在该轮评审的输入所含的文件版本内。 */
  snapshot_id?: Id | null;
  query: string;
  top_k: number;
  mode: 'hybrid' | 'keyword';
}

/** $defs/SearchResult.hits 的元素 */
export interface SearchHit {
  evidence: EvidenceRef;
  score: number;
  channel: 'dense' | 'sparse' | 'fused' | 'keyword';
}

/** $defs/SearchResult */
export interface SearchResult {
  /** 检索项目当前资料时为 null。 */
  snapshot_id: Id | null;
  mode_used: 'hybrid' | 'keyword';
  index_state: 'ready' | 'building' | 'unavailable';
  hits: SearchHit[];
  /** 后端降级说明，形如 `code:中文说明`（例如 hybrid_index_unavailable:使用关键词通道）。 */
  gaps: string[];
}

export const TASK_KINDS = [
  'parse',
  'rules',
  'diagnosis',
  'revision',
  'recheck',
  'prediction',
  'experiment',
  'export',
] as const;
export type TaskKind = (typeof TASK_KINDS)[number];
export type TaskPurpose = 'research' | 'shadow' | 'business';
export type TaskState =
  | 'queued'
  | 'running'
  | 'waiting_input'
  | 'succeeded'
  | 'failed'
  | 'cancel_requested'
  | 'cancelled';

/**
 * $defs/Task。[差异] 契约里两个 id 必填；后端扩展为可空：
 * 解析与规则提取任务没有快照，核对、改稿、复检使用内置方法所以没有方法包。
 */
/** $defs/Task.coverage（核对任务） */
export interface TaskCoverage {
  status: 'complete' | 'partial' | 'empty';
  rules_total: number;
  rules_checked: number;
  rules_failed: number;
  candidates_dropped: number;
}

export interface Task {
  task_id: Id;
  project_id: Id;
  snapshot_id: Id | null;
  bundle_id: Id | null;
  kind: TaskKind;
  purpose: TaskPurpose;
  state: TaskState;
  stage: string;
  attempt: number;
  input_sha256: string;
  output_artifact: ArtifactRef | null;
  error_code: string | null;
  created_at: IsoDateTime;
  /** [差异] 后端可能附带的人话说明（失败原因、跳过原因等）；没有则不显示。 */
  message?: string | null;
  /** 核对任务的覆盖度；只有 complete 才算完整，partial / empty 的结论不完整，需要重新评审。 */
  coverage?: TaskCoverage | null;
  /** [差异] 解析任务所对应的文件版本；后端不提供时界面按时间就近配对。 */
  file_version_id?: Id | null;
}

/** $defs/TaskEvent（SSE 每条 data） */
export interface TaskEvent {
  task_id: Id;
  attempt: number;
  kind: string;
  state: TaskState;
  stage: string;
  at: IsoDateTime;
}

/** [差异] 契约另有 recheck_pending / reviewed，后端随复检实现；当前只返回这四种。 */
export type RevisionStatus = 'proposed' | 'adopted' | 'rejected' | 'stale';

/** $defs/Revision。diff_artifact 是产物引用；差异正文用 GET /revisions/{id}/diff 读取。 */
export interface Revision {
  revision_id: Id;
  project_id: Id;
  base_version_id: Id;
  finding_ids: Id[];
  allowed_fact_ids: Id[];
  status: RevisionStatus;
  diff_artifact: ArtifactRef;
  target_version_id: Id | null;
  review_ids: Id[];
}

/** GET /revisions/{id}/diff 的一条修改（后端产物 JSON）。 */
export interface RevisionEdit {
  evidence_id: Id;
  original: string;
  replacement: string;
  finding_id: Id;
  facts_used: Id[];
  note: string;
}

/** 被丢弃的候选；除 reason 外的字段随原因不同而不同，只读取已知的几个。 */
export interface RevisionDropped {
  finding_id?: Id;
  reason: string;
  original?: string;
}

/** GET /revisions/{id}/diff 响应（后端未在 response_model 中声明，按产物 JSON 书写）。 */
export interface RevisionDiff {
  prompt_version: string;
  model: string;
  usage: Record<string, number>;
  base_version_id: Id;
  edits: RevisionEdit[];
  dropped: RevisionDropped[];
}

/** $defs/RevisionRequest */
export interface RevisionRequest {
  base_version_id: Id;
  snapshot_id: Id;
  finding_ids: Id[];
  allowed_fact_ids: Id[];
  scope: string;
}

/** $defs/AdoptRequest。不用 If-Match；暂不支持人工编辑后的差异，edited_diff_artifact_id 必须为 null。 */
export interface AdoptRequest {
  base_version_id: Id;
  edited_diff_artifact_id: null;
}

/** 驳回改稿建议的请求体（后端 RejectRevisionRequest）。 */
export interface RejectRevisionRequest {
  base_version_id: Id;
  reason: string;
}

/** $defs/SubmissionRequest */
export interface SubmissionRequest {
  body_version_id: Id;
  snapshot_id: Id;
  submitted_at: IsoDateTime;
  receipt_artifact_id: Id | null;
}

/** $defs/Submission */
export interface Submission {
  submission_id: Id;
  project_id: Id;
  body_version_id: Id;
  snapshot_id: Id;
  submitted_at: IsoDateTime;
  confirmation_review_id: Id;
  receipt_artifact: ArtifactRef | null;
  supersedes: Id | null;
}

export type OutcomeTarget = 'technical_total' | 'composite_total' | 'no_score';
export type StageResult =
  | 'pending'
  | 'technical_shortlisted'
  | 'not_shortlisted'
  | 'rejected'
  | 'candidate'
  | 'awarded'
  | 'not_awarded'
  | 'cancelled'
  | 'failed_tender';

/** $defs/OutcomeRequest */
export interface OutcomeRequest {
  submission_id: Id;
  source_kind: 'user_reported' | 'official';
  target: OutcomeTarget;
  value: DecimalString | null;
  maximum: DecimalString | null;
  aggregation: string | null;
  stage_result: StageResult;
  source_page: number | null;
  published_at: IsoDateTime | null;
  supersedes: Id | null;
  source_artifact_id: Id | null;
  source_description: string;
}

/** $defs/Outcome */
export interface Outcome {
  outcome_id: Id;
  project_id: Id;
  submission_id: Id;
  source_kind: 'user_reported' | 'official';
  verification_status: 'pending' | 'verified' | 'conflict';
  target: OutcomeTarget;
  value: DecimalString | null;
  maximum: DecimalString | null;
  aggregation: string | null;
  stage_result: StageResult;
  source_artifact: ArtifactRef | null;
  source_page: number | null;
  published_at: IsoDateTime | null;
  known_at: IsoDateTime;
  verified_by: Id | null;
  supersedes: Id | null;
}

/** $defs/OutcomeVerifyRequest */
export interface OutcomeVerifyRequest {
  source_artifact_id: Id;
  source_page: number;
  aggregation: string;
  reason: string;
}

/** 只有问题列表分页：后端返回 `{ items, next_cursor }`，客户端统一成 Page<T>。其余列表直接是数组。 */
export interface Page<T> {
  items: T[];
  nextCursor: string | null;
}

/** 后端 Fact（事实集条目）。value_decimal 为十进制字符串。 */
export interface Fact {
  fact_id: Id;
  name: string;
  subject: string;
  scope: string;
  value_decimal: string | null;
  unit: string | null;
  statement: string;
  confirmation: Confirmation;
  evidence_ids: Id[];
}

/** GET /projects/{id}/facts：项目当前（最新）事实集；还没录入过则 fact_set_id 为 null、items 为空。 */
export interface FactList {
  fact_set_id: Id | null;
  items: Fact[];
}

/** POST /projects/{id}/facts 的请求体（后端 FactRequest）。 */
export interface FactRequest {
  name: string;
  subject: string;
  scope: string;
  value_decimal: string | null;
  unit: string | null;
  statement: string;
  evidence_ids: Id[];
}

/** POST /projects/{id}/facts 与 /facts/{fact_id}/withdraw 的响应（后端 FactSetResult）：
 * 每次录入或撤回都生成新事实集，条目带新 ID；撤回时 fact_id 是被撤回的事实 ID。 */
export interface FactSetResult {
  fact_set_id: Id;
  fact_id: Id;
  item_count: number;
}

// ------------------------------------------------------------------ 响应矩阵

export type Verdict = 'satisfied' | 'violated' | 'unclear' | 'failed';

/** 响应矩阵的一行：一条规则在一次评审里的判定。 */
export interface RuleVerdict {
  rule_id: Id;
  kind: RuleKind;
  statement: string;
  rule_basis: RuleBasis;
  verdict: Verdict;
  note: string;
  /** 支持该判定的正文依据；判定为“满足”时至少一条。 */
  evidence: EvidenceRef[];
  finding_ids: Id[];
}

export interface VerdictCounts {
  total: number;
  satisfied: number;
  violated: number;
  unclear: number;
  failed: number;
}

/** 废标／否决与强制类规则计入 qualification，评分条款计入 scoring。 */
export interface Compliance {
  snapshot_id: Id;
  run_id: Id | null;
  coverage: TaskCoverage | null;
  qualification: VerdictCounts;
  scoring: VerdictCounts;
  rows: RuleVerdict[];
}

// ------------------------------------------------------------------ 评分预测

export interface PredictionTopic {
  /** 评分条款及其满分。 */
  topic: string;
  /** 估计失分。 */
  points_lost: DecimalString;
  assessment: string;
  evidence: EvidenceRef[];
  limitations: string;
}

export type CalibrationState = 'uncalibrated' | 'insufficient' | 'calibrated';

/** 预测与官方成绩的对照；样本不足时不给误差（mae、bias 为 null）。 */
export interface Calibration {
  state: CalibrationState;
  pairs: number;
  needed_pairs: number;
  mae: DecimalString | null;
  bias: DecimalString | null;
}

export type PredictionStatus = 'candidate' | 'abstained' | 'failed';
export type ValidationStatus = 'not_validated' | 'validated_in_scope' | 'out_of_scope';

/** $defs/ScoringModelRef：校准所用的打分模型——训练与评估用的官方成绩组数、误差（满分百分制）与适用范围。 */
export interface ScoringModelRef {
  model_id: string;
  pairs: number;
  mae: DecimalString;
  scope: string;
}

export interface Prediction {
  prediction_id: Id;
  project_id: Id;
  snapshot_id: Id;
  run_id: Id;
  target: 'technical_total';
  status: PredictionStatus;
  purpose: TaskPurpose;
  estimated_value: DecimalString | null;
  low: DecimalString | null;
  high: DecimalString | null;
  /** 未校准时为参与估计的评分条款分值合计（与 technical_full_score 对照即覆盖程度）；校准后为技术标满分。 */
  maximum: DecimalString | null;
  /** 评标办法写明的技术标满分。 */
  technical_full_score: DecimalString | null;
  /** validated_in_scope：分数与区间已由打分模型校准；not_validated／out_of_scope：逐项评估的合计，未校准。 */
  validation_status: ValidationStatus;
  reason: string;
  scoring_model: ScoringModelRef | null;
  topics: PredictionTopic[];
  created_at: IsoDateTime;
  calibration: Calibration;
}

// ------------------------------------------------------------------ 报价

export type BenchmarkMethod = 'fixed' | 'average' | 'trimmed_average';

export interface BenchmarkSpec {
  method: BenchmarkMethod;
  fixed_value?: DecimalString | null;
  coefficient: DecimalString;
  trim_pct: DecimalString;
  include_own: boolean;
}

export interface PriceParams {
  full_score: DecimalString;
  above_deduct_per_pct: DecimalString;
  below_deduct_per_pct: DecimalString;
  max_limit?: DecimalString | null;
  abnormal_low_pct?: DecimalString | null;
  benchmark: BenchmarkSpec;
}

/** PUT /price 与 POST /price:simulate 的请求体。 */
export interface PricePlanRequest {
  params: PriceParams;
  competitor_prices: DecimalString[];
  candidate_prices: DecimalString[];
  note: string;
}

export interface PricePlan {
  plan_id: Id;
  project_id: Id;
  params: PriceParams;
  competitor_prices: DecimalString[];
  candidate_prices: DecimalString[];
  note: string;
  supersedes: Id | null;
  created_by: Id;
  created_at: IsoDateTime;
}

export type PriceFlag = 'over_max_limit' | 'abnormal_low';

export interface PricePoint {
  price: DecimalString;
  deviation_pct: DecimalString;
  score: DecimalString;
  flags: PriceFlag[];
}

/** 高于基准价 1% 失去 points_per_pct_above 分，即 1 个技术分约相当于 pct_per_point_above % 的报价。 */
export interface ExchangeRate {
  points_per_pct_above: DecimalString;
  pct_per_point_above: DecimalString | null;
}

export interface PriceSimulation {
  benchmark: DecimalString | null;
  exchange_rate: ExchangeRate;
  candidates: PricePoint[];
  curve: PricePoint[];
  best: PricePoint | null;
  notes: string[];
}

export interface PricePlanWithSimulation {
  plan: PricePlan;
  simulation: PriceSimulation;
}

// ------------------------------------------------------------------ 流水线、报告与度量

export type PipelineStepKey = 'materials' | 'rules' | 'review' | 'prediction';
export type PipelineStepState = 'waiting' | 'running' | 'done' | 'failed';

export interface PipelineStep {
  key: PipelineStepKey;
  state: PipelineStepState;
  task_id: Id | null;
  message: string | null;
}

export type StaleReason = 'body_updated' | 'tender_updated' | 'rules_changed' | 'facts_changed';

export interface PipelineStatus {
  project_id: Id;
  /** waiting_start：项目设置为手动开始评审，资料已就绪或有更新，等人点“开始评审”。 */
  stage: 'waiting_materials' | 'waiting_start' | 'running' | 'done' | 'failed';
  steps: PipelineStep[];
  missing: ('tender' | 'body')[];
  /** 最近一次已完成评审的输入快照。 */
  snapshot_id: Id | null;
  round_no: number | null;
  stale_reasons: StaleReason[];
  rules_total: number;
  rules_unconfirmed: number;
  input_verification_required?: boolean;
  word_pdf_required?: boolean;
}

export interface CategoryCount {
  category: FindingCategory;
  total: number;
  open: number;
  resolved: number;
}

export type NextActionKey =
  | 'upload_materials'
  | 'start_analysis'
  | 'wait_analysis'
  | 'retry_analysis'
  | 'handle_disqualification'
  | 'handle_findings'
  | 'reanalyze'
  | 'review_unclear'
  | 'confirm_rules'
  | 'verify_sources'
  | 'set_price'
  | 'submit'
  | 'record_outcome';
export type NextActionTarget =
  'materials' | 'report' | 'findings' | 'rules' | 'price' | 'submit' | 'outcomes';

export interface NextAction {
  key: NextActionKey;
  title: string;
  detail: string;
  target: NextActionTarget;
  count: number | null;
}

export interface ReportBasis {
  rules_total: number;
  rules_confirmed: number;
  rules_unconfirmed: number;
  coverage: TaskCoverage | null;
  generated_from_snapshot_at: IsoDateTime;
}

export interface PriceSummary {
  plan_id: Id;
  exchange_rate: ExchangeRate;
  best: PricePoint | null;
  candidates: PricePoint[];
  created_at: IsoDateTime;
}

export interface Report {
  project_id: Id;
  snapshot_id: Id;
  round_no: number;
  basis: ReportBasis;
  qualification: Compliance;
  categories: CategoryCount[];
  prediction: Prediction | null;
  price: PriceSummary | null;
  next_actions: NextAction[];
  pipeline: PipelineStatus;
}

export interface OutcomeMetrics {
  submissions: number;
  decided: number;
  shortlisted: number;
  not_shortlisted: number;
  rejected: number;
  awarded: number;
  not_awarded: number;
  shortlist_rate: DecimalString | null;
  award_rate: DecimalString | null;
}

/** 废标／否决风险的闭环：评审发现多少、提交前处理多少、提交时仍未处理多少、招标方实际否决多少。 */
export interface QualificationMetrics {
  identified: number;
  resolved_or_dismissed: number;
  open_at_submission: number;
  rejected_by_buyer: number;
}

export interface RoundPoint {
  round_no: number;
  snapshot_id: Id;
  estimated_value: DecimalString | null;
  open_findings: number;
  resolved_findings: number;
  open_qualification: number;
}

export interface RoundTrend {
  project_id: Id;
  title: string;
  maximum: DecimalString | null;
  actual_value: DecimalString | null;
  rounds: RoundPoint[];
}

export interface Metrics {
  outcomes: OutcomeMetrics;
  qualification: QualificationMetrics;
  calibration: Calibration;
  trends: RoundTrend[];
}
