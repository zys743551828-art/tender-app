import { createContext } from "react";
import type {
  BidPackageStoredView,
  PackageReviewHumanDecisionCurrent,
  PackageReviewRunView,
} from "./contracts";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";

type Receipt = {
  member_id: string;
  document_version_id: string;
  artifact_sha256: string;
  format: "docx" | "pdf";
  build_id: string;
  snapshot_id: string;
  snapshot_digest: string;
  parse_run_id: string | null;
};
type Handoff = {
  protocol: "technical-authoring-handoff/1";
  bid_id: string;
  package_id: string;
  revision_id: string;
  package_digest: string;
  revision_status: "head_at_read" | "historical";
  record: Receipt | null;
  independent_approval_available: false;
  publication_authorized: false;
};
export type TechnicalAuthoringFocus = Handoff & { record: Receipt };
export const TechnicalDraftContext =
  createContext<TechnicalAuthoringFocus | null>(null);

export function verifyTechnicalHandoff(
  value: unknown,
  packageView: BidPackageStoredView,
): Handoff | null {
  const manifest = packageView.manifest;
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "protocol",
      "bid_id",
      "package_id",
      "revision_id",
      "package_digest",
      "revision_status",
      "record",
      "independent_approval_available",
      "publication_authorized",
    ]) ||
    value.protocol !== "technical-authoring-handoff/1" ||
    value.bid_id !== manifest.scope.bid_id ||
    value.package_id !== manifest.package_id ||
    value.revision_id !== manifest.revision_id ||
    value.package_digest !== packageView.digest ||
    (value.revision_status !== "head_at_read" &&
      value.revision_status !== "historical") ||
    value.independent_approval_available !== false ||
    value.publication_authorized !== false
  )
    return null;
  const receipt = value.record;
  if (receipt !== null) {
    if (
      !recordObject(receipt) ||
      !exactKeys(receipt, [
        "member_id",
        "document_version_id",
        "artifact_sha256",
        "format",
        "build_id",
        "snapshot_id",
        "snapshot_digest",
        "parse_run_id",
      ]) ||
      typeof receipt.member_id !== "string" ||
      ![
        receipt.document_version_id,
        receipt.build_id,
        receipt.snapshot_id,
      ].every(executionId) ||
      ![receipt.artifact_sha256, receipt.snapshot_digest].every(executionSha) ||
      (receipt.format !== "docx" && receipt.format !== "pdf") ||
      (receipt.parse_run_id !== null && !executionId(receipt.parse_run_id)) ||
      manifest.members.filter(
        (member) =>
          member.member_id === receipt.member_id &&
          member.document_version_id === receipt.document_version_id &&
          member.file_digest === receipt.artifact_sha256 &&
          member.parse.parse_run_id === receipt.parse_run_id,
      ).length !== 1
    )
      return null;
  }
  return value as Handoff;
}

export function technicalDisposition(
  focus: TechnicalAuthoringFocus,
  run: PackageReviewRunView,
  reading: PackageReviewHumanDecisionCurrent | null,
) {
  const record = focus.record;
  const result = run.result?.manifest;
  if (
    !result ||
    run.operation.state !== "succeeded" ||
    result.scope.bid_id !== run.scope.bid_id ||
    result.scope.package_id !== run.scope.package_id ||
    result.scope.revision_id !== run.scope.revision_id ||
    result.scope.inventory_id !== run.scope.inventory_id ||
    result.run_id !== run.id ||
    !record.parse_run_id ||
    run.scope.bid_id !== focus.bid_id ||
    run.scope.package_id !== focus.package_id ||
    run.scope.revision_id !== focus.revision_id ||
    !result.submitted_documents.some(
      (member) =>
        member.package_role === "target" &&
        member.member_id === record.member_id &&
        member.document_version_id === record.document_version_id &&
        member.file_digest === record.artifact_sha256 &&
        member.parse_run_id === record.parse_run_id,
    )
  )
    return null;
  const rows = result.matrix.filter((row) =>
    row.inspected_ranges.some(
      (range) =>
        range.member_id === record.member_id &&
        range.document_version_id === record.document_version_id &&
        range.parse_run_id === record.parse_run_id,
    ),
  );
  if (
    !reading ||
    reading.scope.inventory_id !== run.scope.inventory_id ||
    reading.scope.bid_id !== focus.bid_id ||
    reading.scope.revision_id !== focus.revision_id ||
    reading.scope.package_id !== focus.package_id ||
    reading.run_id !== run.id ||
    reading.frozen_input_id !== run.frozen_input_id ||
    reading.execution_input_id !== run.execution_input_id ||
    reading.result_digest !== run.result?.digest ||
    reading.items.length !== result.matrix.length
  )
    return { scoped: rows.length, counts: null };
  const heads = new Map(
    reading.items.map((item) => [item.requirement_id, item.current?.state]),
  );
  if (
    heads.size !== result.matrix.length ||
    result.matrix.some((row) => !heads.has(row.requirement_id))
  )
    return { scoped: rows.length, counts: null };
  const counts = { confirmed: 0, rejected: 0, needs_review: 0, unrecorded: 0 };
  for (const row of rows)
    counts[heads.get(row.requirement_id) ?? "unrecorded"]++;
  return { scoped: rows.length, counts };
}
