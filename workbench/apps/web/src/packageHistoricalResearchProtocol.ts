import { ApiError } from "./api";
import type {
  PackageHistoricalAdmission,
  PackageHistoricalAdmissionContext,
  PackageHistoricalAdmissionView,
  PackageHistoricalCohort,
  PackageHistoricalCohortView,
  PackageHistoricalJob,
  PackageHistoricalJobView,
  PackageHistoricalProtocol,
  PackageHistoricalProtocolTemplate,
  PackageHistoryAdmissionDirectory,
  PackageHistoryAdmissionRequest,
  PackageHistoryCohortDirectory,
  PackageHistoryCohortRequest,
  PackageHistoryJobControl,
  PackageHistoryJobDirectory,
  PackageHistoryJobRequest,
  PackageHistoryProtocolDirectory,
  PackageHistoryProtocolRequest,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { contextTime } from "./workContextProtocol";
import { historySchemas } from "./packageHistoricalResearchSchemas";

export const historyBase = "/package-historical-research";
export type HistoryDirectoryKind =
  | "admissions"
  | "protocols"
  | "cohorts"
  | "jobs";
export type HistoryDirectoryFilters = {
  bid_id: string | null;
  scope_id: string | null;
  protocol_id: string | null;
  cohort_id: string | null;
};
export type HistoryDirectoryByKind = {
  admissions: PackageHistoryAdmissionDirectory;
  protocols: PackageHistoryProtocolDirectory;
  cohorts: PackageHistoryCohortDirectory;
  jobs: PackageHistoryJobDirectory;
};
type PendingBase = { path: string; key: string; etag: string | null };
export type HistoryPending = PendingBase &
  (
    | {
        kind: "admission";
        body: PackageHistoryAdmissionRequest;
        expected: {
          bidId: string;
          packageId: string;
          revisionId: string;
          scopeId: string;
          scopeDigest: string;
          submissionBindingDigest: string;
          proofOrigin: "synthetic" | "external_evidence";
        };
      }
    | {
        kind: "protocol";
        body: PackageHistoryProtocolRequest;
        expected: Record<string, never>;
      }
    | {
        kind: "cohort";
        body: PackageHistoryCohortRequest;
        expected: { protocolDigest: string };
      }
    | {
        kind: "job";
        body: PackageHistoryJobRequest;
        expected: { cohortId: string };
      }
    | {
        kind: "control";
        body: PackageHistoryJobControl;
        expected: { cohortId: string; jobKind: "train" | "evaluate" };
      }
  );
export type HistoryReceipt =
  | PackageHistoricalAdmission
  | PackageHistoricalProtocol
  | PackageHistoricalCohort
  | PackageHistoricalJob;
export type HistoryResult = NonNullable<PackageHistoricalJobView["result"]>;
type EvaluationResult = Extract<
  HistoryResult,
  { schema: "package-history-independent-evaluation/1" }
>;
type EvaluationReport = EvaluationResult["report"];

function fail(
  message = "历史研究记录的身份、完整内容或回执无法核对。原请求仍保留，请核对后恢复。 ",
): never {
  throw new Error(message);
}
function check(condition: unknown, message?: string): asserts condition {
  if (!condition) fail(message);
}
export function historySame(a: unknown, b: unknown): boolean {
  const ordered = (v: unknown): unknown =>
    Array.isArray(v)
      ? v.map(ordered)
      : recordObject(v)
        ? Object.fromEntries(
            Object.entries(v)
              .sort(([x], [y]) => (x < y ? -1 : x > y ? 1 : 0))
              .map(([k, x]) => [k, ordered(x)]),
          )
        : v;
  return JSON.stringify(ordered(a)) === JSON.stringify(ordered(b));
}

/** Interpret only the bounded JSON Schema vocabulary emitted by this actual API. */
function shape(
  value: unknown,
  schema: unknown,
  budget: { nodes: number },
  depth = 0,
): boolean {
  if (--budget.nodes < 0 || depth > 64 || !recordObject(schema)) return false;
  const child = (v: unknown, s: unknown) => shape(v, s, budget, depth + 1);
  if (typeof schema.$ref === "string") {
    if (!schema.$ref.startsWith("#/components/schemas/")) return false;
    return child(
      value,
      historySchemas[schema.$ref.slice("#/components/schemas/".length)],
    );
  }
  if ("const" in schema && !historySame(value, schema.const)) return false;
  if (
    Array.isArray(schema.enum) &&
    !schema.enum.some((v) => historySame(v, value))
  )
    return false;
  if (
    Array.isArray(schema.oneOf) &&
    schema.oneOf.filter((s) => child(value, s)).length !== 1
  )
    return false;
  if (Array.isArray(schema.anyOf) && !schema.anyOf.some((s) => child(value, s)))
    return false;
  if (schema.type === undefined) return true;
  if (Array.isArray(schema.type))
    return schema.type.some((t) => child(value, { ...schema, type: t }));
  if (schema.type === "null") return value === null;
  if (schema.type === "boolean") return typeof value === "boolean";
  if (schema.type === "string") {
    if (
      typeof value !== "string" ||
      value.length > 65536 ||
      /[\uD800-\uDFFF]/u.test(value) ||
      value.includes("\0")
    )
      return false;
    const length = Array.from(value).length;
    return (
      !(typeof schema.minLength === "number" && length < schema.minLength) &&
      !(typeof schema.maxLength === "number" && length > schema.maxLength) &&
      !(
        typeof schema.pattern === "string" &&
        !new RegExp(schema.pattern, "u").test(value)
      ) &&
      (schema.format !== "uuid" || executionId(value)) &&
      (schema.format !== "date-time" || contextTime(value))
    );
  }
  if (schema.type === "number" || schema.type === "integer") {
    return (
      typeof value === "number" &&
      Number.isFinite(value) &&
      (schema.type !== "integer" || Number.isSafeInteger(value)) &&
      !(typeof schema.minimum === "number" && value < schema.minimum) &&
      !(typeof schema.maximum === "number" && value > schema.maximum)
    );
  }
  if (schema.type === "array") {
    return (
      Array.isArray(value) &&
      !(
        typeof schema.minItems === "number" && value.length < schema.minItems
      ) &&
      !(
        typeof schema.maxItems === "number" && value.length > schema.maxItems
      ) &&
      (schema.items === undefined || value.every((v) => child(v, schema.items)))
    );
  }
  if (schema.type === "object") {
    if (!recordObject(value)) return false;
    const properties = recordObject(schema.properties) ? schema.properties : {};
    if (
      Array.isArray(schema.required) &&
      schema.required.some(
        (k) => typeof k !== "string" || !Object.hasOwn(value, k),
      )
    )
      return false;
    return Object.entries(value).every(([k, v]) =>
      Object.hasOwn(properties, k)
        ? child(v, properties[k])
        : schema.additionalProperties === false
          ? false
          : recordObject(schema.additionalProperties)
            ? child(v, schema.additionalProperties)
            : true,
    );
  }
  return false;
}
function structural<T>(name: string, value: unknown): T {
  check(shape(value, historySchemas[name], { nodes: 250000 }));
  return value as T;
}
function without(value: object, key: string) {
  return Object.fromEntries(Object.entries(value).filter(([k]) => k !== key));
}
async function ownDigest(value: { digest: string }) {
  check((await jsonDigest(without(value, "digest"))) === value.digest);
}
export async function historyEtag(kind: string, id: string, value: object) {
  check(executionId(id));
  return `"package-history-${kind}:${id}:${await jsonDigest(without(value, "observed_at"))}"`;
}
async function tag(
  kind: string,
  id: string,
  value: object,
  etag: string | null,
) {
  check(
    etag === (await historyEtag(kind, id, value)),
    "历史研究响应的条件标记与本次完整记录不一致，原请求仍保留。",
  );
}
const number = (v: string, min = 0, max = Number.MAX_VALUE) => {
  const n = Number(v);
  check(Number.isFinite(n) && n >= min && n <= max);
  return n;
};
const unique = (values: string[]) => new Set(values).size === values.length;
// Preserve microseconds when comparing PG timestamps; Date.parse alone drops them.
function instant(value: string) {
  check(contextTime(value));
  const fraction = value.match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/)?.[1] ?? "";
  return (
    BigInt(Date.parse(value)) * 1000n +
    BigInt(fraction.padEnd(6, "0").slice(3, 6))
  );
}
function originState(origin: string, state: string) {
  check(
    state ===
      (origin === "synthetic"
        ? "mechanism_candidate"
        : "retrospective_candidate"),
  );
}
async function protocolDocument(value: PackageHistoricalProtocol["document"]) {
  await ownDigest(value.method);
}
async function admissionDocument(value: PackageHistoricalAdmission) {
  await ownDigest(value);
  originState(value.origin, value.state);
  check(number(value.technical_maximum) > 0);
  check(
    number(value.official_technical_value) <= number(value.technical_maximum),
  );
  check(instant(value.historical_as_of) <= instant(value.label_known_at));
  check(instant(value.evidence_verified_at) <= instant(value.admitted_at));
}

