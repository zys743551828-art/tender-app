import raw from "./test-fixtures/package-retrospective-http.json";
import { jsonDigest } from "./editorSchema";
import type {
  PackageRetrospectiveApplied,
  PackageRetrospectiveChoices,
  PackageRetrospectiveDetail,
  PackageRetrospectiveKnowledgeApplied,
  PackageRetrospectiveKnowledgeRequest,
  PackageRetrospectivePreview,
  PackageRetrospectiveRequest,
  PackageRetrospectiveSelection,
  PackageRetrospectiveView,
} from "./packageRetrospectiveContracts";
import { retrospectiveTag } from "./packageRetrospectiveProtocol";

type Fixture = {
  bid_id: string;
  member_id: string;
  selection: PackageRetrospectiveSelection;
  preview: PackageRetrospectivePreview;
  preview_etag: string;
  request: PackageRetrospectiveRequest;
  saved: PackageRetrospectiveApplied;
  saved_etag: string;
  save_key: string;
  candidate: PackageRetrospectiveKnowledgeApplied;
  candidate_request: PackageRetrospectiveKnowledgeRequest;
  candidate_key: string;
  detail: PackageRetrospectiveDetail;
  choices: Record<
    "submissions" | "outcomes" | "business_results" | "runs",
    PackageRetrospectiveChoices
  >;
};
export const retrospectiveFixture = () =>
  structuredClone(raw) as unknown as Fixture;
export const retrospectiveScope = (f: Fixture) =>
  `package-retrospective:${f.member_id}:${f.bid_id}:${f.selection.submission_id}`;
export const retrospectiveCandidateScope = (f: Fixture) =>
  `package-retrospective-knowledge:${f.member_id}:${f.bid_id}:${f.saved.retrospective.manifest.id}`;
export const retrospectiveDraftKey = (f: Fixture) =>
  `tender:retrospective-draft:${f.member_id}:${f.bid_id}:${f.selection.submission_id}`;

export async function retrospectiveAckFor(
  f: Fixture,
  body: PackageRetrospectiveRequest,
  key: string,
  condition: string,
) {
  const data = structuredClone(f.saved);
  data.retrospective.manifest.title = body.title;
  data.retrospective.manifest.notes = body.notes;
  data.retrospective.digest = await jsonDigest(data.retrospective.manifest);
  data.command = {
    ...data.command,
    idempotency_key: key,
    request: body,
    if_match: condition,
    request_digest: await jsonDigest({ body, if_match: condition }),
  };
  return { data, etag: retrospectiveTag(data.retrospective) };
}
export async function retrospectiveKnowledgeAckFor(
  f: Fixture,
  frozen: PackageRetrospectiveView,
  body: PackageRetrospectiveKnowledgeRequest,
  key: string,
  condition: string,
) {
  const data = structuredClone(f.candidate);
  data.link.retrospective_digest = frozen.digest;
  data.link.reason = body.reason;
  data.command = {
    ...data.command,
    idempotency_key: key,
    request: body,
    if_match: condition,
    request_digest: await jsonDigest({ body, if_match: condition }),
  };
  return { data, etag: condition };
}
