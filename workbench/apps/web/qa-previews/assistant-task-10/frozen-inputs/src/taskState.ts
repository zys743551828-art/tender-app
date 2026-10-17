import type { RunView, TemplateRequest } from "./contracts";
export const taskNames: Record<TemplateRequest["task_kind"], string> = {
  denial_check: "否决核对",
  scoring_review: "评分核对",
  supplement_impact: "已登记补遗关系核对",
  chapter_suggestion: "章节修改建议",
};
export const taskScopes: Record<TemplateRequest["task_kind"], string> = {
  denial_check:
    "须由统一输入守卫与评审控制面实际接受；未就绪保持未完成，不生成假通过。",
  scoring_review:
    "正式评分资格尚未就绪时拒绝运行，不以聊天片段代替完整输入与三次判断。",
  supplement_impact:
    "仅核对已登记效力关系，不进行语义影响检查；运行后仍须分别核对实际处理结果。",
  chapter_suggestion:
    "只产出章节修改提案，须原文差异预览后明确采纳，不自动改稿。",
};
export const taskRunNames: Record<RunView["state"], string> = {
  queued: "等待处理",
  running: "正在处理",
  cancel_requested: "正在取消",
  succeeded: "已记录处理结果",
  failed: "执行失败",
  cancelled: "已取消",
  awaiting_review: "等待后续核对",
  blocked: "受阻，尚未完成",
  superseded: "原输入已过期",
  unknown: "结果或费用未知",
  reconciliation_required: "需核对调用账本",
};
export function newTaskConfiguration(): TemplateRequest {
  return {
    name: "",
    task_kind: "supplement_impact",
    instructions: "",
    section_id: null,
    source_selection: { mode: "current_project", version_ids: [] },
    trigger: { mode: "manual", cron: null, timezone: "Asia/Shanghai" },
  };
}
export function triggerDescription(trigger: TemplateRequest["trigger"]) {
  if (!trigger || trigger.mode === "manual") return "仅手动运行";
  if (trigger.mode === "material_updated") return "资料实际入库更新后触发";
  return `明确定时：${trigger.cron ?? "尚未设置"} · ${trigger.timezone ?? "Asia/Shanghai"}`;
}