export async function validateHistoryDirectory<K extends HistoryDirectoryKind>(
  kind: K,
  raw: unknown,
  filters: HistoryDirectoryFilters,
): Promise<HistoryDirectoryByKind[K]> {
  const names = {
    admissions: "PackageHistoryAdmissionDirectory",
    protocols: "PackageHistoryProtocolDirectory",
    cohorts: "PackageHistoryCohortDirectory",
    jobs: "PackageHistoryJobDirectory",
  };
  check(Object.hasOwn(names, kind));
  const value = structural<HistoryDirectoryByKind[K]>(names[kind], raw);
  check(historySame(value.filters, filters) && value.kind === kind);
  if (value.status === "unavailable") return value;
  check(value.has_more === (value.next_cursor !== null));
  check(
    unique(value.items.map((item) => item.id)) &&
      value.total >= value.items.length,
  );
  check(
    !value.has_more ||
      (value.items.length > 0 && value.total > value.items.length),
  );
  for (const item of value.items) {
    if (item.kind === "admission") {
      originState(item.origin, item.state);
      check(
        (filters.bid_id === null || filters.bid_id === item.bid_id) &&
          (filters.scope_id === null || filters.scope_id === item.scope_id),
      );
    } else if (item.kind === "protocol") {
      await protocolDocument(item.document);
      check((await jsonDigest(item.document)) === item.digest);
    } else if (item.kind === "cohort") {
      check(
        filters.protocol_id === null ||
          filters.protocol_id === item.protocol_id,
      );
    } else if (item.kind === "job") {
      check(item.cohort_id === filters.cohort_id);
      check(item.result_available === (item.result_digest !== null));
      check(item.result_available === (item.state === "succeeded"));
    }
  }
  return value;
}

