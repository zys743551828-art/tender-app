import type {
  PackageTechnicalScoringContext,
  PackageTechnicalSampleContext,
  PackageTechnicalScopeView,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId as uuid,
  executionSha as sha,
  recordObject as object,
} from "./executionInputValidation";
import { outcomeInstant } from "./packageOutcomeProtocol";
import {
  technicalFlags,
  technicalSame as same,
  technicalText as text,
} from "./packageTechnicalScopeProtocol";

export type TechnicalEligibilitySelection = {
  purpose: "current_prebid" | "historical_backtest";
  scaleId: string | null;
  submissionId?: string;
  outcomeId?: string | null;
};
export type TechnicalEligibility =
  | PackageTechnicalScoringContext
  | PackageTechnicalSampleContext;
function fail(): never {
  throw new Error(
    "评分条件与原技术范围、选择或证据不一致，未显示其他版本的资格或分值。",
  );
}
const date = (v: unknown) => outcomeInstant(v) !== null;
const decimal = (v: unknown): v is string =>
  typeof v === "string" &&
  v.length <= 64 &&
  /^(0|[1-9][0-9]*)(\.[0-9]+)?$/.test(v) &&
  Number(v) <= 1_000_000_000;
const gaps = (
  v: unknown,
): v is Array<{
  id: string;
  code: string;
  subject: string | null;
  message: string;
}> =>
  Array.isArray(v) &&
  v.length <= 20000 &&
  new Set(v.map((g) => g?.id)).size === v.length &&
  v.every(
    (g) =>
      object(g) &&
      exactKeys(g, ["id", "code", "subject", "message"]) &&
      text(g.id, 1000) &&
      text(g.code, 200) &&
      (g.subject === null || text(g.subject, 1000)) &&
      text(g.message, 10000),
  );
const judgments = {
  required_valid_independent: 3,
  recorded_valid_independent: 0,
  producer_authority: "not_configured_for_exact_package",
  previous_answers_in_input: false,
  retries_count_as_independent: false,
  unknown_send_auto_retry: false,
  execution_enabled: false,
};

