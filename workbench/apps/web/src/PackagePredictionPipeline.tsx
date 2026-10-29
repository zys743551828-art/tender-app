import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ErrorNotice } from "./components";
import { PackageUnifiedReport } from "./PackageUnifiedReport";

type Props = { bidId: string; scopeId: string; memberId: string };
type Receipt = {
  schema: string;
  actor_id: string;
  bid_id: string;
  scope_id: string;
  state: string;
  command_id: string | null;
  certificate_id: string | null;
  review_id: string | null;
  context_digest: string | null;
  report_ready: boolean;
  provider_requests: number;
};
const states: Record<string, string> = {
  waiting_start: "等待从现有核查入口开始评审",
  waiting_review: "等待本冻结范围的核查完成",
  review_context_mismatch: "核查文档集合或摘要与冻结技术范围不一致",
  review_failed: "核查失败或取消，不能自动预测",
  certificate_missing: "没有同范围、同操作者且仍有效的认证",
  certificate_ambiguous: "存在多个合格认证，已阻止自动选择",
  awaiting_submission: "资料与唯一认证就绪，等待协调器接受",
  accepted: "启动意图已冻结，等待恢复提交",
  queued: "预测已排队",
  running: "预测计算中",
  retrying: "等待原任务重试",
  awaiting_publication: "等待最终资格与意图复验",
  ready: "四部分统一报告可生成，读取时仍会复验",
  published: "预测已发布",
  blocked: "固定资格或输入失效，未发布新结果",
  context_changed: "固定评审上下文已变化，不自动改选输入或认证",
  report_blocked: "统一报告依据已失效",
  failed: "预测任务失败",
  cancel_requested: "正在取消",
  cancelled: "预测意图已取消",
  stale: "历史预测已失效",
};
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function PackagePredictionPipeline(p: Props) {
  return <View key={`${p.memberId}:${p.bidId}:${p.scopeId}`} {...p} />;
}
function View(p: Props) {
  const [value, setValue] = useState<Receipt | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(false),
    serial = useRef(0);
  const base = `/bids/${p.bidId}/technical-scopes/${p.scopeId}/prediction-pipeline`;
  const load = useCallback(
    async (action: "read" | "advance" | "cancel", command?: string) => {
      const n = ++serial.current;
      setValue(null);
      setError(null);
      setBusy(true);
      try {
        const { data: v } = await api<Receipt>(
          action === "read" ? base : `${base}/${action}`,
          action === "read"
            ? {}
            : {
                method: "POST",
                body: action === "cancel" ? { command_id: command } : {},
              },
        );
        const bound = v.command_id !== null;
        if (
          v.schema !== "package-prediction-pipeline/1" ||
          v.actor_id !== p.memberId ||
          v.bid_id !== p.bidId ||
          v.scope_id !== p.scopeId ||
          !Object.hasOwn(states, v.state) ||
          v.provider_requests !== 0 ||
          v.report_ready !== (v.state === "ready") ||
          (bound
            ? !uuid.test(v.command_id!) ||
              !uuid.test(v.certificate_id ?? "") ||
              !uuid.test(v.review_id ?? "") ||
              !/^[a-f0-9]{64}$/.test(v.context_digest ?? "")
            : v.certificate_id !== null ||
              v.review_id !== null ||
              v.context_digest !== null ||
              v.report_ready)
        )
          throw new Error("自动预测回执身份或状态不符。");
        if (alive.current && serial.current === n) setValue(v);
      } catch (e) {
        if (alive.current && serial.current === n) setError(e);
      } finally {
        if (alive.current && serial.current === n) setBusy(false);
      }
    },
    [base, p.bidId, p.scopeId, p.memberId],
  );
  useEffect(() => {
    alive.current = true;
    void load("read");
    return () => {
      alive.current = false;
    };
  }, [load]);
  return (
    <section aria-label="项目自动预测推进">
      <h4>项目自动预测推进</h4>
      <p>
        沿用资料就绪或开始核查意图，只选择唯一有效认证；隐藏分数不停止内部预测。
      </p>
      <button disabled={busy} onClick={() => void load("read")}>
        刷新自动推进状态
      </button>
      <button disabled={busy} onClick={() => void load("advance")}>
        恢复已有评审意图
      </button>
      <button
        disabled={
          busy ||
          !value?.command_id ||
          value.state === "ready" ||
          value.state === "stale"
        }
        onClick={() => void load("cancel", value?.command_id ?? undefined)}
      >
        取消自动预测意图
      </button>
      {busy && <p role="status">正在读取当前意图…</p>}
      {error != null && <ErrorNotice error={error} />}
      {value && <p role="status">{states[value.state]}</p>}
      {value?.report_ready && (
        <PackageUnifiedReport
          bidId={p.bidId}
          scopeId={p.scopeId}
          commandId={value.command_id!}
          initialReviewId={value.review_id!}
        />
      )}
    </section>
  );
}