export async function validateHistoryAdmissionContext(
  raw: unknown,
  expected: { scopeId: string; submissionId: string; outcomeId: string },
  etag: string | null,
): Promise<PackageHistoricalAdmissionContext> {
  const value = structural<PackageHistoricalAdmissionContext>(
    "PackageHistoricalAdmissionContext",
    raw,
  );
  check(
    value.scope_id === expected.scopeId &&
      value.submission_id === expected.submissionId &&
      value.outcome_id === expected.outcomeId,
  );
  check(unique(value.proofs.map((p) => p.id)));
  check(value.proofs.every((p) => p.context_digest === value.context_digest));
  if (!value.schema_configured)
    check(
      value.context_digest === null &&
        value.proofs.length === 0 &&
        value.blockers.length > 0,
    );
  // A native context digest exists only after the exact source, submission and
  // official label have been checked. Nullable fields describe an unavailable
  // context; they cannot erase evidence from an otherwise proved context.
  if (value.context_digest !== null)
    check(
      value.historical_as_of !== null &&
        value.scope_frozen_at !== null &&
        value.label_known_at !== null &&
        value.official_technical_value !== null &&
        value.official_maximum !== null,
    );
  if (value.official_technical_value !== null)
    number(value.official_technical_value);
  if (value.official_maximum !== null)
    check(number(value.official_maximum) > 0);
  if (
    value.official_technical_value !== null &&
    value.official_maximum !== null
  )
    check(
      number(value.official_technical_value) <= number(value.official_maximum),
    );
  await tag("context", expected.scopeId, value, etag);
  return value;
}
export async function validateHistoryAdmission(
  raw: unknown,
  id: string,
  etag: string | null,
): Promise<PackageHistoricalAdmissionView> {
  const value = structural<PackageHistoricalAdmissionView>(
    "PackageHistoricalAdmissionView",
    raw,
  );
  check(value.admission.id === id);
  await admissionDocument(value.admission);
  await tag("admission-view", id, value, etag);
  return value;
}
export async function validateHistoryTemplate(
  raw: unknown,
  etag: string | null,
): Promise<PackageHistoricalProtocolTemplate> {
  const value = structural<PackageHistoricalProtocolTemplate>(
    "PackageHistoricalProtocolTemplate",
    raw,
  );
  check(value.method_digest === value.document.method.digest);
  await protocolDocument(value.document);
  await tag(
    "protocol-template",
    "00000000-0000-0000-0000-000000000000",
    value,
    etag,
  );
  return value;
}
async function cohortDocument(value: PackageHistoricalCohort) {
  await ownDigest(value);
  check((await jsonDigest(value.members)) === value.membership_digest);
  check(
    unique(value.members.map((m) => m.admission_id)) &&
      unique(value.members.map((m) => m.submission_id)),
  );
  const split = instant(value.timing.submission_split_at),
    cutoff = instant(value.timing.label_available_as_of),
    frozen = instant(value.timing.training_frozen_at);
  check(split <= frozen && cutoff <= frozen);
  const groups = new Map<string, string>();
  for (const item of value.members) {
    check(
      unique(item.closure_ids) &&
        item.closure_ids.includes(item.admission_id) &&
        item.closure_ids.includes(item.group_id),
    );
    check(instant(item.submitted_at) <= instant(item.label_known_at));
    if (item.purpose === "excluded") {
      check(item.exclusion_reason !== null);
    } else {
      check(
        item.exclusion_reason === null &&
          item.purpose === item.requested_purpose,
      );
      check(instant(item.label_known_at) <= cutoff);
      check(
        item.purpose === "final"
          ? instant(item.submitted_at) >= split
          : instant(item.submitted_at) < split,
      );
      check(
        !groups.has(item.group_id) ||
          groups.get(item.group_id) === item.purpose,
      );
      groups.set(item.group_id, item.purpose);
    }
  }
}
export async function validateHistoryCohort(
  raw: unknown,
  id: string,
  etag: string | null,
  expectedProtocolDigest?: string,
): Promise<PackageHistoricalCohortView> {
  const value = structural<PackageHistoricalCohortView>(
    "PackageHistoricalCohortView",
    raw,
  );
  check(
    value.cohort.id === id &&
      (expectedProtocolDigest === undefined ||
        value.cohort.protocol_digest === expectedProtocolDigest),
  );
  await cohortDocument(value.cohort);
  await tag("cohort-view", id, value, etag);
  return value;
}
function report(value: EvaluationReport) {
  const succeeded = value.counts.succeeded;
  check(
    Object.values(value.counts).reduce((a, b) => a + b, 0) ===
      value.denominator,
  );
  check(value.independent_groups <= succeeded && value.projects <= succeeded);
  if (value.denominator === 0) check(value.success_coverage === null);
  else
    check(
      value.success_coverage !== null &&
        Math.abs(
          number(value.success_coverage, 0, 1) - succeeded / value.denominator,
        ) < 1e-12,
    );
  const statistics = [
    value.sample_mae,
    value.project_mae,
    value.original_scale_project_mae,
    value.p90_absolute_error,
    value.project_bias,
    value.project_within_three,
  ];
  if (succeeded === 0)
    check(
      statistics.every((v) => v === null) &&
        value.independent_groups === 0 &&
        value.projects === 0,
    );
  else {
    check(
      statistics.every((v) => v !== null) &&
        value.independent_groups > 0 &&
        value.projects > 0,
    );
    number(value.sample_mae!, 0, 100);
    number(value.project_mae!, 0, 100);
    number(value.original_scale_project_mae!);
    number(value.p90_absolute_error!, 0, 100);
    number(value.project_bias!, -100, 100);
    number(value.project_within_three!, 0, 1);
  }
  for (const interval of Object.values(value.intervals)) {
    if (interval.coverage !== null) {
      number(interval.coverage, 0, 1);
      number(interval.width, 0, 100);
      check(succeeded > 0);
    }
  }
  const bounds = value.group_bootstrap_project_mae_95;
  if (bounds)
    check(
      number(bounds[0], 0, 100) <= number(bounds[1], 0, 100) &&
        value.independent_groups >= 2,
    );
  for (const baseline of Object.values(value.paired_baselines)) {
    if (baseline.gain !== null) {
      number(baseline.gain, -100, 100);
      check(baseline.paired_count === succeeded && succeeded > 0);
      const interval = baseline.group_bootstrap_gain_95;
      if (interval)
        check(
          number(interval[0], -100, 100) <= number(interval[1], -100, 100) &&
            value.independent_groups >= 2,
        );
    }
  }
  for (const stratum of Object.values(value.strata)) {
    check(
      Object.values(stratum).reduce((n, row) => n + row.count, 0) === succeeded,
    );
    for (const row of Object.values(stratum))
      check(
        row.count > 0 &&
          row.project_mae !== null &&
          number(row.project_mae, 0, 100) >= 0,
      );
  }
}
async function resultDocument(value: HistoryResult) {
  if (value.schema === "package-history-training-result/1") {
    if (value.complete_material_consumer) {
      const rows = value.complete_material_consumer.receipts;
      check(
        unique(rows.map((r) => r.admission_id)) &&
          unique(rows.map((r) => r.input_digest)),
      );
    }
    const candidate = value.complete_feature_training;
    if (candidate) {
      check(
        !!value.complete_material_consumer &&
          candidate.source_digest ===
            value.complete_material_consumer?.reference_digest &&
          candidate.origin === value.origin &&
          candidate.membership_digest === value.membership_digest,
      );
      check(
        candidate.groups.fit +
          candidate.groups.development +
          candidate.groups.calibration <=
          (value.complete_material_consumer?.receipts.length ?? 0),
      );
      if (candidate.status === "research_candidate") {
        check(
          candidate.groups.fit >= 3 &&
            candidate.groups.development >= 2 &&
            candidate.groups.calibration >= 9,
        );
        check(
          (await jsonDigest(candidate.model)) === candidate.model_digest &&
            candidate.model.method_digest === candidate.method_digest &&
            candidate.model.alpha === candidate.selection.selected_alpha,
        );
        candidate.model.means.forEach((v) => number(v, 0, 1));
        candidate.model.scales.forEach((v) => number(v, 1e-12, 1));
        candidate.model.coefficients.forEach((v) => number(v, -1e9, 1e9));
        number(candidate.model.intercept, 0, 100);
        const alphas = ["10", "1", "0.1"] as const;
        const losses = candidate.selection.development_project_mae;
        alphas.forEach((a) => number(losses[a], 0, 100));
        const selected = alphas.reduce((best, a) =>
          Number(losses[a]) < Number(losses[best]) ? a : best,
        );
        check(selected === candidate.selection.selected_alpha);
        for (const [level, interval] of Object.entries(candidate.intervals)) {
          check(
            interval.groups === candidate.groups.calibration &&
              interval.rank ===
                Math.ceil((interval.groups + 1) * Number(level)) &&
              interval.rank <= interval.groups,
          );
          number(interval.radius, 0, 100);
        }
      }
    }
    check((await jsonDigest(value.model)) === value.model_digest);
    check(
      value.model.training_export_digest === value.training_export_digest &&
        value.selection.selected === value.model.family,
    );
    check(
      number(value.model.constant, 0, 100) ===
        number(value.baselines[value.model.family], 0, 100),
    );
    const loss = value.selection.development_project_mae;
    check(
      value.selection.selected ===
        (number(loss.mean, 0, 100) <= number(loss.median, 0, 100)
          ? "mean"
          : "median"),
    );
    for (const [level, interval] of Object.entries(value.intervals)) {
      check(interval.rank === Math.ceil((interval.groups + 1) * Number(level)));
      const available = interval.groups > 0 && interval.rank <= interval.groups;
      check(
        available === (interval.radius !== null) &&
          available === (interval.unavailable_reason === null),
      );
      if (interval.radius !== null) number(interval.radius, 0, 100);
    }
  } else {
    if (value.feature_final_evaluation) {
      const feature = value.feature_final_evaluation;
      check(
        feature.cohort_id === value.cohort_id &&
          feature.origin === value.origin &&
          feature.membership_digest === value.membership_digest &&
          feature.labels_digest === value.labels_digest,
      );
      report(feature.report);
      check(
        feature.report.denominator === value.report.denominator &&
          feature.report.counts.rejected === value.report.counts.rejected &&
          feature.report.counts.unlabeled === value.report.counts.unlabeled &&
          feature.report.counts.succeeded + feature.report.counts.failed ===
            value.report.counts.succeeded + value.report.counts.failed,
      );
    }
    report(value.report);
    report(value.official_source_subset.report);
    check(value.official_source_subset.origin === value.origin);
    check(
      value.official_source_subset.report.denominator <=
        value.report.denominator,
    );
    const count = value.selection_denominator;
    check(
      count.selected_submissions >= count.excluded_submissions &&
        count.selected_submissions >= count.final_side_candidates &&
        count.final_side_candidates === value.report.denominator,
    );
  }
}
export async function validateHistoryJob(
  raw: unknown,
  id: string,
  etag: string | null,
  expectedCohort?: PackageHistoricalCohort,
): Promise<PackageHistoricalJobView> {
  const value = structural<PackageHistoricalJobView>(
    "PackageHistoricalJobView",
    raw,
  );
  check(value.job_id === id);
  check(
    (value.result !== null) === (value.result_digest !== null) &&
      (value.result !== null) === (value.state === "succeeded"),
  );
  if (expectedCohort) check(value.cohort_id === expectedCohort.id);
  if (value.result !== null) {
    check(
      value.result.cohort_id === value.cohort_id &&
        (await jsonDigest(value.result)) === value.result_digest,
    );
    check(
      (value.kind === "train") ===
        (value.result.schema === "package-history-training-result/1"),
    );
    if (expectedCohort) {
      check(
        value.result.protocol_digest === expectedCohort.protocol_digest &&
          value.result.membership_digest === expectedCohort.membership_digest &&
          value.result.origin === expectedCohort.origin,
      );
      if (
        value.result.schema === "package-history-training-result/1" &&
        value.result.complete_material_consumer
      ) {
        const rows = value.result.complete_material_consumer.receipts;
        const members = expectedCohort.members.filter((m) =>
          ["fit", "development", "calibration"].includes(m.purpose),
        );
        check(
          rows.length === members.length &&
            rows.every((r) =>
              members.some(
                (m) =>
                  m.admission_id === r.admission_id &&
                  m.proof_id === r.proof_id,
              ),
            ),
        );
      }
      if (
        value.result.schema === "package-history-training-result/1" &&
        value.result.complete_feature_training
      ) {
        const candidate = value.result.complete_feature_training;
        for (const purpose of ["fit", "development", "calibration"] as const) {
          check(
            candidate.groups[purpose] ===
              new Set(
                expectedCohort.members
                  .filter((m) => m.purpose === purpose)
                  .map((m) => m.group_id),
              ).size,
          );
        }
      }
      if (value.result.schema === "package-history-independent-evaluation/1") {
        check(historySame(value.result.timing, expectedCohort.timing));
        const members = expectedCohort.members;
        const finalSide = members.filter(
          (m) =>
            instant(m.submitted_at) >=
            instant(expectedCohort.timing.submission_split_at),
        );
        check(
          value.result.selection_denominator.selected_submissions ===
            members.length,
        );
        check(
          value.result.selection_denominator.excluded_submissions ===
            members.filter((m) => m.purpose === "excluded").length,
        );
        check(
          value.result.selection_denominator.final_side_candidates ===
            finalSide.length,
        );
        check(
          value.result.report.counts.succeeded +
            value.result.report.counts.failed ===
            finalSide.filter((m) => m.purpose === "final").length,
        );
        check(
          value.result.report.counts.unlabeled ===
            finalSide.filter(
              (m) =>
                m.purpose === "excluded" &&
                m.exclusion_reason === "label_after_available_cutoff",
            ).length,
        );
        check(
          value.result.report.counts.rejected ===
            finalSide.filter(
              (m) =>
                m.purpose === "excluded" &&
                m.exclusion_reason !== "label_after_available_cutoff",
            ).length,
        );
      }
    }
    await resultDocument(value.result);
  }
  await tag("job-view", id, value, etag);
  return value;
}

