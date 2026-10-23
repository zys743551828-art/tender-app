import type {
  AuthoringHistoricalSectionView,
  AuthoringRevisionPage,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { readAuthoringContent } from "./richEditorSchema";

export type HistoricalSectionSelection = {
  bidId: string;
  draftId: string;
  sectionId: string;
  revision: number;
  digest: string;
};
const integer = (value: unknown): value is number =>
  Number.isSafeInteger(value) && Number(value) > 0;
const time = (value: unknown) =>
  typeof value === "string" &&
  /(Z|[+-]\d{2}:\d{2})$/.test(value) &&
  Number.isFinite(Date.parse(value));
const keys = (
  value: unknown,
  names: string[],
): value is Record<string, unknown> =>
  recordObject(value) && exactKeys(value, names);

function invalid(): never {
  throw new Error(
    "历史章节的项目、原修订、完整正文或图片绑定无法核验，请保留原选择后重试。",
  );
}

export function historicalSectionPath(selection: HistoricalSectionSelection) {
  return `/bids/${selection.bidId}/drafts/${selection.draftId}/sections/${selection.sectionId}/revisions/${selection.revision}?expected_digest=${selection.digest}`;
}

export function readAuthoringRevisionPage(
  value: unknown,
  before?: number,
): AuthoringRevisionPage {
  if (
    !keys(value, ["items", "next_cursor"]) ||
    !Array.isArray(value.items) ||
    value.items.length > 100 ||
    (value.next_cursor !== null && !integer(value.next_cursor))
  )
    invalid();
  let previous = before ?? Number.POSITIVE_INFINITY;
  for (const item of value.items) {
    if (
      !keys(item, ["revision", "created_at", "digest", "created_by"]) ||
      !integer(item.revision) ||
      item.revision >= previous ||
      !time(item.created_at) ||
      !executionSha(item.digest) ||
      !executionId(item.created_by)
    )
      invalid();
    previous = item.revision;
  }
  if (
    value.next_cursor !== null &&
    (!value.items.length || value.next_cursor !== previous)
  )
    invalid();
  return value as AuthoringRevisionPage;
}

export async function validateHistoricalSection(
  value: unknown,
  expected: HistoricalSectionSelection,
): Promise<AuthoringHistoricalSectionView> {
  if (
    !keys(value, [
      "version",
      "bid_id",
      "draft_id",
      "section_id",
      "section_revision_id",
      "revision",
      "schema_digest",
      "digest",
      "content",
      "created_by",
      "created_at",
      "images",
      "read_only",
      "source_qualification_assessed",
      "restoration_authorized",
    ]) ||
    value.version !== "authoring-historical-section/1" ||
    ![
      value.bid_id,
      value.draft_id,
      value.section_id,
      value.section_revision_id,
      value.created_by,
    ].every(executionId) ||
    value.bid_id !== expected.bidId ||
    value.draft_id !== expected.draftId ||
    value.section_id !== expected.sectionId ||
    !integer(value.revision) ||
    value.revision !== expected.revision ||
    !executionSha(value.schema_digest) ||
    !executionSha(value.digest) ||
    value.digest !== expected.digest ||
    !time(value.created_at) ||
    value.read_only !== true ||
    value.source_qualification_assessed !== false ||
    value.restoration_authorized !== false ||
    !Array.isArray(value.images) ||
    value.images.length > 10000
  )
    invalid();
  const content = readAuthoringContent(value.content, true);
  if ((await jsonDigest(value.content)) !== value.digest) invalid();
  const images = new Map<string, Record<string, unknown>>();
  for (const image of value.images) {
    if (
      !keys(image, [
        "asset_id",
        "asset_revision",
        "asset_version_id",
        "version_digest",
        "normalized_sha256",
        "media_type",
      ]) ||
      !executionId(image.asset_id) ||
      !executionId(image.asset_version_id) ||
      !integer(image.asset_revision) ||
      !executionSha(image.version_digest) ||
      !executionSha(image.normalized_sha256) ||
      image.media_type !== "image/png" ||
      images.has(image.asset_version_id)
    )
      invalid();
    images.set(image.asset_version_id, image);
  }
  const used = new Set<string>();
  content.descendants((node) => {
    if (node.type.name !== "image") return;
    const image = images.get(node.attrs.asset_version_id);
    if (
      !image ||
      image.asset_id !== node.attrs.asset_id ||
      image.asset_revision !== node.attrs.asset_revision
    )
      invalid();
    used.add(node.attrs.asset_version_id);
  });
  if (used.size !== images.size) invalid();
  return value as AuthoringHistoricalSectionView;
}
