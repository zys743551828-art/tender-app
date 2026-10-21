import raw from "./test-fixtures/technical-scope-synthetic.json";
import type {
  PackageTechnicalScopeApplied,
  PackageTechnicalScopeContext,
  PackageTechnicalScopePreview,
  PackageTechnicalScopeRequest,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  technicalSelection,
  type TechnicalPending,
} from "./packageTechnicalScopeProtocol";

export function technicalFixture() {
  const f = structuredClone(raw) as unknown as {
    context: PackageTechnicalScopeContext;
    request: PackageTechnicalScopeRequest;
    preview: PackageTechnicalScopePreview;
    ack: PackageTechnicalScopeApplied;
    pending: TechnicalPending;
    etag: string;
  };
  return {
    ...f,
    scope: technicalSelection(
      f.context.target.manifest.scope.bid_id,
      f.ack.command.actor_id,
      f.context.target,
      f.context.inventory,
    ),
  };
}

export async function technicalAckFor(pending: TechnicalPending) {
  const f = technicalFixture(),
    ack = structuredClone(f.ack);
  ack.command.idempotency_key = pending.key;
  ack.command.request = pending.body;
  ack.command.if_match = pending.etag;
  ack.command.request_digest = await jsonDigest({
    body: {
      scope: [f.scope.bidId, f.scope.packageId, f.scope.revisionId],
      ...pending.body,
    },
    if_match: pending.etag,
  });
  return { data: ack, etag: f.etag };
}