function conditional(value: unknown, kind: string, id: string) {
  check(
    typeof value === "string" &&
      value.startsWith(`"package-history-${kind}:${id}:`) &&
      /^"[^"\r\n]+:[a-f0-9]{64}"$/.test(value),
  );
}
export function validateHistoryPending(raw: unknown): HistoryPending {
  check(
    recordObject(raw) &&
      exactKeys(raw, ["kind", "path", "key", "body", "etag", "expected"]) &&
      executionId(raw.key) &&
      typeof raw.path === "string" &&
      recordObject(raw.expected),
  );
  const requestNames: Record<string, string> = {
    admission: "PackageHistoryAdmissionRequest",
    protocol: "PackageHistoryProtocolRequest",
    cohort: "PackageHistoryCohortRequest",
    job: "PackageHistoryJobRequest",
    control: "PackageHistoryJobControl",
  };
  check(typeof raw.kind === "string" && Object.hasOwn(requestNames, raw.kind));
  structural(requestNames[raw.kind], raw.body);
  check(
    recordObject(raw.body) &&
      typeof raw.body.reason === "string" &&
      !!raw.body.reason.trim(),
  );
  const value = raw as HistoryPending;
  if (value.kind === "admission") {
    const e = value.expected;
    check(
      exactKeys(e, [
        "bidId",
        "packageId",
        "revisionId",
        "scopeId",
        "scopeDigest",
        "submissionBindingDigest",
        "proofOrigin",
      ]),
    );
    check(
      [e.bidId, e.packageId, e.revisionId, e.scopeId].every(executionId) &&
        [e.scopeDigest, e.submissionBindingDigest].every(executionSha) &&
        ["synthetic", "external_evidence"].includes(e.proofOrigin),
    );
    check(
      value.path ===
        `/bids/${e.bidId}/packages/${e.packageId}/revisions/${e.revisionId}/technical-scopes/${e.scopeId}/historical-admissions`,
    );
    conditional(value.etag, "context", e.scopeId);
  } else if (value.kind === "protocol") {
    check(
      exactKeys(value.expected, []) &&
        value.path === historyBase + "/protocols" &&
        value.etag === null,
    );
  } else if (value.kind === "cohort") {
    check(
      exactKeys(value.expected, ["protocolDigest"]) &&
        executionSha(value.expected.protocolDigest) &&
        value.path === historyBase + "/cohorts" &&
        value.etag === null,
    );
    check(unique(value.body.selections.map((s) => s.admission_id)));
  } else if (value.kind === "job") {
    check(
      exactKeys(value.expected, ["cohortId"]) &&
        executionId(value.expected.cohortId) &&
        value.path === `${historyBase}/cohorts/${value.expected.cohortId}/jobs`,
    );
    conditional(value.etag, "cohort-view", value.expected.cohortId);
  } else {
    check(
      exactKeys(value.expected, ["cohortId", "jobKind"]) &&
        executionId(value.expected.cohortId) &&
        ["train", "evaluate"].includes(value.expected.jobKind),
    );
    const id = value.path.slice(
      `${historyBase}/jobs/`.length,
      -"/control".length,
    );
    check(
      executionId(id) && value.path === `${historyBase}/jobs/${id}/control`,
    );
    conditional(value.etag, "job-view", id);
  }
  return value;
}
export const historyPendingPath = (pending: HistoryPending) =>
  validateHistoryPending(pending).path;
