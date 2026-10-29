import type {
  PackageSubmissionView,
  PackageTechnicalScopeView,
} from "./contracts";
import {
  exactKeys,
  executionId as uuid,
  recordObject as object,
} from "./executionInputValidation";
import { outcomeInstant } from "./packageOutcomeProtocol";
import { validatePackageSubmission } from "./packageSubmissionProtocol";
import { technicalText as text } from "./packageTechnicalScopeProtocol";

function invalid(): never {
  throw new Error("目录身份或分页信息不一致，请重新读取后选择。");
}

export async function technicalSubmissions(
  value: unknown,
  saved: PackageTechnicalScopeView,
) {
  const scope = saved.manifest.preview.manifest.scope;
  if (
    !object(value) ||
    !exactKeys(value, ["items", "has_more", "next_cursor"]) ||
    !Array.isArray(value.items) ||
    value.items.length > 20 ||
    typeof value.has_more !== "boolean" ||
    (value.has_more
      ? !text(value.next_cursor, 4096)
      : value.next_cursor !== null) ||
    new Set(value.items.map((item) => item?.id)).size !== value.items.length
  )
    invalid();
  const items: PackageSubmissionView[] = [];
  for (const item of value.items) {
    if (
      !object(item) ||
      !uuid(item.id) ||
      item.bid_id !== scope.bid_id ||
      (item.subject_kind !== undefined &&
        !["single_body", "bid_package"].includes(String(item.subject_kind)))
    )
      invalid();
    if (item.subject_kind !== "bid_package") {
      if (!uuid(item.body_version_id) || item.package_binding !== undefined)
        invalid();
      continue;
    }
    const checked = await validatePackageSubmission(
      item as PackageSubmissionView,
      scope.bid_id,
    );
    const bound = checked.package_binding.manifest.subject;
    if (
      bound.package_id === scope.package_id &&
      bound.revision_id === scope.revision_id
    )
      items.push(checked);
  }
  return { items, nextCursor: value.next_cursor as string | null };
}

export type TechnicalScaleChoice = {
  id: string;
  purpose: "current_prebid" | "historical_backtest";
  submission_id: string | null;
  created_at: string;
  state: string;
  scale_description: string;
};

export function technicalScaleConfigured(value: unknown): boolean {
  if (
    !object(value) ||
    !exactKeys(value, [
      "schema_configured",
      "sourced_denominator_registration",
      "supported_declaration_method",
      "supported_scale_descriptions",
      "executable_aggregation",
      "score_input_integration",
      "formal_eligibility",
      "paid_execution_enabled",
    ]) ||
    typeof value.schema_configured !== "boolean" ||
    value.sourced_denominator_registration !== value.schema_configured ||
    value.supported_declaration_method !==
      "explicit-whole-technical-total-and-scale/1" ||
    !Array.isArray(value.supported_scale_descriptions) ||
    !value.supported_scale_descriptions.every((entry) => text(entry, 10000)) ||
    value.executable_aggregation !== false ||
    value.score_input_integration !== false ||
    value.formal_eligibility !== "unavailable" ||
    value.paid_execution_enabled !== false
  )
    invalid();
  return value.schema_configured;
}

export function technicalScales(
  value: unknown,
  bidId: string,
): TechnicalScaleChoice[] {
  if (
    !object(value) ||
    !exactKeys(value, ["items", "limit", "formal_eligibility"]) ||
    value.limit !== 200 ||
    value.formal_eligibility !== "unavailable" ||
    !Array.isArray(value.items) ||
    value.items.length > 200 ||
    new Set(value.items.map((item) => item?.id)).size !== value.items.length
  )
    invalid();
  return value.items.map((item) => {
    if (
      !object(item) ||
      !uuid(item.id) ||
      item.bid_id !== bidId ||
      !["current_prebid", "historical_backtest"].includes(
        String(item.purpose),
      ) ||
      (item.purpose === "current_prebid"
        ? item.submission_id !== null
        : !uuid(item.submission_id)) ||
      outcomeInstant(item.created_at) === null ||
      ![
        "pending",
        "confirmed",
        "withdrawn",
        "superseded",
        "needs_revalidation",
      ].includes(String(item.state)) ||
      !text(item.scale_description, 10000, true) ||
      item.formal_eligibility !== "unavailable" ||
      item.paid_execution_enabled !== false ||
      item.aggregation_usable !== false
    )
      invalid();
    // The catalogue supplies choices only. It cannot grant a maximum or readiness.
    return {
      id: item.id as string,
      purpose: item.purpose as TechnicalScaleChoice["purpose"],
      submission_id: item.submission_id as string | null,
      created_at: item.created_at as string,
      state: item.state as string,
      scale_description: item.scale_description as string,
    };
  });
}
