import type {
  Compliance,
  EvidenceRef,
  Fact,
  FileVersion,
  Finding,
  InputSnapshot,
  Metrics,
  Outcome,
  PipelineStatus,
  Prediction,
  PricePlan,
  PricePlanWithSimulation,
  PriceSimulation,
  Report,
  Revision,
  RuleSet,
  RuleVerdict,
  RevisionDiff,
  Submission,
  Task,
} from '../api/types';

export const SHA = 'a'.repeat(64);

export function task(over: Partial<Task> = {}): Task {
  return {
    task_id: 'tsk-1',
    project_id: 'prj-1',
    snapshot_id: null,
    bundle_id: null,
    kind: 'rules',
    purpose: 'business',
    state: 'queued',
    stage: 'queued',
    attempt: 1,
    input_sha256: SHA,
    output_artifact: null,
    error_code: null,
    created_at: '2026-10-02T03:00:00Z',
    ...over,
  };
}

export function snapshot(over: Partial<InputSnapshot> = {}): InputSnapshot {
  return {
    snapshot_id: 'snp-1',
    project_id: 'prj-1',
    contract_version: 'input-v1',
    file_version_ids: ['ver-t', 'ver-b'],
    body_version_id: 'ver-b',
    rule_set_id: 'rls-1',
    fact_set_id: null,
    as_of: '2026-10-02T03:20:00Z',
    reference_dataset_id: null,
    coverage_gaps: [],
    sha256: SHA,
    ...over,
  };
}

export function revision(over: Partial<Revision> = {}): Revision {
  return {
    revision_id: 'rvs-1',
    project_id: 'prj-1',
    base_version_id: 'ver-b',
    finding_ids: ['fnd-1'],
    allowed_fact_ids: [],
    status: 'proposed',
    diff_artifact: {
      artifact_id: 'art-diff-1',
      sha256: SHA,
      media_type: 'application/json',
      byte_size: 2048,
      contract_version: 'artifact-v1',
    },
    target_version_id: null,
    review_ids: [],
    ...over,
  };
}

export function fileVersion(
  id: string,
  role: FileVersion['role'],
  name: string,
  mediaType = 'application/pdf',
): FileVersion {
  return {
    version_id: id,
    project_id: 'prj-1',
    file_id: `f-${id}`,
    version_number: 1,
    original_name: name,
    role,
    artifact: {
      artifact_id: `a-${id}`,
      sha256: SHA,
      media_type: mediaType,
      byte_size: 1000,
      contract_version: 'artifact-v1',
    },
    obtained_at: '2026-10-01T00:00:00Z',
    document_date: null,
    association_status: 'confirmed',
    supersedes: null,
  };
}

export function submission(over: Partial<Submission> = {}): Submission {
  return {
    submission_id: 'sub-1',
    project_id: 'prj-1',
    body_version_id: 'ver-b',
    snapshot_id: 'snp-1',
    submitted_at: '2026-10-05T02:00:00Z',
    confirmation_review_id: 'rev-9',
    receipt_artifact: null,
    supersedes: null,
    project_title: '城市支路及排水改造',
    lot: '一标段',
    round: 1,
    ...over,
  };
}

export function outcome(over: Partial<Outcome> = {}): Outcome {
  return {
    outcome_id: 'out-1',
    project_id: 'prj-1',
    submission_id: 'sub-1',
    source_kind: 'user_reported',
    verification_status: 'pending',
    target: 'technical_total',
    value: '86.5',
    maximum: '100',
    aggregation: null,
    stage_result: 'pending',
    source_artifact: null,
    source_page: null,
    published_at: null,
    known_at: '2026-10-06T02:00:00Z',
    verified_by: null,
    supersedes: null,
    ...over,
  };
}

export function revisionDiff(over: Partial<RevisionDiff> = {}): RevisionDiff {
  return {
    prompt_version: 'revision-v1',
    model: 'm1',
    usage: {},
    base_version_id: 'ver-b',
    edits: [
      {
        evidence_id: 'evd-2',
        original: '本工程拟用 160 天完成',
        replacement: '本工程总工期 180 日历天',
        finding_id: 'fnd-1',
        facts_used: [],
        note: '对齐招标工期',
      },
    ],
    dropped: [],
    ...over,
  };
}

export function fact(over: Partial<Fact> = {}): Fact {
  return {
    fact_id: 'fai-1',
    name: '总工期',
    subject: '本公司',
    scope: '一标段',
    value_decimal: '180',
    unit: '日历天',
    statement: '承诺总工期 180 日历天',
    confirmation: 'confirmed',
    evidence_ids: ['evd-1'],
    ...over,
  };
}

