import { useEffect, useState } from "react";
import { api } from "./api";
import {
  exactActionSaved,
  exactAdoptionBinding,
  verifyExactAction,
  verifyExactQualification,
} from "./authoringExactProtocol";
import type { DraftSaved, DraftView } from "./contracts";
import { executionId, executionSha } from "./executionInputValidation";
import { ResourceState } from "./ResourceState";
import { authoringText } from "./richEditorSchema";
import { useResource } from "./useResource";

export function AuthoringAdoptionHandoff({
  bidId,
  query,
}: {
  bidId: string;
  query: URLSearchParams;
}) {
  const draftId = query.get("draft");
  const actionId = query.get("adoption");
  const snapshotId = query.get("snapshot");
  const digest = query.get("snapshot_digest");
  const valid =
    executionId(bidId) &&
    executionId(draftId) &&
    executionId(actionId) &&
    executionId(snapshotId) &&
    executionSha(digest) &&
    ["draft", "adoption", "snapshot", "snapshot_digest"].every(
      (field) => query.getAll(field).length === 1,
    );
  const [receipt, setReceipt] = useState<{
    saved: DraftSaved;
    title: string;
    text: string;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [epoch, setEpoch] = useState(0);
  useEffect(() => {
    if (!valid) return;
    let active = true;
    setError(null);
    void (async () => {
      const result = await api<unknown>(`/assistant/actions/${actionId}`);
      const action = await verifyExactAction(
        result.data,
        result.etag,
        actionId,
        bidId,
      );
      const saved = exactActionSaved(action);
      if (
        !saved ||
        saved.draft_id !== draftId ||
        saved.snapshot_id !== snapshotId ||
        saved.snapshot_digest !== digest
      )
        throw new Error("链接中的草稿或快照与原采纳回执不一致。");
      const frozen = await api<unknown>(
        `/bids/${bidId}/draft-snapshots/${saved.snapshot_id}`,
      );
      const binding = await exactAdoptionBinding(frozen.data, action, saved);
      const qualification = await api<unknown>(
        `/bids/${bidId}/authoring/section-revisions/${binding.section_revision_id}/exact-qualification`,
      );
      await verifyExactQualification(
        qualification.data,
        binding,
        action,
        saved,
      );
      if (active)
        setReceipt({
          saved,
          title: action.preview.after.attrs.title,
          text: authoringText(action.preview.after),
        });
    })().catch((failure: unknown) => {
      if (active) setError(failure);
    });
    return () => {
      active = false;
    };
  }, [actionId, bidId, digest, draftId, epoch, snapshotId, valid]);

  const current = useResource<DraftView>(
    receipt ? `/bids/${bidId}/drafts/${receipt.saved.draft_id}` : null,
  );
  const head = current.data;
  const verifiedHead =
    receipt &&
    head &&
    head.id === receipt.saved.draft_id &&
    head.bid_id === bidId &&
    executionId(head.snapshot_id) &&
    Number.isSafeInteger(head.revision) &&
    (head.revision === receipt.saved.draft_revision
      ? head.snapshot_id === receipt.saved.snapshot_id
      : head.revision > receipt.saved.draft_revision &&
        head.snapshot_id !== receipt.saved.snapshot_id)
      ? head
      : null;
  return (
    <section className="panel" aria-label="采纳快照核对">
      <h3>本次采纳的固定快照</h3>
      {!valid && (
        <p role="alert" className="notice error">
          采纳快照链接缺少有效的固定身份，请返回原采纳回执重新打开。
        </p>
      )}
      {valid && (
        <ResourceState
          loading={!error && !receipt}
          error={error}
          hasData={!!receipt}
          onRetry={() => setEpoch((n) => n + 1)}
          loadingLabel="正在核对原采纳回执与固定快照…"
        />
      )}
      {receipt && (
        <>
          <p>本次采纳固定为草稿修订 {receipt.saved.draft_revision}。</p>
          <p className="identity-ref">快照 {receipt.saved.snapshot_id}</p>
          <p className="identity-ref">
            快照摘要 {receipt.saved.snapshot_digest}
          </p>
          <details className="snapshot-reading">
            <summary>查看本次采纳的章节正文</summary>
            <strong>{receipt.title}</strong>
            <pre>{receipt.text}</pre>
          </details>
          <ResourceState
            {...current}
            hasData={!!verifiedHead}
            onRetry={() => void current.reload()}
            loadingLabel="正在核对当前草稿修订…"
          />
          {head && !verifiedHead && (
            <p role="alert" className="notice error">
              无法核对当前草稿与本次采纳快照的版本关系。
            </p>
          )}
          {verifiedHead && !current.loading && !current.error && (
            <>
              <p>
                {verifiedHead.revision === receipt.saved.draft_revision
                  ? `当前草稿仍为修订 ${verifiedHead.revision}。`
                  : `当前草稿已更新到修订 ${verifiedHead.revision}。本页仍只显示原采纳快照。`}
              </p>
              <p className="small-note">
                「查看当前草稿」会重新读取打开时的当前修订；请核对实际修订，再明确决定是否生成内部文件。不会自动构建。
              </p>
              <a
                className="button secondary"
                href={`/bids/${bidId}/authoring?${new URLSearchParams({ draft: receipt.saved.draft_id })}`}
              >
                查看当前草稿
              </a>
            </>
          )}
        </>
      )}
    </section>
  );
}
