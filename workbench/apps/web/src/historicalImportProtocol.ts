import { ApiError } from "./api";
import type {
  HistoricalImportBatch,
  HistoricalImportPage,
  HistoricalImportReceipt,
  HistoricalImportRecord,
  HistoricalImportRequest,
  HistoricalImportSource,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";

export const historicalImportLimit = 8 * 1024 * 1024;
export const historicalPreviewTarget = "59696bb3-834e-4768-80fb-5662402f6975";
export const historicalImportPath = (id: string) => `/research/imports/${id}`;
export const historicalImportEtag = (id: string, revision: number) =>
  `"historical-import:${id}:${revision}"`;
export type HistoricalPending =
  | { kind: "preview"; key: string; body: HistoricalImportRequest; etag: null }
  | {
      kind: "confirm";
      key: string;
      body: Record<string, never>;
      etag: string;
      batchId: string;
      baseRevision: number;
      manifestBlobId: string;
      manifestDigest: string;
    };

const recordKeys = [
  "external_record_id",
  "bid_id",
  "actual_document_version_id",
  "submitted_at",
  "evidence_ref",
  "explanation",
  "score_kind",
  "value",
  "maximum",
  "source_version_id",
  "known_at",
];
export const historicalSame = (a: unknown, b: unknown): boolean => {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b))
    return (
      a.length === b.length && a.every((item, i) => historicalSame(item, b[i]))
    );
  if (!recordObject(a) || !recordObject(b)) return false;
  return (
    exactKeys(a, Object.keys(b)) &&
    Object.keys(a).every((key) => historicalSame(a[key], b[key]))
  );
};
export function historicalFailure(
  message = "导入批次的身份、摘要或回执无法核对，请保留原操作。",
): never {
  throw new Error(message);
}
const integer = (v: unknown, min = 0, max = 100000): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const text = (v: unknown, max: number): v is string =>
  typeof v === "string" &&
  !!v.trim() &&
  Array.from(v).length <= max &&
  Array.from(v).every((c) => {
    const n = c.codePointAt(0)!;
    return (n >= 32 || [9, 10, 13].includes(n)) && (n < 0xd800 || n > 0xdfff);
  });
const nullableUuid = (v: unknown) => v === null || executionId(v);
const decimal = (v: unknown) =>
  v === null ||
  (typeof v === "string" && /^(0|[1-9][0-9]*)(\.[0-9]+)?$/.test(v));
