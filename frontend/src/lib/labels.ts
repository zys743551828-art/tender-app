/** 枚举 → 中文展示。未知取值显示"未知（原值）"，不留空白、不抛错。 */
function dict<T extends string>(map: Record<T, string>) {
  return (v: string | null | undefined): string => {
    if (v === null || v === undefined || v === '') return '暂无';
    return (map as Record<string, string | undefined>)[v] ?? `未知（${v}）`;
  };
}

export const fileRoleLabel = dict({
  tender: '招标文件',
  supplement: '补遗／答疑',
  drawing: '图纸',
  boq: '工程量清单',
  body: '施组正文',
  submission: '已提交文件',
  official_result: '官方结果',
  other: '其他资料',
});

export const projectStateLabel = dict({
  materials_pending: '资料待补充',
  ready_to_analyze: '待开始评审',
  analyzing: '评审中',
  analysis_failed: '评审中断',
  issues_open: '问题待处理',
  ready_to_submit: '可登记提交',
  submitted: '已提交',
  archived: '已归档',
  cancelled: '已取消',
  failed_tender: '流标',
});

export type Tone = 'neutral' | 'green' | 'amber' | 'red' | 'blue' | 'gray' | 'ai';

export function projectStateTone(state: string): Tone {
  switch (state) {
    case 'issues_open':
    case 'materials_pending':
    case 'ready_to_analyze':
      return 'amber';
    case 'analysis_failed':
      return 'red';
    case 'ready_to_submit':
    case 'submitted':
    case 'archived':
      return 'green';
    case 'cancelled':
    case 'failed_tender':
      return 'gray';
    default:
      return 'blue';
  }
}

export const findingNatureLabel = dict({
  fact_conflict: '事实冲突',
  needs_confirmation: '待确认事项',
  suggestion: '优化建议',
});
export const findingImpactLabel = dict({
  qualification: '资格',
  technical: '技术响应',
  delivery: '交付',
});
export const findingSeverityLabel = dict({
  critical: '重大',
  normal: '一般',
  improvement: '可改进',
});
export const findingStatusLabel = dict({
  candidate: '待复核',
  confirmed: '已确认',
  rejected: '已驳回',
  deferred: '暂缓',
  revision_pending: '待修改',
  recheck_pending: '待重查',
  resolved: '已解决',
});

export const decisionLabel = dict({
  confirm: '确认问题',
  reject: '驳回',
  defer: '暂缓',
  resolve: '标记已解决',
  request_facts: '暂缓，待补事实',
  reopen: '重新打开',
});

export const ruleKindLabel = dict({
  mandatory: '强制性要求',
  scoring: '评分条款',
  disqualification: '废标／否决项',
  recommendation: '建议性要求',
  exception: '例外',
});

/** 问题分类（Finding.category），顺序即页签顺序。 */
export const findingCategoryLabel = dict({
  disqualification: '废标／否决风险',
  response: '强制性要求',
  consistency: '前后矛盾',
  scope: '范围残留',
  improvement: '改进建议',
});
export const findingCategoryHint = dict({
  disqualification: '与否决或废标条款冲突，整份投标可能作废。',
  response: '与强制性要求冲突，或正文无法确认已响应。',
  consistency: '同一个量在正文不同位置取值不同，或存在大段重复。',
  scope: '正文出现招标文件及补遗没有的工程对象，多为套用了其他项目的模板。',
  improvement: '评分条款、建议性要求上可以改进的地方。',
});
export const findingSourceLabel = dict({
  rule: '规则核对',
  consistency: '一致性检测',
  scope: '范围检测',
});
/** 问题所依据的规则当时是否已人工确认。 */
export const ruleBasisLabel = dict({
  confirmed: '依据已确认',
  unconfirmed: '依据未确认',
});

/** 响应矩阵里的判定。“无法判断”不等于“满足”，必须让人看见。 */
export const verdictLabel = dict({
  satisfied: '满足',
  violated: '违反',
  unclear: '无法判断',
  failed: '检查失败',
});

