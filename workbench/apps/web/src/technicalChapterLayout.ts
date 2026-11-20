import { api } from "./api";
import type { TechnicalChapterLayoutView } from "./contracts";
import { exactKeys, recordObject } from "./executionInputValidation";
import {
  authoringInteger,
  type FixedAuthoringChapter,
} from "./packageAuthoringInputProtocol";

const states = [
  "plain_draft",
  "structured_layout_rechecked",
  "layout_review_required",
  "layout_basis_changed",
  "structure_not_supported",
] as const;

const unsupportedReasons = [
  "saved_chapter_plans",
  "bound_project_format",
  "word_import_sources",
] as const;

const planStates = [
  "none",
  "requires_fixed_evidence",
  "not_configured",
  "target_stale",
] as const;

export async function readTechnicalChapterLayout(
  bidId: string,
  target: FixedAuthoringChapter,
) {
  const { data } = await api<unknown>(
    `/bids/${bidId}/drafts/${target.draft_id}/sections/${target.section_id}/technical-authoring-layout`,
  );
  if (
    !recordObject(data) ||
    !exactKeys(data, [
      "bid_id",
      "draft_id",
      "section_id",
      "snapshot_id",
      "draft_revision",
      "section_revision",
      "state",
      "unsupported_reasons",
      "plan_state",
      "section_plan_revision",
      "ordinary_structure_protected",
    ]) ||
    data.bid_id !== bidId ||
    data.draft_id !== target.draft_id ||
    data.section_id !== target.section_id ||
    data.snapshot_id !== target.snapshot_id ||
    data.draft_revision !== target.base_draft_revision ||
    data.section_revision !== target.base_section_revision ||
    !states.some((state) => state === data.state) ||
    !Array.isArray(data.unsupported_reasons) ||
    !data.unsupported_reasons.every((reason) =>
      unsupportedReasons.some((allowed) => reason === allowed),
    ) ||
    new Set(data.unsupported_reasons).size !==
      data.unsupported_reasons.length ||
    (data.state === "structure_not_supported") !==
      data.unsupported_reasons.length > 0 ||
    !planStates.some((state) => state === data.plan_state) ||
    (data.section_plan_revision !== null &&
      !authoringInteger(data.section_plan_revision)) ||
    (data.plan_state === "none" && data.section_plan_revision !== null) ||
    (data.plan_state === "target_stale" &&
      data.section_plan_revision === null) ||
    (data.plan_state === "not_configured" ||
      data.plan_state === "target_stale") !==
      data.unsupported_reasons.includes("saved_chapter_plans") ||
    (data.state === "plain_draft" && data.plan_state !== "none") ||
    typeof data.ordinary_structure_protected !== "boolean"
  )
    throw new Error(
      "本章保存版本已变化或版式结果无法核对，未打开固定编写表单。",
    );
  return data as TechnicalChapterLayoutView;
}