export async function validateHistoryReceipt(
  raw: unknown,
  pending: HistoryPending,
  etag: string | null,
): Promise<HistoryReceipt> {
  validateHistoryPending(pending);
  if (pending.kind === "admission") {
    const value = structural<PackageHistoricalAdmission>(
        "PackageHistoricalAdmission",
        raw,
      ),
      e = pending.expected,
      b = pending.body;
    check(
      value.bid_id === e.bidId &&
        value.scope_id === e.scopeId &&
        value.scope_digest === e.scopeDigest &&
        value.submission_binding_digest === e.submissionBindingDigest &&
        value.origin === e.proofOrigin,
    );
    check(
      value.submission_id === b.submission_id &&
        value.outcome_id === b.outcome_id &&
        value.proof_id === b.proof_id &&
        value.context_digest === b.context_digest,
    );
    await admissionDocument(value);
    await tag("admission", value.id, value, etag);
    return value;
  }
  if (pending.kind === "protocol") {
    const value = structural<PackageHistoricalProtocol>(
        "PackageHistoricalProtocol",
        raw,
      ),
      b = pending.body;
    await protocolDocument(value.document);
    check(
      (await jsonDigest(value.document)) === value.digest &&
        value.document.method.digest === b.method_digest &&
        value.document.seed === b.seed &&
        value.document.bootstrap_iterations === b.bootstrap_iterations,
    );
    await tag("protocol", value.id, value, etag);
    return value;
  }
  if (pending.kind === "cohort") {
    const value = structural<PackageHistoricalCohort>(
        "PackageHistoricalCohort",
        raw,
      ),
      b = pending.body;
    check(
      value.protocol_id === b.protocol_id &&
        value.protocol_digest === pending.expected.protocolDigest &&
        instant(value.timing.submission_split_at) ===
          instant(b.submission_split_at) &&
        instant(value.timing.label_available_as_of) ===
          instant(b.label_available_as_of),
    );
    const selected = new Map(
      b.selections.map((s) => [s.admission_id, s.purpose]),
    );
    check(
      value.members.length === selected.size &&
        value.members.every(
          (m) => selected.get(m.admission_id) === m.requested_purpose,
        ),
    );
    await cohortDocument(value);
    await tag("cohort", value.id, value, etag);
    return value;
  }
  const value = structural<PackageHistoricalJob>("PackageHistoricalJob", raw);
  check(value.cohort_id === pending.expected.cohortId);
  if (pending.kind === "job") check(value.kind === pending.body.kind);
  else {
    check(
      value.job_id === pending.path.split("/").at(-2) &&
        value.kind === pending.expected.jobKind &&
        value.generation === pending.body.generation + 1,
    );
    check(
      value.state ===
        ({ pause: "paused", resume: "queued", cancel: "cancelled" } as const)[
          pending.body.action
        ],
    );
  }
  await tag("job", value.job_id, value, etag);
  return value;
}
export function definitiveHistoryFailure(error: unknown) {
  // Authentication/permission failures may occur before replay lookup. Keep the
  // original command so a later restored session can recover its immutable ACK.
  return (
    error instanceof ApiError &&
    !error.retryable &&
    !["IDEMPOTENCY_CONFLICT", "COMMAND_INCOMPLETE"].includes(error.code) &&
    [400, 404, 409, 412, 422, 428].includes(error.status)
  );
}
