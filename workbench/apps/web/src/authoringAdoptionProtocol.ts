import type {
  AdoptAuthoringOutput,
  AuthoringOutputAdopted,
  BidPackageStoredView,
  BuildView,
} from "./contracts";
import {
  executionId as uuid,
  executionSha as sha,
  exactKeys,
  recordObject as object,
} from "./executionInputValidation";
import { jsonDigest } from "./editorSchema";
import { sameBuildRequest } from "./authoringBuildRecovery";

export type AdoptionScope = {
  bidId: string;
  memberId: string;
  buildId: string;
  documentId: string;
};
export type AdoptionBase = {
  id: string;
  revision: number;
  digest: string;
  membersDigest: string;
  memberCount: number;
  etag: string;
};
export type PendingAdoption = {
  version: 1;
  scope: AdoptionScope;
  key: string;
  body: AdoptAuthoringOutput;
  base: AdoptionBase | null;
};
const positive = (v: unknown) => Number.isSafeInteger(v) && Number(v) > 0;
const text = (v: unknown, limit = 200): v is string =>
  typeof v === "string" &&
  !!v.trim() &&
  Array.from(v).length <= limit &&
  Array.from(v).every((character) => {
    const point = character.codePointAt(0)!;
    return point > 31 && (point < 0xd800 || point > 0xdfff);
  });
export const adoptionStorageKey = (s: AdoptionScope) =>
  `tender:authoring:${s.memberId}:${s.bidId}:adoption:${s.buildId}:${s.documentId}`;

export function validAdoptionBody(v: unknown): v is AdoptAuthoringOutput {
  if (
    !object(v) ||
    !exactKeys(v, [
      "snapshot_id",
      "snapshot_digest",
      "package_id",
      "member",
      "reason",
    ]) ||
    !uuid(v.snapshot_id) ||
    !sha(v.snapshot_digest) ||
    !(v.package_id === null || uuid(v.package_id)) ||
    !text(v.reason, 1000) ||
    !object(v.member)
  )
    return false;
  const member = v.member;
  if (
    !exactKeys(member, [
      "member_id",
      "document_version_id",
      "purposes",
      "parts",
      ...("parse_run_id" in member ? ["parse_run_id"] : []),
    ]) ||
    !text(member.member_id) ||
    !uuid(member.document_version_id) ||
    !Array.isArray(member.purposes) ||
    !member.purposes.length ||
    new Set(member.purposes).size !== member.purposes.length ||
    !member.purposes.every((purpose) => text(purpose)) ||
    !Array.isArray(member.parts)
  )
    return false;
  if (
    member.parse_run_id === undefined
      ? member.parts.length > 0
      : !uuid(member.parse_run_id) || !member.parts.length
  )
    return false;
  return (
    member.parts.every(
      (part) =>
        object(part) &&
        exactKeys(part, [
          "part_id",
          "category",
          "first_page",
          "last_page",
          "shared_attachment",
          "heading_path",
        ]) &&
        text(part.part_id) &&
        text(part.category) &&
        positive(part.first_page) &&
        positive(part.last_page) &&
        Number(part.first_page) <= Number(part.last_page) &&
        typeof part.shared_attachment === "boolean" &&
        Array.isArray(part.heading_path) &&
        part.heading_path.every(positive),
    ) &&
    new Set(member.parts.map((part) => part.part_id)).size ===
      member.parts.length
  );
}

export function readAdoption(scope: AdoptionScope): {
  pending: PendingAdoption | null;
  blocked: boolean;
} {
  try {
    const raw = sessionStorage.getItem(adoptionStorageKey(scope));
    if (!raw) return { pending: null, blocked: false };
    const value: unknown = JSON.parse(raw);
    if (
      !object(value) ||
      !exactKeys(value, ["version", "scope", "key", "body", "base"]) ||
      value.version !== 1 ||
      !sameBuildRequest(value.scope, scope) ||
      !uuid(value.key) ||
      !validAdoptionBody(value.body) ||
      value.body.member.document_version_id !== scope.documentId
    )
      throw new Error("invalid recovery");
    const base = value.base;
    if (
      base === null
        ? value.body.package_id !== null
        : !object(base) ||
          !exactKeys(base, [
            "id",
            "revision",
            "digest",
            "membersDigest",
            "memberCount",
            "etag",
          ]) ||
          base.id !== value.body.package_id ||
          !uuid(base.id) ||
          !positive(base.revision) ||
          !positive(base.memberCount) ||
          Number(base.memberCount) >= 500 ||
          !sha(base.digest) ||
          !sha(base.membersDigest) ||
          base.etag !== `"bid-package-head:${base.id}:${base.digest}"`
    )
      throw new Error("invalid package base");
    return { pending: value as PendingAdoption, blocked: false };
  } catch {
    return { pending: null, blocked: true };
  }
}

