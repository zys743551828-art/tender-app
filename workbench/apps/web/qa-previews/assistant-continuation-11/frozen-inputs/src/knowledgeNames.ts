import type {
  KnowledgeReferenceRequest,
  KnowledgeVersionRequest,
  KnowledgeView,
} from "./contracts";
export const knowledgeStates: Record<KnowledgeView["workflow"], string> = {
  candidate: "待完善候选",
  pending_confirmation: "待明确发布",
  published: "已发布",
  withdrawn: "已停用",
  expired: "已到期",
  superseded: "已由新版替代",
  source_invalid: "来源已失效",
  not_yet_effective: "尚未生效",
};
export const knowledgePurposes: Record<
  KnowledgeReferenceRequest["purpose"],
  string
> = {
  assist: "项目辅助查证",
  authoring: "正文编写参考",
  compliance: "核心核对参考",
  history: "历史回顾",
};
export const knowledgeCategories: Record<
  KnowledgeVersionRequest["categories"][number],
  string
> = {
  company_fact: "本公司可用事实",
  method: "施工方法",
  standard: "规范标准",
  retrospective: "历史复盘",
  chapter_reference: "章节参考",
};

const applicabilityReasons: Record<string, string> = {
  KNOWLEDGE_SCOPE_CHANGED:
    "查证依据、索引或项目适用条件已变化，请使用当前条件重新查证。",
  KNOWLEDGE_RAG_NOT_READY: "企业知识查证服务尚未就绪，已保留输入。",
  KNOWLEDGE_INDEX_INCOMPLETE:
    "知识索引尚未完整建立，请从知识条目核对处理状态。",
  KNOWLEDGE_NOT_PUBLISHED: "知识版本尚未发布或已失效，不能新增查证选用。",
  VERSION_NOT_EFFECTIVE: "此知识版本当前不可新用，当时摘录与原件仍可追溯。",
  APPLICABILITY_UNKNOWN: "适用范围或有效期尚未明确，不能新增选用。",
  PROJECT_IDENTITY_UNCONFIRMED: "项目投标主体或工程身份尚未有据确认。",
  SUBJECT_MISMATCH: "当前投标主体不在此知识版本的明确适用范围内。",
  PROJECT_MISMATCH: "当前项目不在此知识版本的明确项目范围内。",
  REGION_UNKNOWN_OR_MISMATCH: "项目地区尚未注明，或与知识适用地区不一致。",
  ENGINEERING_TYPE_UNKNOWN_OR_MISMATCH:
    "工程类型尚未注明，或与知识适用类型不一致。",
  PURPOSE_FORBIDDEN: "当前用途不在此知识版本允许的用途内。",
  REFERENCE_IS_NOT_CURRENT_REGULATORY_AUTHORITY:
    "此条目不能作为本项目当前有效的规范依据。",
  PROJECT_FACT_UNKNOWN_OR_CONFLICT:
    "所需工程事实尚未确认、已变化或存在冲突，须重新核验。",
};
export const knowledgeReason = (reason: string) =>
  applicabilityReasons[reason] ?? reason;