/** 证据：version_id 为 ver-b 的出自施组正文，其余出自招标文件。 */
export function evidence(over: Partial<EvidenceRef> = {}): EvidenceRef {
  const body = over.version_id === 'ver-b';
  return {
    evidence_id: 'evd-1',
    project_id: 'prj-1',
    version_id: 'ver-t',
    file_role: body ? 'body' : 'tender',
    file_name: body ? '施工组织设计.pdf' : '招标文件.pdf',
    source_sha256: SHA,
    physical_page: 3,
    printed_page: '2',
    quote: '总工期为 180 日历天',
    kind: 'text',
    parser_version: 'p1',
    bbox: null,
    semantic_review: 'supported',
    ...over,
  };
}

/** 规则集：默认已确认、两条规则都已确认。 */
export function ruleSet(over: Partial<RuleSet> = {}): RuleSet {
  return {
    rule_set_id: 'rls-1',
    project_id: 'prj-1',
    source_version_ids: ['ver-t'],
    status: 'confirmed',
    revision: 3,
    rules: [
      {
        rule_id: 'rul-1',
        kind: 'mandatory',
        statement: '总工期不超过 180 日历天',
        conditions: [],
        exceptions: [],
        evidence: [],
        confirmation: 'confirmed',
        max_points: null,
      },
    ],
    terms: { technical_full_score: null, price_rule: null },
    ...over,
  };
}

/** 一个已完成评审、没有更新的流水线状态。 */
export function pipeline(over: Partial<PipelineStatus> = {}): PipelineStatus {
  return {
    project_id: 'prj-1',
    stage: 'done',
    steps: [
      { key: 'materials', state: 'done', task_id: null, message: null },
      { key: 'rules', state: 'done', task_id: null, message: null },
      { key: 'review', state: 'done', task_id: null, message: null },
      { key: 'prediction', state: 'done', task_id: null, message: null },
    ],
    missing: [],
    snapshot_id: 'snp-1',
    round_no: 1,
    stale_reasons: [],
    rules_total: 2,
    rules_unconfirmed: 0,
    ...over,
  };
}

export function finding(over: Partial<Finding> = {}): Finding {
  return {
    finding_id: 'fnd-1',
    project_id: 'prj-1',
    snapshot_id: 'snp-1',
    run_id: 'run-1',
    rule_id: 'rul-1',
    source: 'rule',
    category: 'response',
    rule_basis: 'confirmed',
    nature: 'fact_conflict',
    impact: 'technical',
    severity: 'normal',
    statement: '工期表述与招标要求不一致',
    evidence: [
      evidence({ evidence_id: 'evd-1', version_id: 'ver-t', quote: '工期 180 日历天' }),
      evidence({
        evidence_id: 'evd-2',
        version_id: 'ver-b',
        physical_page: 17,
        printed_page: null,
        quote: '本工程拟用 160 天完成',
      }),
    ],
    required_facts: [],
    status: 'candidate',
    official_score_effect: null,
    revision: 4,
    ...over,
  };
}

export function verdictRow(over: Partial<RuleVerdict> = {}): RuleVerdict {
  return {
    rule_id: 'rul-1',
    kind: 'mandatory',
    statement: '总工期不超过 180 日历天',
    rule_basis: 'confirmed',
    verdict: 'satisfied',
    note: '',
    evidence: [evidence({ evidence_id: 'evd-9', quote: '总工期 175 日历天', version_id: 'ver-b' })],
    finding_ids: [],
    ...over,
  };
}

export function compliance(rows: RuleVerdict[] = [verdictRow()]): Compliance {
  const count = (kinds: string[]) => {
    const rs = rows.filter((r) => kinds.includes(r.kind));
    const n = (v: string) => rs.filter((r) => r.verdict === v).length;
    return {
      total: rs.length,
      satisfied: n('satisfied'),
      violated: n('violated'),
      unclear: n('unclear'),
      failed: n('failed'),
    };
  };
  return {
    snapshot_id: 'snp-1',
    run_id: 'run-1',
    coverage: {
      status: 'complete',
      rules_total: rows.length,
      rules_checked: rows.length,
      rules_failed: 0,
      candidates_dropped: 0,
    },
    qualification: count(['mandatory', 'disqualification']),
    scoring: count(['scoring']),
    rows,
  };
}

