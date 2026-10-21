import type { Accepted, BuildRequest, BuildView } from "./contracts";
import { ApiError } from "./api";

type Dict = Record<string, unknown>;
const object = (value: unknown): value is Dict =>
  !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string =>
  typeof value === "string" && !!value && value.length <= 200;
const positive = (value: unknown): value is number =>
  Number.isSafeInteger(value) && Number(value) > 0;
const digest = (value: unknown) =>
  typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
function ordered(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(ordered);
  if (object(value))
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([key, item]) => [key, ordered(item)]),
    );
  return value;
}
export const sameBuildRequest = (left: unknown, right: unknown) =>
  JSON.stringify(ordered(left)) === JSON.stringify(ordered(right));
export function validBuildRequest(
  value: unknown,
  draftId: string,
): value is BuildRequest {
  if (
    !object(value) ||
    value.draft_id !== draftId ||
    !positive(value.draft_revision) ||
    !Array.isArray(value.formats) ||
    !value.formats.length ||
    value.formats.length > 2 ||
    new Set(value.formats).size !== value.formats.length ||
    !value.formats.every((format) =>
      ["docx", "pdf"].includes(String(format)),
    ) ||
    !["none", "review"].includes(String(value.follow_up))
  )
    return false;
  const common = ["draft_id", "draft_revision", "formats", "follow_up"];
  const fields =
    "template_version_id" in value
      ? [...common, "template_version_id"]
      : [
          ...common,
          "directory_template_version_id",
          "style_template_version_id",
          ...("pagination_mode" in value ? ["pagination_mode"] : []),
        ];
  if (
    Object.keys(value).length !== fields.length ||
    !fields.every((key) => key in value)
  )
    return false;
  if (
    "template_version_id" in value
      ? !text(value.template_version_id)
      : !text(value.directory_template_version_id) ||
        !text(value.style_template_version_id)
  )
    return false;
  return (
    !("pagination_mode" in value) ||
    ["chapter_start_new_page", "continuous"].includes(
      String(value.pagination_mode),
    )
  );
}
export type PendingBuild = {
  key: string;
  body: BuildRequest;
  snapshotId?: string;
};
export type ReceivedBuild = {
  id: string;
  snapshotId: string;
  revision: number | null;
};
export type BuildCache = {
  version: 2;
  bidId: string;
  memberId: string;
  draftId: string;
  pending: PendingBuild | null;
  received: ReceivedBuild[];
};
export function emptyBuildCache(
  bidId: string,
  memberId: string,
  draftId: string,
): BuildCache {
  return { version: 2, bidId, memberId, draftId, pending: null, received: [] };
}
export function readBuildCache(
  key: string,
  bidId: string,
  memberId: string,
  draftId: string,
) {
  const empty = emptyBuildCache(bidId, memberId, draftId);
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return { cache: empty, blocked: false };
    const value = JSON.parse(raw) as unknown;
    if (
      !object(value) ||
      (value.version !== undefined &&
        (value.version !== 2 ||
          value.bidId !== bidId ||
          value.memberId !== memberId ||
          value.draftId !== draftId)) ||
      !Array.isArray(value.received) ||
      value.received.length > 30 ||
      !value.received.every(
        (row) =>
          object(row) &&
          text(row.id) &&
          typeof row.snapshotId === "string" &&
          (row.revision === null || positive(row.revision)),
      )
    )
      throw new Error("invalid cache");
    if (
      value.pending !== null &&
      (!object(value.pending) ||
        !text(value.pending.key) ||
        !validBuildRequest(value.pending.body, draftId) ||
        (value.pending.snapshotId !== undefined &&
          !text(value.pending.snapshotId)))
    )
      throw new Error("invalid pending");
    return {
      cache: {
        ...empty,
        pending: value.pending as PendingBuild | null,
        received: value.received as ReceivedBuild[],
      },
      blocked: false,
    };
  } catch {
    return { cache: empty, blocked: true };
  }
}

