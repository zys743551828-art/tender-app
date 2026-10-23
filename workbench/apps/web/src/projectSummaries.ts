import type { ProjectWorkSummary, ProjectWorkSummaryBatch } from "./contracts";

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const count = (value: unknown): value is number =>
  Number.isSafeInteger(value) && Number(value) >= 0;

export function checkedProjectSummaries(
  value: unknown,
  requested: readonly string[],
): ProjectWorkSummaryBatch {
  const invalid = () => new Error("项目摘要身份或状态不完整，请重新读取。");
  if (
    !record(value) ||
    value.version !== "project-work-summary/1" ||
    typeof value.observed_at !== "string" ||
    !Number.isFinite(Date.parse(value.observed_at)) ||
    !Array.isArray(value.items) ||
    value.items.length !== requested.length ||
    new Set(requested).size !== requested.length
  )
    throw invalid();
  value.items.forEach((item: unknown, index: number) => {
    if (
      !record(item) ||
      item.bid_id !== requested[index] ||
      !["preparation", "working", "submitted", "closed", "terminated"].includes(
        String(item.phase),
      ) ||
      !(
        item.archived_at === null ||
        (typeof item.archived_at === "string" &&
          Number.isFinite(Date.parse(item.archived_at)))
      ) ||
      !record(item.package_counts) ||
      !count(item.package_counts.authority) ||
      !count(item.package_counts.bid) ||
      !record(item.head_members) ||
      !count(item.head_members.total) ||
      !count(item.head_members.parse_not_frozen) ||
      item.head_members.parse_not_frozen > item.head_members.total ||
      item.action_scope !== "package_directory" ||
      item.risk_status !== "not_evaluated" ||
      item.prediction_status !== "not_evaluated" ||
      item.critical_risk_count !== null ||
      item.other_risk_count !== null ||
      item.predicted_score !== null ||
      item.inventory_complete !== false ||
      item.formal_scoring_eligible !== false ||
      item.submission_eligible !== false ||
      !record(item.next_action) ||
      typeof item.next_action.blocked !== "boolean" ||
      typeof item.next_action.reason !== "string" ||
      !item.next_action.reason.trim() ||
      ![
        "assemble_packages",
        "inspect_package_parses",
        "choose_package_revision",
        "view_history",
      ].includes(String(item.next_action.action)) ||
      item.next_action.target_url !==
        `/bids/${item.bid_id}/${item.next_action.action === "view_history" ? "work-context" : "packages"}`
    )
      throw invalid();
  });
  return value as unknown as ProjectWorkSummaryBatch;
}

export function summaryPage(
  summary: ProjectWorkSummary,
): "packages" | "work-context" {
  return summary.next_action.target_url.endsWith("/work-context")
    ? "work-context"
    : "packages";
}