export async function checkedAdoptionBase(
  value: BidPackageStoredView,
  bidId: string,
  packageId: string,
  etag: string | null,
): Promise<AdoptionBase> {
  const manifest = value?.manifest;
  if (
    !manifest ||
    manifest.package_id !== packageId ||
    manifest.scope?.bid_id !== bidId ||
    manifest.kind !== "bid" ||
    manifest.identity_version !== "bid-package/1" ||
    !uuid(manifest.revision_id) ||
    !positive(manifest.revision) ||
    !Array.isArray(manifest.members) ||
    !manifest.members.length ||
    manifest.members.length >= 500 ||
    !sha(value.digest) ||
    (await jsonDigest(manifest)) !== value.digest ||
    etag !== `"bid-package-head:${packageId}:${value.digest}"`
  )
    throw new Error(
      "当前投标包身份、完整清单或版本令牌无法核对，尚未采用文件。",
    );
  return {
    id: packageId,
    revision: manifest.revision,
    digest: value.digest,
    memberCount: manifest.members.length,
    membersDigest: await jsonDigest(manifest.members),
    etag,
  };
}

export async function validateAdoption(
  value: AuthoringOutputAdopted,
  pending: PendingAdoption,
  build: BuildView,
  responseEtag: string | null,
) {
  const fail = () => {
    throw new Error(
      "采用回执与原文件、固定快照或包新修订不一致。原请求保留，请按原 key 核对。",
    );
  };
  const { scope, body, base } = pending;
  if (
    !value ||
    value.protocol !== "authoring-output-adoption/1" ||
    value.bid_id !== scope.bidId ||
    value.build_id !== scope.buildId ||
    value.actor_id !== scope.memberId ||
    !uuid(value.command_id) ||
    value.current_body_changed !== false ||
    value.automatically_started_review !== false ||
    value.request_digest !==
      (await jsonDigest({
        body: { bid_id: scope.bidId, ...body },
        if_match: base?.etag ?? null,
      }))
  )
    fail();
  const output = value.output;
  const selected = build.outputs.find(
    (item) =>
      item.document_version_id === scope.documentId &&
      item.state === "succeeded",
  );
  const expectedIdentity = Object.fromEntries(
    Object.entries(build.identity).filter(
      ([key]) => !["protocol", "bid_id", "request"].includes(key),
    ),
  );
  if (
    !output ||
    output.protocol !== "authoring-build-output/1" ||
    output.bid_id !== scope.bidId ||
    output.build_id !== scope.buildId ||
    output.document_version_id !== scope.documentId ||
    !selected ||
    output.format !== selected.format ||
    !sha(output.sha256) ||
    !positive(output.byte_size) ||
    !sameBuildRequest(output.build_identity, expectedIdentity) ||
    output.build_identity.snapshot_id !== body.snapshot_id ||
    output.build_identity.snapshot_digest !== body.snapshot_digest ||
    !uuid(output.word_document_version_id) ||
    !sha(output.word_sha256) ||
    !sha(output.publication_receipt_digest) ||
    !sha(output.source_authority_digest) ||
    !Array.isArray(output.direct_source_ids) ||
    !output.direct_source_ids.every(uuid) ||
    new Set(output.direct_source_ids).size !==
      output.direct_source_ids.length ||
    (output.format === "pdf"
      ? output.word_pdf_relation !== "verified" ||
        build.outputs.find((item) => item.format === "docx")
          ?.document_version_id !== output.word_document_version_id
      : output.word_pdf_relation !== "not_applicable" ||
        output.word_document_version_id !== scope.documentId ||
        output.word_sha256 !== output.sha256)
  )
    fail();
  const pack = value.package;
  const manifest = pack?.manifest;
  if (
    !manifest ||
    pack.review_ready !== false ||
    manifest.kind !== "bid" ||
    manifest.identity_version !== "bid-package/1" ||
    !uuid(manifest.package_id) ||
    !uuid(manifest.revision_id) ||
    manifest.scope.bid_id !== scope.bidId ||
    manifest.revision !== (base?.revision ?? 0) + 1 ||
    manifest.predecessor_digest !== (base?.digest ?? null) ||
    (base && manifest.package_id !== base.id) ||
    !Array.isArray(manifest.members) ||
    manifest.members.length !== (base?.memberCount ?? 0) + 1 ||
    !sha(pack.digest) ||
    (await jsonDigest(manifest)) !== pack.digest ||
    value.package_etag !==
      `"bid-package-head:${manifest.package_id}:${pack.digest}"` ||
    responseEtag !== value.package_etag
  )
    fail();
  if (
    base &&
    (await jsonDigest(manifest.members.slice(0, -1))) !== base.membersDigest
  )
    fail();
  const member = manifest.members.at(-1)!;
  if (
    !member ||
    member.member_id !== body.member.member_id ||
    member.document_version_id !== scope.documentId ||
    member.file_digest !== output.sha256 ||
    member.source_kind !== "own" ||
    !sameBuildRequest(member.purposes, body.member.purposes) ||
    !sameBuildRequest(member.parts, body.member.parts) ||
    !sameBuildRequest(member.scope, manifest.scope) ||
    (body.member.parse_run_id
      ? member.parse.status !== "frozen" ||
        member.parse.parse_run_id !== body.member.parse_run_id ||
        !sha(member.parse.evidence_digest)
      : member.parse.status !== "not_frozen" ||
        member.page_count !== null ||
        member.parts.length !== 0)
  )
    fail();
  return value;
}