export const pipelineStepLabel = dict({
  materials: '资料解析',
  rules: '提取规则',
  review: '逐条核对',
  prediction: '评分预测',
});
export const pipelineStateLabel = dict({
  waiting: '等待中',
  running: '进行中',
  done: '已完成',
  failed: '失败',
});
export const staleReasonLabel = dict({
  body_updated: '技术标正文有了新版本',
  tender_updated: '招标文件或补遗有了新版本',
  rules_changed: '规则已更正',
  facts_changed: '事实库有更新',
});
export const missingMaterialLabel = dict({
  tender: '招标文件',
  body: '施组正文',
});

export const predictionStatusLabel = dict({
  candidate: '已给出估计',
  abstained: '未给出估计',
  failed: '预测失败',
});
export const validationStatusLabel = dict({
  not_validated: '未校准',
  validated_in_scope: '已校准',
  out_of_scope: '超出校准范围',
});
export const calibrationStateLabel = dict({
  uncalibrated: '尚无对照样本',
  insufficient: '样本不足',
  calibrated: '已校准',
});

export const benchmarkMethodLabel = dict({
  fixed: '固定值',
  average: '竞争对手报价平均值',
  trimmed_average: '去极值平均值',
});
export const priceFlagLabel = dict({
  over_max_limit: '超过最高限价，将被否决',
  abnormal_low: '低于异常低价线，有被认定为异常低价的风险',
});
export const confirmationLabel = dict({
  pending: '待人工确认',
  confirmed: '已确认',
  rejected: '已驳回',
});
export const ruleSetStatusLabel = dict({
  candidate: '候选',
  conflict: '存在冲突',
  confirmed: '已确认',
});

export const taskKindLabel = dict({
  parse: '资料解析',
  rules: '规则提取',
  diagnosis: '规则核对',
  revision: '修改建议',
  recheck: '复检',
  prediction: '评分预测',
  experiment: '实验',
  export: '导出',
});
export const taskStateLabel = dict({
  queued: '排队中',
  running: '进行中',
  waiting_input: '等待补充事实',
  succeeded: '已完成',
  failed: '失败',
  cancel_requested: '正在取消',
  cancelled: '已取消',
});
/** 任务阶段令牌 → 中文。未知阶段显示“未知（原值）”。 */
export const taskStageLabel = dict({
  queued: '排队中',
  running: '进行中',
  extracting: '正在提取规则',
  analyzing: '正在分析',
  waiting_input: '等待补充事实',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
});
export const purposeLabel = dict({
  research: '研究',
  shadow: '影子运行',
  business: '业务',
});

export const revisionStatusLabel = dict({
  proposed: '建议待采纳',
  adopted: '已采纳',
  rejected: '已驳回',
  stale: '底稿已变化',
});

export const droppedReasonLabel = dict({
  invalid_output: '模型输出不合格',
  finding_not_requested: '修改对应的问题不在本次请求内',
  unknown_evidence: '引用了不存在的正文片段',
  original_not_verbatim: '“原文”与正文不一致',
  fact_not_allowed: '使用了未允许的事实',
  invented_number: '出现了没有依据的数字',
});

export const outcomeTargetLabel = dict({
  technical_total: '技术总分',
  composite_total: '综合总分',
  no_score: '无分值（仅阶段结果）',
});
export const stageResultLabel = dict({
  pending: '待公布',
  technical_shortlisted: '技术入围',
  not_shortlisted: '未入围',
  rejected: '被否决',
  candidate: '中标候选人',
  awarded: '最终中标',
  not_awarded: '未中标',
  cancelled: '项目取消',
  failed_tender: '流标',
});
export const sourceKindLabel = dict({
  user_reported: '人工报送',
  official: '官方来源',
});
export const verificationLabel = dict({
  pending: '待核实',
  verified: '已核实',
  conflict: '存在冲突',
});
export const indexStateLabel = dict({
  ready: '索引就绪',
  building: '索引构建中',
  unavailable: '索引不可用',
});
export const evidenceKindLabel = dict({
  text: '文字',
  table: '表格',
  visual_observation: '图像观察',
});
export const searchChannelLabel = dict({
  dense: '语义检索',
  sparse: '稀疏检索',
  fused: '融合排序',
  keyword: '关键词',
});
export const semanticReviewLabel = dict({
  pending: '语义待复核',
  supported: '语义已支持',
  unsupported: '语义不支持',
});