export function validBuildView(
  value: unknown,
  bidId: string,
  draftId: string,
  buildId?: string,
): value is BuildView {
  if (
    !object(value) ||
    !text(value.id) ||
    (buildId && value.id !== buildId) ||
    !text(value.operation_id) ||
    !text(value.draft_snapshot_id) ||
    !object(value.identity)
  )
    return false;
  const id = value.identity;
  if (
    id.protocol !== "authoring-build-identity/1" ||
    id.bid_id !== bidId ||
    id.draft_id !== draftId ||
    !positive(id.draft_revision) ||
    id.snapshot_id !== value.draft_snapshot_id ||
    !digest(id.snapshot_digest) ||
    !text(id.build_input_id) ||
    !digest(id.input_digest) ||
    !digest(id.manifest_digest) ||
    ![
      "strict_text/1",
      "structured_text/1",
      "generated_text/2",
      "generated_rich/3",
    ].includes(String(id.writer_kind)) ||
    !validBuildRequest(id.request, draftId) ||
    id.request.draft_revision !== id.draft_revision
  )
    return false;
  if (
    (id.writer_kind === "generated_rich/3") !==
    "pagination_mode" in id.request
  )
    return false;
  if (
    !Array.isArray(value.outputs) ||
    value.outputs.length > 2 ||
    new Set(value.outputs.map((row) => (object(row) ? row.format : null)))
      .size !== value.outputs.length ||
    !value.outputs.every(
      (row) =>
        object(row) &&
        ["docx", "pdf"].includes(String(row.format)) &&
        ["pending", "failed", "succeeded"].includes(String(row.state)) &&
        (row.state === "succeeded"
          ? text(row.document_version_id)
          : row.document_version_id === null) &&
        Array.isArray(row.gaps) &&
        row.gaps.every((gap) => typeof gap === "string"),
    )
  )
    return false;
  if (
    !object(value.follow_up) ||
    typeof value.follow_up.requested !== "boolean" ||
    ![
      "not_requested",
      "pending",
      "adopted",
      "needs_selection",
      "failed",
    ].includes(String(value.follow_up.state)) ||
    value.follow_up.requested !== (id.request.follow_up === "review")
  )
    return false;
  if (value.layout !== null && value.layout !== undefined) {
    const layout = value.layout;
    if (
      !object(layout) ||
      layout.scope !== "navigation_only" ||
      !("pagination_mode" in id.request) ||
      layout.pagination_mode !== id.request.pagination_mode ||
      !["pending", "partial", "complete"].includes(String(layout.state)) ||
      typeof layout.fixed_point !== "boolean" ||
      (layout.state === "complete") !== layout.fixed_point ||
      !(layout.page_count === null || positive(layout.page_count)) ||
      !Number.isSafeInteger(layout.iteration_count) ||
      Number(layout.iteration_count) < 0 ||
      Number(layout.iteration_count) > 3 ||
      !Array.isArray(layout.entries) ||
      !layout.entries.every(
        (entry) =>
          object(entry) &&
          text(entry.section_id) &&
          ["start_page", "end_page", "printed_toc_page"].every(
            (key) => entry[key] === null || positive(entry[key]),
          ) &&
          Array.isArray(entry.gaps) &&
          entry.gaps.every((gap) => typeof gap === "string"),
      ) ||
      !Array.isArray(layout.gaps)
    )
      return false;
  } else if (id.writer_kind === "generated_rich/3") return false;
  return true;
}

export function matchBuildAck(
  ack: Accepted,
  view: BuildView,
  bidId: string,
  draftId: string,
  pending: PendingBuild,
) {
  return (
    ack?.resource_kind === "build" &&
    validBuildView(view, bidId, draftId, ack.resource_id) &&
    ack.operation?.id === view.operation_id &&
    ack.operation.bid_id === bidId &&
    ack.operation.kind === "build" &&
    ack.operation.handler_version === "export/1" &&
    ack.operation.input_digest === view.identity.input_digest &&
    sameBuildRequest(view.identity.request, pending.body) &&
    (!pending.snapshotId || pending.snapshotId === view.draft_snapshot_id)
  );
}
export function definitiveBuildFailure(failure: unknown) {
  return (
    failure instanceof ApiError &&
    [400, 409, 412, 422].includes(failure.status) &&
    !["IDEMPOTENCY_CONFLICT", "COMMAND_INCOMPLETE"].includes(failure.code) &&
    !failure.retryable
  );
}
