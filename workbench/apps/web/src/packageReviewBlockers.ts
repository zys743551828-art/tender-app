import type { PackageReviewInputPreview } from "./contracts";

export const reviewInputBlockers: Record<
  PackageReviewInputPreview["blockers"][number],
  string
> = {
  PROJECT_WORK_CLOSED: "项目已结束或归档，保留只读输入。",
  PACKAGE_BIDDER_UNCONFIRMED: "投标主体尚未确认。",
  PACKAGE_REVIEW_IDENTITY_STALE: "主体、工程、标段或轮次身份已变化。",
  PACKAGE_REVIEW_PACKAGE_STALE: "所选包已是历史修订，请明确核对当前包。",
  PACKAGE_REVIEW_INVENTORY_STALE: "所选要求清单已是历史版本。",
  PACKAGE_REVIEW_RULE_SET_STALE: "当前规则集已更新，需重新核对要求清单。",
  PACKAGE_REVIEW_SOURCE_UNPROVEN: "尚无可证明的完整来源范围。",
  PACKAGE_REVIEW_SOURCE_CHANGED: "来源效力记录已变化，旧输入保持原样。",
  PACKAGE_REVIEW_SOURCE_NOT_EFFECTIVE: "来源尚未生效、已撤回、过期或用途不符。",
  PACKAGE_REVIEW_GENERATED_OUTPUT_UNPROVEN:
    "生成正文的编写依据、确认状态或输出来源已无法核验，请重新核对后生成。",
  PACKAGE_REVIEW_MEMBERS_UNPROVEN: "成员的解析、页数或逻辑范围仍未明确。",
  PACKAGE_REVIEW_EVIDENCE_CHANGED:
    "冻结解析对应的文件、页或证据记录无法核对，需检查原件与解析。",
  PACKAGE_REVIEW_PHYSICAL_RANGE_GAP: "包内仍有未纳入逻辑范围的物理页。",
  PACKAGE_REVIEW_EXTRACTION_UNPROVEN: "要求抽取尚无精确冻结输入与完成绑定。",
  PACKAGE_REVIEW_REQUIREMENT_COMPLETENESS_UNPROVEN:
    "要求清单完整性尚未获得证明。",
  PACKAGE_REVIEW_EXECUTOR_NOT_READY: "正式整包评审执行器尚未接入。",
};