export function prediction(over: Partial<Prediction> = {}): Prediction {
  return {
    prediction_id: 'prd-1',
    project_id: 'prj-1',
    snapshot_id: 'snp-1',
    run_id: 'run-1',
    target: 'technical_total',
    status: 'candidate',
    purpose: 'research',
    estimated_value: '72.5',
    low: '65',
    high: '80',
    maximum: '100',
    technical_full_score: '100',
    validation_status: 'not_validated',
    reason: '还没有生效的打分模型：分数是逐项评估的合计，尚未用官方成绩校准，不是对结果的承诺。',
    scoring_model: null,
    topics: [
      {
        topic: '施工组织设计的针对性（满分 10 分）',
        points_lost: '4.5',
        assessment: '正文对交通导改的描述偏笼统。',
        evidence: [
          evidence({ evidence_id: 'evd-7', quote: '交通导改按常规处理', version_id: 'ver-b' }),
        ],
        limitations: '只依据文字内容评估。',
      },
    ],
    created_at: '2026-10-02T04:00:00Z',
    calibration: { state: 'uncalibrated', pairs: 0, needed_pairs: 20, mae: null, bias: null },
    ...over,
  };
}

export function report(over: Partial<Report> = {}): Report {
  return {
    project_id: 'prj-1',
    snapshot_id: 'snp-1',
    round_no: 1,
    basis: {
      rules_total: 2,
      rules_confirmed: 1,
      rules_unconfirmed: 1,
      coverage: null,
      generated_from_snapshot_at: '2026-10-02T03:20:00Z',
    },
    qualification: compliance(),
    categories: [
      { category: 'disqualification', total: 0, open: 0, resolved: 0 },
      { category: 'response', total: 2, open: 1, resolved: 1 },
      { category: 'consistency', total: 1, open: 1, resolved: 0 },
      { category: 'scope', total: 0, open: 0, resolved: 0 },
      { category: 'improvement', total: 3, open: 3, resolved: 0 },
    ],
    prediction: prediction(),
    price: null,
    next_actions: [
      {
        key: 'handle_findings',
        title: '处理 5 个影响得分或一致性的问题',
        detail: '按失分影响从大到小处理。',
        target: 'findings',
        count: 5,
      },
      {
        key: 'set_price',
        title: '填写评标价规则，模拟报价得分',
        detail: '价格分与技术分合在一起才决定排名。',
        target: 'price',
        count: null,
      },
    ],
    pipeline: pipeline(),
    ...over,
  };
}

export function simulation(over: Partial<PriceSimulation> = {}): PriceSimulation {
  const pt = (
    price: string,
    dev: string,
    score: string,
    flags: ('over_max_limit' | 'abnormal_low')[] = [],
  ) => ({
    price,
    deviation_pct: dev,
    score,
    flags,
  });
  return {
    benchmark: '1000',
    exchange_rate: { points_per_pct_above: '1', pct_per_point_above: '1' },
    candidates: [pt('980', '-2', '29'), pt('1100', '10', '20', ['over_max_limit'])],
    curve: [pt('900', '-10', '25'), pt('1000', '0', '30'), pt('1100', '10', '20')],
    best: pt('980', '-2', '29'),
    notes: [],
    ...over,
  };
}

export function pricePlan(over: Partial<PricePlan> = {}): PricePlan {
  return {
    plan_id: 'prp-1',
    project_id: 'prj-1',
    params: {
      full_score: '30',
      above_deduct_per_pct: '1',
      below_deduct_per_pct: '0.5',
      max_limit: '1050',
      abnormal_low_pct: null,
      benchmark: {
        method: 'fixed',
        fixed_value: '1000',
        coefficient: '1',
        trim_pct: '0',
        include_own: false,
      },
    },
    competitor_prices: [],
    candidate_prices: ['980', '1100'],
    note: '',
    supersedes: null,
    created_by: 'mem-1',
    created_at: '2026-10-03T03:00:00Z',
    ...over,
  };
}

export function priceWithSimulation(): PricePlanWithSimulation {
  return { plan: pricePlan(), simulation: simulation() };
}

export function metrics(over: Partial<Metrics> = {}): Metrics {
  return {
    outcomes: {
      submissions: 4,
      decided: 3,
      shortlisted: 2,
      not_shortlisted: 1,
      rejected: 0,
      awarded: 1,
      not_awarded: 1,
      shortlist_rate: '0.6667',
      award_rate: '0.5',
    },
    qualification: {
      identified: 6,
      resolved_or_dismissed: 5,
      open_at_submission: 1,
      rejected_by_buyer: 0,
    },
    calibration: { state: 'insufficient', pairs: 3, needed_pairs: 20, mae: null, bias: null },
    trends: [
      {
        project_id: 'prj-1',
        title: '城市支路及排水改造',
        maximum: '100',
        actual_value: '78',
        rounds: [
          {
            round_no: 1,
            snapshot_id: 'snp-1',
            estimated_value: '65',
            open_findings: 6,
            resolved_findings: 0,
            open_qualification: 2,
          },
          {
            round_no: 2,
            snapshot_id: 'snp-2',
            estimated_value: '74',
            open_findings: 2,
            resolved_findings: 4,
            open_qualification: 0,
          },
        ],
      },
    ],
    ...over,
  };
}
