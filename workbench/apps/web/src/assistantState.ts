import type {
  AssistantGlobalConversation,
  WorkConversationView,
  WorkMessageView,
  AssistantGlobalMessage,
  AssistantSourcePage,
  AssistantSourceRef,
  AssistantJob,
} from "./contracts";
export type AssistantConversation =
  | WorkConversationView
  | AssistantGlobalConversation;
export type AssistantMessage = WorkMessageView | AssistantGlobalMessage;
export type SelectedAssistantSource = {
  reference: AssistantSourceRef;
  title: string;
  bidId: string | null;
};
export const assistantStates = {
  active: "进行中",
  closed: "已结束",
  hidden: "已归档",
};
export const assistantJobs: Record<AssistantJob["operation"]["state"], string> =
  {
    queued: "等待处理",
    running: "正在处理",
    cancel_requested: "正在取消",
    succeeded: "处理步骤已结束",
    failed: "执行失败",
    cancelled: "已取消",
  };
export const sourceKinds: Record<AssistantSourceRef["kind"], string> = {
  project: "项目结构化记忆",
  document: "资料原页",
  section: "已保存章节",
  knowledge_unit: "知识查证片段",
};
export function sourceIdentity(ref: AssistantSourceRef) {
  return JSON.stringify([
    ref.kind,
    ref.id,
    ref.trace_id,
    ref.physical_page ?? null,
  ]);
}
export function selectableSource(
  item: AssistantSourcePage["items"][number],
  bidId: string | null,
) {
  return (
    item.available && !!item.reference && (!bidId || item.bid_id === bidId)
  );
}
export const assistantReason = (code: string) =>
  ({
    MODEL_CALL_REQUIRES_RECONCILIATION:
      "调用费用状态未知，不能启动新的付费尝试。请先等待核账。",
    ASSISTANT_SOURCE_NOT_READY:
      "所选资料尚未形成可核验解析，请选可读物理页或稍后重试。",
    ASSISTANT_SOURCE_INVALID: "所选来源身份无法核对，请重新选择真实来源。",
    MODEL_NOT_CONFIGURED:
      "助手服务尚未配置，本次没有形成模型处理。输入仍保留。",
    ASSISTANT_CONTEXT_CHANGED:
      "项目、事实、章节或来源依据已变化，请重新核对后再使用候选。",
    ASSISTANT_SOURCE_CHANGED: "所选来源版本已变化，请明确换用当前可信来源。",
    ASSISTANT_BILLING_RECONCILIATION_REQUIRED:
      "调用费用状态未知，需先核账；不能用新消息标识重复付费。",
    CONVERSATION_CLOSED: "请先继续此主会话，再发给助手。",
    TASK_REVIEW_EXECUTOR_NOT_READY: "否决核对的统一执行守卫尚未接通。",
    TASK_SCORING_NOT_QUALIFIED: "评分能力尚无正式资格，不能运行或生成假分数。",
  })[code] ?? code;

/** A browser cache may contain local drafts, never invented server authority. */
export function isSelectedAssistantSource(
  value: unknown,
): value is SelectedAssistantSource {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<SelectedAssistantSource>;
  const ref = item.reference;
  return (
    typeof item.title === "string" &&
    (item.bidId === null || typeof item.bidId === "string") &&
    !!ref &&
    typeof ref === "object" &&
    Object.hasOwn(sourceKinds, ref.kind) &&
    typeof ref.id === "string" &&
    typeof ref.version === "string" &&
    (ref.trace_id === null || typeof ref.trace_id === "string") &&
    (ref.physical_page === undefined ||
      (Number.isSafeInteger(ref.physical_page) && ref.physical_page > 0))
  );
}