function uuid(v: unknown, label: string) {
  if (typeof v !== "string" || !executionId(v.toLowerCase()))
    historicalFailure(`${label} 须为完整 UUID，不能用名称或最新版本代替。`);
  return v.toLowerCase();
}
/** Match Pydantic's JSON datetime spelling without going through Date (which loses microseconds). */
export function historicalDateTime(v: unknown, label = "时间") {
  if (typeof v !== "string")
    historicalFailure(`${label} 须为含时区的 ISO 时间。`);
  const m =
    /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?([Zz]|[+-]\d{2}:\d{2})$/.exec(
      v,
    );
  if (!m)
    historicalFailure(
      `${label} 须含秒和明确时区，最多保留六位小数；不会截断微秒。`,
    );
  const [year, month, day, hour, minute, second] = m.slice(1, 7).map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (
    year < 1 ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > days[month - 1] ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  )
    historicalFailure(`${label} 不是有效的日历时间。`);
  let zone = m[8].toUpperCase();
  if (zone !== "Z") {
    if (+zone.slice(1, 3) > 23 || +zone.slice(4, 6) > 59)
      historicalFailure(`${label} 的时区偏移无效。`);
    if (zone.slice(1) === "00:00") zone = "Z";
  }
  const fraction = (m[7] ?? "").padEnd(6, "0");
  return `${m.slice(1, 4).join("-")}T${m.slice(4, 7).join(":")}${/^0+$/.test(fraction) ? "" : `.${fraction}`}${zone}`;
}
export function normalizeHistoricalRequest(
  value: unknown,
): HistoricalImportRequest {
  if (
    !recordObject(value) ||
    !exactKeys(value, ["records"]) ||
    !Array.isArray(value.records) ||
    value.records.length < 1 ||
    value.records.length > 1000
  )
    historicalFailure(
      "清单必须仅含 records 数组，每批 1—1000 条；文件须为 JSON。",
    );
  const ids = new Set<string>();
  const records = value.records.map((raw, index) => {
    const label = `第 ${index + 1} 条`;
    if (!recordObject(raw) || !exactKeys(raw, recordKeys))
      historicalFailure(
        `${label} 的字段缺失或多余，请按导入格式逐项核对；空值请明确写 null。`,
      );
    if (!text(raw.external_record_id, 200) || !text(raw.explanation, 4000))
      historicalFailure(`${label} 须有外部记录编号和实交说明，不能只填空格。`);
    if (ids.has(raw.external_record_id))
      historicalFailure(
        `${label} 的外部记录编号重复，请为不同记录保留不同编号。`,
      );
    ids.add(raw.external_record_id);
    if (
      !["technical_total", "comprehensive_total", "unknown"].includes(
        String(raw.score_kind),
      ) ||
      !decimal(raw.value) ||
      !decimal(raw.maximum)
    )
      historicalFailure(
        `${label} 的分数须为精确十进制字符串或 null，并明确技术总分、综合总分或未知。`,
      );
    if (
      (raw.value === null) !== (raw.maximum === null) ||
      (raw.score_kind === "unknown" && raw.value !== null)
    )
      historicalFailure(
        `${label} 的未知成绩必须保留 null，真实零分写 "0" 并同时填写满分。`,
      );
    return {
      external_record_id: raw.external_record_id,
      bid_id: uuid(raw.bid_id, `${label}项目`),
      actual_document_version_id: uuid(
        raw.actual_document_version_id,
        `${label}实交正文版本`,
      ),
      submitted_at: historicalDateTime(
        raw.submitted_at,
        `${label}实际提交时间`,
      ),
      evidence_ref: uuid(raw.evidence_ref, `${label}实交证明版本`),
      explanation: raw.explanation,
      score_kind: raw.score_kind,
      value: raw.value,
      maximum: raw.maximum,
      source_version_id:
        raw.source_version_id === null
          ? null
          : uuid(raw.source_version_id, `${label}官方成绩原件版本`),
      known_at:
        raw.known_at === null
          ? null
          : historicalDateTime(raw.known_at, `${label}成绩取得时间`),
    } as HistoricalImportRecord;
  });
  if (
    new TextEncoder().encode(
      JSON.stringify({ schema: "historical-import/1", records }),
    ).byteLength > historicalImportLimit
  )
    historicalFailure(
      "规范后的清单超过 8 MiB，请明确拆分批次；不会自动丢弃记录。",
    );
  return { records };
}
export function parseHistoricalFile(raw: string) {
  if (new TextEncoder().encode(raw).byteLength > historicalImportLimit)
    historicalFailure("清单文件超过 8 MiB，请拆分后再读取。");
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    historicalFailure("文件不是有效 JSON，请检查引号、逗号和括号。");
  }
  return normalizeHistoricalRequest(value);
}
function counts(v: unknown) {
  return (
    recordObject(v) &&
    ["total", "pending", "imported", "errors"].every((key) =>
      integer(v[key], 0, 1000),
    ) &&
    v.total === Number(v.pending) + Number(v.imported) + Number(v.errors)
  );
}
export function historicalRecordCounts(
  records: HistoricalImportBatch["records"],
): HistoricalImportBatch["counts"] {
  return {
    total: records.length,
    pending: records.filter((row) => row.state === "pending").length,
    imported: records.filter((row) => row.state === "imported").length,
    errors: records.filter(
      (row) => row.state === "failed" || row.state === "conflict",
    ).length,
  };
}
export function validateHistoricalBatch(
  value: unknown,
  expected: { id?: string; offset?: number; etag: string | null },
): HistoricalImportBatch {
  if (
    !recordObject(value) ||
    !executionId(value.id) ||
    (expected.id && value.id !== expected.id) ||
    !["dry_run", "confirmed_import"].includes(String(value.mode)) ||
    !integer(value.revision, 1) ||
    !executionId(value.manifest_blob_id) ||
    !counts(value.counts) ||
    value.formal_sample_admission !==
      "separate_verified_technical_label_check" ||
    value.standard_submission_gate_checked !== false ||
    !Array.isArray(value.records) ||
    value.records.length > 200 ||
    expected.etag !==
      historicalImportEtag(value.id as string, value.revision as number)
  )
    historicalFailure();
  const result = value as HistoricalImportBatch;
  const offset = expected.offset ?? 0,
    next = offset + result.records.length;
  if (
    next > result.counts.total ||
    (result.next_offset === null
      ? next !== result.counts.total
      : result.next_offset !== next ||
        result.next_offset >= result.counts.total ||
        !result.records.length) ||
    (result.mode === "dry_run" && result.counts.imported !== 0)
  )
    historicalFailure();
  const ids = new Set<string>();
  for (const record of result.records) {
    if (
      !recordObject(record) ||
      record.batch_id !== result.id ||
      !text(record.external_record_id, 200) ||
      ids.has(record.external_record_id) ||
      !executionSha(record.source_digest) ||
      !nullableUuid(record.bid_id) ||
      !["pending", "imported", "conflict", "failed"].includes(record.state) ||
      !Array.isArray(record.errors) ||
      record.errors.length > 100 ||
      !record.errors.every((error) => text(error, 1000))
    )
      historicalFailure();
    ids.add(record.external_record_id);
  }
  const observed = historicalRecordCounts(result.records);
  if (
    (["pending", "imported", "errors"] as const).some(
      (key) => observed[key] > result.counts[key],
    ) ||
    (offset === 0 &&
      result.next_offset === null &&
      !historicalSame(observed, result.counts)) ||
    (result.mode === "confirmed_import" && result.counts.pending !== 0) ||
    (result.mode === "dry_run" &&
      result.records.some((row) => row.state === "failed"))
  )
    historicalFailure();
  return result;
}
export function validateHistoricalDirectory(
  value: unknown,
  offset: number,
): HistoricalImportPage {
  if (
    !recordObject(value) ||
    !Array.isArray(value.items) ||
    value.items.length > 100 ||
    !(
      value.next_offset === null ||
      (integer(value.next_offset, 1) &&
        value.next_offset === offset + value.items.length &&
        value.items.length > 0)
    ) ||
    !value.items.every(
      (item) =>
        recordObject(item) &&
        executionId(item.id) &&
        ["dry_run", "confirmed_import"].includes(String(item.mode)) &&
        integer(item.revision, 1) &&
        executionId(item.created_by) &&
        (item.created_at === null ||
          (typeof item.created_at === "string" &&
            Number.isFinite(Date.parse(item.created_at)))) &&
        counts(item.counts),
    )
  )
    historicalFailure();
  if (new Set(value.items.map((item) => item.id)).size !== value.items.length)
    historicalFailure();
  return value as HistoricalImportPage;
}
export async function validateHistoricalSource(
  value: unknown,
  batch: HistoricalImportBatch,
): Promise<HistoricalImportSource> {
  if (
    !recordObject(value) ||
    value.batch_id !== batch.id ||
    value.manifest_blob_id !== batch.manifest_blob_id ||
    !executionSha(value.manifest_digest) ||
    value.source_matches_saved_manifest !== true
  )
    historicalFailure();
  const result = value as HistoricalImportSource;
  // Validate, but hash the exact saved representation before normalizing any retry.
  const normalized = normalizeHistoricalRequest(result.request);
  if (
    normalized.records.length !== batch.counts.total ||
    (await jsonDigest({
      schema: "historical-import/1",
      records: result.request.records,
    })) !== result.manifest_digest
  )
    historicalFailure();
  const sources = new Map(
    normalized.records.map((record) => [record.external_record_id, record]),
  );
  if (
    batch.records.some(
      (record) =>
        !sources.has(record.external_record_id) ||
        (record.bid_id !== null &&
          sources.get(record.external_record_id)!.bid_id !== record.bid_id),
    )
  )
    historicalFailure();
  return result;
}
export async function validateHistoricalReceipt(
  value: unknown,
  memberId: string,
  pending: HistoricalPending,
  etag: string | null,
): Promise<HistoricalImportReceipt> {
  const batch = validateHistoricalBatch(value, {
    id: pending.kind === "confirm" ? pending.batchId : undefined,
    etag,
  });
  const result = value as HistoricalImportReceipt,
    command = result.command;
  if (
    !recordObject(command) ||
    !executionId(command.command_id) ||
    command.actor_id !== memberId ||
    command.idempotency_key !== pending.key ||
    command.if_match !== pending.etag ||
    command.command_kind !==
      (pending.kind === "preview"
        ? "preview-historical-import"
        : "confirm-historical-import") ||
    command.target_id !==
      (pending.kind === "preview"
        ? historicalPreviewTarget
        : pending.batchId) ||
    command.request_digest !==
      (await jsonDigest({ body: pending.body, if_match: pending.etag }))
  )
    historicalFailure();
  if (pending.kind === "preview") {
    const originals = new Map(
      pending.body.records.map((record) => [record.external_record_id, record]),
    );
    if (
      batch.mode !== "dry_run" ||
      batch.revision !== 1 ||
      batch.counts.total !== originals.size ||
      batch.records.some(
        (record) =>
          !originals.has(record.external_record_id) ||
          (record.bid_id !== null &&
            record.bid_id !== originals.get(record.external_record_id)!.bid_id),
      )
    )
      historicalFailure();
  } else if (
    batch.mode !== "confirmed_import" ||
    batch.revision !== pending.baseRevision + 1 ||
    batch.manifest_blob_id !== pending.manifestBlobId ||
    batch.counts.pending !== 0
  )
    historicalFailure();
  return result;
}
export function definitiveHistoricalFailure(error: unknown) {
  if (!(error instanceof ApiError) || error.retryable) return false;
  return (
    (error.status === 422 &&
      [
        "IMPORT_MANIFEST_TOO_LARGE",
        "IMPORT_DUPLICATE_RECORD_ID",
        "IMPORT_ORIGINAL_BUDGET_EXCEEDED",
      ].includes(error.code)) ||
    (error.status === 409 && error.code === "IMPORT_ALREADY_CONFIRMED") ||
    (error.status === 412 && error.code === "REVISION_CONFLICT")
  );
}
export const historicalErrorNames: Record<string, string> = {
  duplicate_within_batch: "本批有相同实交与成绩资料，重复项未导入。",
  already_imported_will_reuse: "相同资料已经导入，确认时将复用既有记录。",
  reused_existing_import: "已复用既有记录，没有另造实交或独立样本。",
  NOT_FOUND:
    "项目、正文、实交证明或官方成绩原件不存在于指定项目，请核对确切版本。",
  IMPORT_SUBMISSION_TIME_INVALID: "实际提交时间须明确时区且不能在未来。",
  IMPORT_OUTCOME_SOURCE_MISSING:
    "成绩需要官方来源原件与实际取得时间，未知不能填零。",
  IMPORT_OUTCOME_TIME_INVALID: "成绩取得时间不能早于实交，也不能在未来。",
  INVALID_SCORE: "分数需与满分配对，得分不能超过正数满分；未知不能填零。",
  IMPORT_INPUT_CHANGED: "预检查后资料身份变化，请核对后另建预检查。",
  IMPORT_OUTCOME_CONFLICT:
    "该实交已有成绩，需在项目中明确追加更正；导入不会覆盖。",
  IMPORT_ORIGINAL_MISSING: "确切原件字节缺失，本项未导入。",
  IMPORT_ORIGINAL_CORRUPTED: "原件字节与登记摘要不符，本项未导入。",
  IMPORT_ORIGINAL_CHANGED: "原件身份在确认期间变化，本项未导入。",
};