export async function validateTechnicalEligibility(
  value: unknown,
  tag: string | null,
  saved: PackageTechnicalScopeView,
  selection: TechnicalEligibilitySelection,
): Promise<TechnicalEligibility> {
  const p = saved.manifest.preview.manifest;
  if (
    !object(value) ||
    new TextEncoder().encode(JSON.stringify(value)).length > 32 * 1024 * 1024 ||
    !same(value.scope, {
      ...p.scope,
      scope_id: saved.manifest.id,
      scope_digest: saved.digest,
    }) ||
    !same(value.basis, p.basis) ||
    !same(value.coverage, p.coverage) ||
    !date(value.observed_at) ||
    value.purpose !== selection.purpose ||
    !technicalFlags.every((key) => value[key] === false) ||
    value.numeric_prediction !== null ||
    !same(value.judgments, judgments) ||
    !gaps(value.blockers) ||
    !value.blockers.length ||
    !object(value.denominator)
  )
    fail();
  const d = value.denominator;
  if (
    !exactKeys(d, [
      "state",
      "scale_id",
      "scale_digest",
      "purpose",
      "technical_maximum",
      "scale_description",
      "aggregation",
      "maximum_usable",
      "aggregation_usable",
      "evidence_refs",
      "reasons",
    ]) ||
    ![
      "unselected",
      "not_configured",
      "unavailable",
      "mismatched",
      "matched",
    ].includes(String(d.state)) ||
    d.scale_id !== selection.scaleId ||
    (d.scale_id !== null && !uuid(d.scale_id)) ||
    (d.scale_digest !== null && !sha(d.scale_digest)) ||
    d.purpose !== selection.purpose ||
    d.aggregation_usable !== false ||
    typeof d.maximum_usable !== "boolean" ||
    !gaps(d.reasons) ||
    !d.reasons.length ||
    !Array.isArray(d.evidence_refs) ||
    d.evidence_refs.length > 1000 ||
    (d.state === "unselected") !== (selection.scaleId === null)
  )
    fail();
  if (d.state !== "matched") {
    if (
      d.maximum_usable !== false ||
      d.technical_maximum !== null ||
      d.scale_description !== null ||
      d.aggregation !== null ||
      d.evidence_refs.length
    )
      fail();
  } else {
    if (
      !d.maximum_usable ||
      !decimal(d.technical_maximum) ||
      Number(d.technical_maximum) <= 0 ||
      !sha(d.scale_digest) ||
      !text(d.scale_description, 10000) ||
      !object(d.aggregation) ||
      !exactKeys(d.aggregation, ["status", "description"]) ||
      !["unknown", "unsupported"].includes(String(d.aggregation.status)) ||
      !text(d.aggregation.description, 10000, true) ||
      !d.evidence_refs.length ||
      new Set(d.evidence_refs.map((r) => r?.id)).size !== d.evidence_refs.length
    )
      fail();
    let wholeMaximum = false;
    for (const ref of d.evidence_refs) {
      if (
        !object(ref) ||
        !exactKeys(ref, [
          "id",
          "document_version_id",
          "parse_id",
          "evidence_id",
          "source_id",
          "blob_digest",
          "evidence_digest",
          "physical_page",
          "source_revision",
          "quote",
          "supported_fields",
        ]) ||
        ![
          ref.id,
          ref.document_version_id,
          ref.parse_id,
          ref.evidence_id,
          ref.source_id,
        ].every(uuid) ||
        !sha(ref.blob_digest) ||
        !sha(ref.evidence_digest) ||
        !Number.isSafeInteger(ref.physical_page) ||
        Number(ref.physical_page) < 1 ||
        !Number.isSafeInteger(ref.source_revision) ||
        Number(ref.source_revision) < 1 ||
        !text(ref.quote, 2 * 1024 * 1024) ||
        !Array.isArray(ref.supported_fields) ||
        !ref.supported_fields.length ||
        !ref.supported_fields.every((s) =>
          ["technical_maximum", "scale_description", "aggregation"].includes(
            String(s),
          ),
        )
      )
        fail();
      const document = p.documents.find(
        (entry) =>
          entry.package_role === "authority" &&
          entry.document_version_id === ref.document_version_id,
      );
      const block = document?.blocks.find(
        (entry) => entry.id === ref.evidence_id,
      );
      const source = p.source_snapshot.find(
        (entry) =>
          entry.source_id === ref.source_id &&
          entry.ancestor_id === ref.source_id,
      );
      if (
        !document ||
        document.parse.status !== "frozen" ||
        document.parse.parse_run_id !== ref.parse_id ||
        document.file_digest !== ref.blob_digest ||
        !block ||
        block.physical_page !== ref.physical_page ||
        block.digest !== ref.evidence_digest ||
        block.text_content !== ref.quote ||
        !source ||
        source.revision !== ref.source_revision ||
        source.document_version_id !== ref.document_version_id ||
        source.digest !== ref.blob_digest
      )
        fail();
      wholeMaximum ||=
        ref.supported_fields.includes("technical_maximum") &&
        ref.supported_fields.includes("scale_description");
    }
    if (!wholeMaximum) fail();
  }
  const common = [
    "version",
    "purpose",
    "scope",
    "basis",
    "observed_at",
    "coverage",
    "denominator",
    "judgments",
    "numeric_prediction",
    "blockers",
    "official_label_access",
    ...technicalFlags,
  ];
  if (selection.purpose === "current_prebid") {
    if (
      !exactKeys(value, [...common, "current_input"]) ||
      value.version !== "package-technical-scoring-context/1" ||
      value.official_label_access !== "forbidden" ||
      !object(value.current_input)
    )
      fail();
    const c = value.current_input;
    if (
      !exactKeys(c, [
        "state",
        "stored_context_digest",
        "current_context_digest",
        "method_matches",
        "original_bytes_reverified",
        "reasons",
      ]) ||
      !["matched", "changed", "unavailable"].includes(String(c.state)) ||
      c.stored_context_digest !== p.context_digest ||
      (c.current_context_digest !== null && !sha(c.current_context_digest)) ||
      typeof c.method_matches !== "boolean" ||
      c.original_bytes_reverified !== false ||
      !gaps(c.reasons) ||
      (c.state === "matched" &&
        (c.current_context_digest !== p.context_digest ||
          !c.method_matches ||
          c.reasons.length)) ||
      (c.state === "unavailable" && c.current_context_digest !== null) ||
      (c.state !== "matched" && !c.reasons.length)
    )
      fail();
  } else {
    if (
      !exactKeys(value, [
        ...common,
        "submission",
        "official_result",
        "timing",
        "original_scope_precedes_submission",
        "source_metadata_matches",
        "sample_state",
        "sample_created",
      ]) ||
      value.version !== "package-technical-sample-context/1" ||
      value.sample_state !== "pending" ||
      value.sample_created !== false ||
      value.official_label_access !== "association_check_only" ||
      !object(value.submission) ||
      !object(value.official_result) ||
      !object(value.timing)
    )
      fail();
    const s = value.submission,
      o = value.official_result,
      t = value.timing;
    if (
      !exactKeys(s, [
        "id",
        "binding_digest",
        "submitted_at",
        "recorded_at",
        "is_current_head",
        "matches_scope",
        "platform_submission_verified",
      ]) ||
      s.id !== selection.submissionId ||
      !uuid(s.id) ||
      !sha(s.binding_digest) ||
      !date(s.submitted_at) ||
      !date(s.recorded_at) ||
      typeof s.is_current_head !== "boolean" ||
      typeof s.matches_scope !== "boolean" ||
      s.platform_submission_verified !== false ||
      !exactKeys(o, [
        "outcome_id",
        "score_kind",
        "technical_value",
        "reported_maximum",
        "label_known_at",
        "current_association",
        "reasons",
      ]) ||
      o.outcome_id !== (selection.outcomeId ?? null) ||
      (o.outcome_id !== null && !uuid(o.outcome_id)) ||
      ![null, "technical_total", "comprehensive_total", "unknown"].includes(
        o.score_kind as string | null,
      ) ||
      (o.technical_value !== null && !decimal(o.technical_value)) ||
      (o.reported_maximum !== null && !decimal(o.reported_maximum)) ||
      (o.label_known_at !== null && !date(o.label_known_at)) ||
      typeof o.current_association !== "boolean" ||
      !gaps(o.reasons) ||
      (o.score_kind !== "technical_total" &&
        (o.technical_value !== null || o.reported_maximum !== null)) ||
      (o.outcome_id === null &&
        (o.score_kind !== null ||
          o.label_known_at !== null ||
          o.current_association)) ||
      !exactKeys(t, [
        "scope_frozen_at",
        "historical_as_of",
        "submitted_at",
        "label_known_at",
        "training_frozen_at",
        "submission_split_at",
        "label_available_as_of",
        "strict_timing_ready",
      ]) ||
      outcomeInstant(t.scope_frozen_at) !==
        outcomeInstant(saved.manifest.frozen_at) ||
      outcomeInstant(t.submitted_at) !== outcomeInstant(s.submitted_at) ||
      outcomeInstant(t.historical_as_of) !== outcomeInstant(s.submitted_at) ||
      t.label_known_at !== o.label_known_at ||
      t.training_frozen_at !== null ||
      t.submission_split_at !== null ||
      t.label_available_as_of !== null ||
      t.strict_timing_ready !== false ||
      typeof value.source_metadata_matches !== "boolean" ||
      value.original_scope_precedes_submission !==
        outcomeInstant(saved.manifest.frozen_at)! <=
          outcomeInstant(s.submitted_at)!
    )
      fail();
  }
  const stable = Object.fromEntries(
    Object.entries(value).filter(([key]) => key !== "observed_at"),
  );
  if (
    tag !==
    `"package-technical-eligibility:${saved.manifest.id}:${await jsonDigest(stable)}"`
  )
    fail();
  return value as unknown as TechnicalEligibility;
}
