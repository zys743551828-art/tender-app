import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { historicalSame } from "./historicalImportProtocol";
import type { DraftSaved, AuthoringExactSectionBinding } from "./contracts";
import {
  exactActionSaved,
  exactAdoptionBinding,
  packageActionBasis,
  readExactCapabilities,
  verifyExactAction,
  verifyExactQualification,
  verifyExactCandidateInput,
  type ExactActionDecision,
  type ExactPackageAction,
} from "./authoringExactProtocol";
import { useExactAuthoringAction } from "./useExactAuthoringAction";
import type { VerifiedAuthoringInput } from "./packageAuthoringInputProtocol";

function AdoptionReceipt({
  action,
  saved,
  input,
}: {
  action: ExactPackageAction;
  saved: DraftSaved;
  input: VerifiedAuthoringInput | null;
}) {
  const [proof, setProof] = useState<{
    binding: AuthoringExactSectionBinding;
    digest: string;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [epoch, setEpoch] = useState(0);
  useEffect(() => {
    let active = true;
    setProof(null);
    setError(null);
    if (!input)
      return () => {
        active = false;
      };
    void (async () => {
      await verifyExactCandidateInput(input, action);
      const snapshot = await api<unknown>(
        `/bids/${action.target_bid_id}/draft-snapshots/${saved.snapshot_id}`,
      );
      const binding = await exactAdoptionBinding(snapshot.data, action, saved);
      if (!active) return;
      const qualification = await api<unknown>(
        `/bids/${action.target_bid_id}/authoring/section-revisions/${binding.section_revision_id}/exact-qualification`,
      );
      const verified = await verifyExactQualification(
        qualification.data,
        binding,
        action,
        saved,
      );
      if (active) setProof({ binding, digest: verified.digest });
    })().catch((caught: unknown) => {
      if (active) setError(caught);
    });
    return () => {
      active = false;
    };
  }, [action, saved, input, epoch]);
  return (
    <section aria-label="固定整包正文采纳结果">
      <p className="inline-success" role="status">
        服务端已记录采纳：草稿修订 {saved.draft_revision}
        。原稿和历史保留，文件构建与入包结果需单独核对。
      </p>
      <ResourceState
        loading={!!input && !proof && !error}
        error={error}
        hasData={!!proof}
        onRetry={() => setEpoch((n) => n + 1)}
        loadingLabel="正在核验本次正文修订与固定输入来源…"
      />
      {!input && (
        <p className="small-note">
          固定输入尚未读取或核验，请先恢复上方输入详情，随后核对本次保存结果。
        </p>
      )}
      {proof && (
        <>
          <p>
            已核验章节修订 {proof.binding.section_revision}
            、采纳后的固定快照和原输入来源关系；采纳不表示内容正确、核查通过或已入包。
          </p>
          <a
            href={`/bids/${action.target_bid_id}/authoring?draft=${encodeURIComponent(saved.draft_id)}`}
          >
            打开这份正文草稿，核对修订并生成文件
          </a>
          <details className="identity-details">
            <summary>本次采纳的固定身份</summary>
            <p>
              草稿修订 {saved.draft_revision}；快照 {saved.snapshot_id}
              ；快照摘要 {saved.snapshot_digest}；来源资格摘要 {proof.digest}。
            </p>
          </details>
        </>
      )}
    </section>
  );
}

/** Separate B3 commands from the generic legacy action hook. The original B2
 * candidate/result remains unchanged; availability is verified independently. */
export function PackageAuthoringActionControls({
  action,
  etag,
  memberId,
  input,
  fresh,
  projectWritable,
  onChanged,
}: {
  action: ExactPackageAction;
  etag: string | null;
  memberId: string;
  input: VerifiedAuthoringInput | null;
  fresh: boolean;
  projectWritable: boolean;
  onChanged: () => void;
}) {
  const capabilities = useResource<unknown>(
    action.preview.apply_available
      ? "/authoring/exact-revision-capabilities"
      : null,
  );
  const command = useExactAuthoringAction({
    memberId,
    actionId: action.action_id,
  });
  const basis = useRef<ReturnType<typeof packageActionBasis> | null>(null);
  const [checked, setChecked] = useState("");
  const [verification, setVerification] = useState<{
    action: ExactPackageAction;
    etag: string;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [ack, setAck] = useState<ExactPackageAction | null>(null);
  const [inputProof, setInputProof] = useState<{
    input: VerifiedAuthoringInput;
    action: ExactPackageAction;
  } | null>(null);
  const [inputError, setInputError] = useState<unknown>(null);
  useEffect(() => {
    let active = true;
    setInputProof(null);
    setInputError(null);
    setChecked("");
    if (input)
      void verifyExactCandidateInput(input, action)
        .then(() => {
          if (active) setInputProof({ input, action });
        })
        .catch((failure: unknown) => {
          if (active) setInputError(failure);
        });
    return () => {
      active = false;
    };
  }, [input, action]);
  useEffect(() => {
    let active = true;
    setVerification(null);
    setError(null);
    void verifyExactAction(action, etag, action.action_id)
      .then((verified) => {
        if (!active) return;
        const next = packageActionBasis(verified);
        if (basis.current && !historicalSame(basis.current, next))
          throw new Error(
            "原候选的固定身份或正文发生变化，保留原核对结果并停止新操作。",
          );
        basis.current ??= next;
        setVerification({ action: verified, etag: etag! });
      })
      .catch((caught: unknown) => {
        if (active) setError(caught);
      });
    return () => {
      active = false;
    };
  }, [action, etag]);
  let capability: ReturnType<typeof readExactCapabilities> | null = null,
    capabilityError: unknown = null;
  if (capabilities.data) {
    try {
      capability = readExactCapabilities(capabilities.data);
    } catch (caught) {
      capabilityError = caught;
    }
  }
  const verified =
    verification?.action === action && verification.etag === etag
      ? action
      : null;
  const effective = ack ?? verified;
  const saved = effective ? exactActionSaved(effective) : null;
  const available =
    !!capability?.apply_available && !!action.preview.apply_available;
  const inputReady =
    inputProof?.input === input && inputProof?.action === action;
  const processing =
    command.busy || command.pending || command.conflict || command.blocked;
  const canResolve = !!verified && fresh && !processing && !ack;
  async function resolve(decision: ExactActionDecision) {
    if (
      !canResolve ||
      !verification ||
      (decision === "confirm" &&
        (!available || !inputReady || !projectWritable || checked !== etag))
    )
      return;
    const result = await command.run(
      verification.action,
      verification.etag,
      decision,
      input,
    );
    if (result) {
      setAck(result.data);
      setChecked("");
      onChanged();
    }
  }
  async function retry() {
    const result = await command.retry();
    if (result) {
      setAck(result.data);
      setChecked("");
      onChanged();
    }
  }
  async function refreshConflict() {
    try {
      const response = await api<unknown>(
        `/assistant/actions/${action.action_id}`,
      );
      const next = await verifyExactAction(
        response.data,
        response.etag,
        action.action_id,
        action.target_bid_id,
      );
      if (await command.acknowledgeConflict(next, response.etag!)) {
        setVerification(null);
        setChecked("");
        onChanged();
      }
    } catch (caught) {
      setError(caught);
    }
  }
  return (
    <section aria-label="固定整包候选明确处理">
      <ErrorNotice error={error ?? command.error} />
      <ErrorNotice error={inputError} />
      {action.state === "pending" && !ack && (
        <>
          {action.preview.apply_available && (
            <ResourceState
              {...capabilities}
              error={capabilityError ?? capabilities.error}
              hasData={!!capability}
              onRetry={() => void capabilities.reload()}
            />
          )}
          {available && (
            <>
              {!inputReady && !inputError && (
                <p className="small-note" role="status">
                  固定编写输入与本候选原稿尚未完成交叉核验，暂不能新采纳。
                </p>
              )}
              <p>
                明确采纳会追加正文修订并保留这份固定输入的来源关系。采纳后按当前能力限制普通编辑；文件生成与入包需分别确认。
              </p>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={checked === etag && !!etag}
                  disabled={!canResolve || !inputReady}
                  onChange={(e) =>
                    setChecked(e.target.checked ? (etag ?? "") : "")
                  }
                />
                我已核对完整原稿与拟稿，确认采用这份修改
              </label>
            </>
          )}
          <div className="review-shortcuts">
            <button
              className="button primary"
              disabled={
                !canResolve ||
                !available ||
                !inputReady ||
                !projectWritable ||
                capabilities.loading ||
                !!capabilities.error ||
                !!capabilityError ||
                checked !== etag
              }
              onClick={() => void resolve("confirm")}
            >
              {command.busy
                ? "正在取得处理结果…"
                : available
                  ? "采纳这份固定整包候选并保存新修订"
                  : "此固定整包候选暂不可采纳"}
            </button>
            <button
              className="button secondary"
              disabled={!canResolve}
              onClick={() => void resolve("reject")}
            >
              拒绝此提议
            </button>
          </div>
        </>
      )}
      {command.pending && !command.busy && (
        <div className="notice warning">
          <p>
            原操作尚未取得可信回执，原决定、候选、保存令牌与请求键均已保留。刷新后的状态不会替换原请求。
          </p>
          <button
            className="button secondary"
            disabled={command.blocked}
            onClick={() => void retry()}
          >
            恢复原固定整包候选处理结果
          </button>
        </div>
      )}
      {command.conflict && (
        <div className="notice warning">
          <p>
            原操作遇到修订冲突，候选和原稿保留；重新读取并核对后才能发起新的明确操作。
          </p>
          <button
            className="button secondary"
            disabled={command.busy || command.blocked}
            onClick={() => void refreshConflict()}
          >
            读取最新操作卡并重新核对
          </button>
        </div>
      )}
      {effective && effective.state !== "pending" && !saved && (
        <p role="status">
          此候选的实际处理结果为
          {effective.state === "rejected"
            ? "已拒绝"
            : effective.state === "expired"
              ? "已到期"
              : effective.state === "stale"
                ? "依据已变化"
                : "处理失败"}
          ；没有采纳正文。
        </p>
      )}
      {effective && saved && (
        <AdoptionReceipt
          key={`${effective.action_id}:${saved.snapshot_id}`}
          action={effective}
          saved={saved}
          input={input}
        />
      )}
    </section>
  );
}
