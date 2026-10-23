import captured from "./test-fixtures/authoring-input-catalog-http.json";
import type {
  AuthoringWorkContext,
  PackageAuthoringFactCatalog,
  PackageAuthoringInputRequest,
  PackageAuthoringInputView,
  WorkContextChoicePage,
} from "./contracts";
import { emptyCaptureDraft, type CaptureDraft } from "./authoringCaptureForm";

/** Unmodified native PG17/S3 HTTP responses; upstream documents are synthetic. */
export function captureFixture() {
  const bundle = structuredClone(captured);
  const responses = new Map(bundle.responses.map((item) => [item.name, item]));
  function body<T>(name: string): T {
    const response = responses.get(name);
    if (!response) throw new Error("Unknown native fixture response " + name);
    return response.body as unknown as T;
  }
  const request = bundle.request as PackageAuthoringInputRequest;
  const saved = body<PackageAuthoringInputView>("saved");
  const memberId = saved.manifest.actor_id;
  if (typeof memberId !== "string")
    throw new Error("Native fixture actor is missing");
  const facts = body<PackageAuthoringFactCatalog>("facts");
  const snapshot = body<AuthoringWorkContext>("snapshot");
  const choice = body<WorkContextChoicePage>("snapshot_choices").items.find(
    (item) => item.id === request.target_section.snapshot_id,
  )!;
  if (choice.selection.kind !== "draft_snapshot")
    throw new Error("Wrong fixture selection");
  const draft: CaptureDraft = {
    ...emptyCaptureDraft(),
    target: request.package_context.target,
    authority: request.package_context.authority,
    inventory: {
      id: request.package_context.inventory.id,
      digest: request.package_context.inventory.digest,
    },
    snapshot: {
      id: choice.id,
      label: choice.label,
      selection_digest: choice.selection_digest,
      selection: choice.selection,
    },
    section: {
      id: request.target_section.section_id,
      digest: request.target_section.section_digest,
    },
    node: {
      id: request.target_section.node_id,
      digest: request.target_section.before_node_digest,
    },
    factSet: {
      id: facts.selection.fact_set_id,
      digest: facts.selection.fact_set_digest,
      head_revision: facts.selection.fact_head_revision,
    },
    identities: Object.fromEntries(
      facts.items.map((item) => [item.identity_name, item.fact_id]),
    ) as CaptureDraft["identities"],
    uses: request.facts.uses.map((use) => ({
      fact_id: use.fact_id,
      subject_kind: use.subject.kind,
      reason: use.reason,
    })),
  };
  return {
    bundle,
    responses,
    body,
    request,
    saved,
    facts,
    snapshot,
    draft,
    memberId,
    bidId: bundle.bid_id,
  };
}
