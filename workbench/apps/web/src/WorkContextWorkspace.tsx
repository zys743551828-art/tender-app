import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type {
  AuthoringWorkContext,
  PackageWorkContext,
  WorkContextDraftSelection,
} from "./contracts";
import { ErrorNotice, LoadingSkeleton } from "./components";
import { jsonDigest } from "./editorSchema";
import type { PackageNavigationTarget } from "./packageNavigation";
import { WorkContextAuthoringDetails } from "./WorkContextAuthoringDetails";
import { WorkContextChoices } from "./WorkContextChoices";
import { WorkContextReviewDetails } from "./WorkContextReviewDetails";
import { WorkContextSubmissionDetails } from "./WorkContextSubmissionDetails";
import { WorkContextSummary } from "./WorkContextSummary";
import { validateAuthoringWorkContext } from "./workContextAuthoringProtocol";
import { validatePackageWorkContext } from "./workContextProtocol";
import {
  parseWorkContextLocation,
  workContextPath,
  workContextStages,
  type WorkContextPosition,
  type WorkContextTarget,
} from "./workContextNavigation";
import "./WorkContext.css";

type Props = {
  bidId: string;
  memberId: string;
  route: string;
  onLocation: (position: WorkContextPosition, replace?: boolean) => void;
  onOpenDraft: (id: string) => void;
  onOpenPackage: (target: PackageNavigationTarget) => void;
};
export function WorkContextWorkspace(p: Props) {
  const parsed = useMemo(
    () => parseWorkContextLocation(p.bidId, p.route),
    [p.bidId, p.route],
  );
  if (!parsed.ok)
    return (
      <section className="panel">
        <h2>阶段链接无法恢复</h2>
        <p className="notice warning">{parsed.message}</p>
        <button
          type="button"
          className="button secondary"
          onClick={() =>
            p.onLocation({ stage: "draft_snapshot", selected: null })
          }
        >
          重新选择阶段记录
        </button>
      </section>
    );
  if (!supportsApi("GET", `/bids/${p.bidId}/work-contexts/choices`))
    return (
      <section className="panel">
        <h2>稿件与阶段</h2>
        <p>当前服务尚未提供完整阶段读取能力。</p>
      </section>
    );
  const position = parsed.position;
  return (
    <div className="work-context-workspace">
      <section className="panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">稿件与阶段</span>
            <h2>选择你正在核对的稿件阶段</h2>
            <p className="muted">
              草稿、生成文件、整包核查和实交各自保留原记录。每次选择都固定到明确身份。
            </p>
          </div>
        </div>
        <fieldset className="work-context-stages">
          <legend>记录阶段</legend>
          {workContextStages.map(([kind, label]) => (
            <label key={kind} data-selected={kind === position.stage}>
              <input
                type="radio"
                name="work-context-stage"
                checked={kind === position.stage}
                onChange={() => p.onLocation({ stage: kind, selected: null })}
              />
              {label}
            </label>
          ))}
        </fieldset>
      </section>
      <WorkContextChoices
        key={`${p.memberId}:${p.bidId}:${position.stage}`}
        bidId={p.bidId}
        kind={position.stage}
        selected={position.selected}
        onSelect={(target) =>
          p.onLocation({ stage: target.kind, selected: target })
        }
      />
      {position.selected ? (
        <SelectedWorkContext
          key={`${p.memberId}:${p.bidId}:${JSON.stringify(position.selected)}`}
          {...p}
          target={position.selected}
        />
      ) : (
        <section className="panel">
          <h2>尚未选择记录</h2>
          <p>
            从目录选择一条记录后，这里会显示它的保存状态、核查范围及可追溯原文。
          </p>
        </section>
      )}
    </div>
  );
}
function SelectedWorkContext(p: Props & { target: WorkContextTarget }) {
  const [context, setContext] = useState<
      AuthoringWorkContext | PackageWorkContext | null
    >(null),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false),
    [original, setOriginal] = useState(false);
  const active = useRef(false),
    pending = useRef(false),
    ticket = useRef(0);
  const { bidId, target } = p;
  const load = useCallback(async () => {
    if (!active.current || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    const request = ++ticket.current;
    try {
      const { data } = await api<unknown>(workContextPath(bidId, target));
      const checked =
        target.kind === "draft_snapshot" || target.kind === "build"
          ? await validateAuthoringWorkContext(data, bidId, target)
          : await validatePackageWorkContext(data, bidId, target);
      if (active.current && request === ticket.current) {
        setContext(checked);
        setOriginal(false);
      }
    } catch (failure) {
      if (active.current && request === ticket.current) setError(failure);
    } finally {
      if (active.current && request === ticket.current) {
        pending.current = false;
        setBusy(false);
      }
    }
  }, [bidId, target]);
  useEffect(() => {
    active.current = true;
    void load();
    const requests = ticket;
    return () => {
      active.current = false;
      pending.current = false;
      requests.current++;
    };
  }, [load]);
  async function openSnapshot(selection: WorkContextDraftSelection) {
    const request = ticket.current,
      selectionDigest = await jsonDigest(selection);
    if (active.current && request === ticket.current)
      p.onLocation({
        stage: "draft_snapshot",
        selected: {
          kind: "draft_snapshot",
          id: selection.snapshot_id,
          selectionDigest,
        },
      });
  }
  return (
    <section
      aria-label="当前明确选择的阶段记录"
      className="work-context-selected"
    >
      <div className="work-context-summary__actions">
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={() => void load()}
        >
          重读同一记录
        </button>
        <button
          type="button"
          className="text-button"
          onClick={() => p.onLocation({ stage: target.kind, selected: null })}
        >
          清除本次选择
        </button>
      </div>
      {busy && !context && (
        <LoadingSkeleton text="正在核对完整选择身份与所保存记录…" rows={4} />
      )}
      {error != null && (
        <ErrorNotice error={error} onRetry={() => void load()} />
      )}
      {error != null && (
        <p className="notice warning">
          未能取得这次完整读取。
          {context
            ? "下方保留上次核验的历史内容。"
            : "原选择仍保留，可核对链接或重新选择目录记录。"}
        </p>
      )}
      {context?.version === "authoring-work-context/1" && (
        <WorkContextAuthoringDetails
          key={`${context.selection_digest}:${context.observation_digest}`}
          context={context}
          onOpenDraft={p.onOpenDraft}
          onOpenSnapshot={(s) => void openSnapshot(s)}
          onOpenPackage={p.onOpenPackage}
        />
      )}
      {context?.version === "package-work-context/1" && (
        <>
          <WorkContextSummary
            key={`${context.selection_digest}:${context.observation_digest}`}
            context={context}
            onOpenOriginal={() => setOriginal(true)}
            onOpenPackage={p.onOpenPackage}
          />
          {original && context.selection.kind === "package_review_run" && (
            <WorkContextReviewDetails
              memberId={p.memberId}
              selection={context.selection}
              onClose={() => setOriginal(false)}
            />
          )}
          {original && context.selection.kind === "package_submission" && (
            <WorkContextSubmissionDetails
              selection={context.selection}
              onClose={() => setOriginal(false)}
            />
          )}
        </>
      )}
    </section>
  );
}
