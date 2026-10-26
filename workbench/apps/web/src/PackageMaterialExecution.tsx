import { PackagePredictionPipeline } from "./PackagePredictionPipeline";
import { PackageFormalPrediction } from "./PackageFormalPrediction";
import { MaterialQualificationReview } from "./MaterialQualificationReview";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, supportsApi } from "./api";
import type { PackageTechnicalScopeView } from "./contracts";
import { ErrorNotice } from "./components";
import {
  invalidMaterial,
  materialContext,
  materialReceipt,
  materialStorageKey,
  readMaterialPending,
  validMaterialRequest,
  type MaterialContext,
  type MaterialReceipt,
  type MaterialReference,
  type PendingMaterialCheck,
} from "./packageMaterialExecutionProtocol";

export function PackageMaterialExecution({
  saved,
  memberId,
}: {
  saved: PackageTechnicalScopeView;
  memberId: string;
}) {
  return (
    <Workspace
      key={`${memberId}:${saved.digest}`}
      saved={saved}
      memberId={memberId}
    />
  );
}
function Workspace({
  saved,
  memberId,
}: {
  saved: PackageTechnicalScopeView;
  memberId: string;
}) {
  const s = saved.manifest.preview.manifest.scope;
  const base = `/bids/${s.bid_id}/packages/${s.package_id}/revisions/${s.revision_id}/technical-scopes/${saved.manifest.id}`;
  const [context, setContext] = useState<{
    data: MaterialContext;
    etag: string;
  } | null>(null);
  const [pending, setPending] = useState<PendingMaterialCheck | null>(null);
  const [receipt, setReceipt] = useState<MaterialReceipt | null>(null);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [corrupt, setCorrupt] = useState(false),
    [busy, setBusy] = useState(false);
  const [budget, setBudget] = useState("0");
  const [reference, setReference] = useState<MaterialReference>({
    seal_id: "",
    seal_digest: "",
    input_digest: "",
    quote_id: "",
    quote_digest: "",
  });
  const active = useRef(false),
    running = useRef(false);
  useEffect(() => {
    active.current = true;
    try {
      setPending(readMaterialPending(saved, memberId));
    } catch (e) {
      setError(e);
      setCorrupt(true);
    }
    return () => {
      active.current = false;
    };
  }, [saved, memberId]);
  async function run(action: () => Promise<void>) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      if (active.current) setError(e);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function load() {
    await run(async () => {
      setContext(null);
      const r = await api<unknown>(`${base}/material-execution-context`);
      const data = await materialContext(r.data, r.etag, saved);
      if (active.current) setContext({ data, etag: r.etag! });
    });
  }
  async function send(old?: PendingMaterialCheck) {
    await run(async () => {
      let p = old;
      if (!p) {
        if (!context) invalidMaterial();
        const t = context.data.target;
        const body = {
          version: "package-material-execution-check/1" as const,
          scope_digest: saved.digest,
          profile_digest: t.profile_digest,
          serializer_digest: t.serializer_digest,
          judgment_method_digest: t.judgment_method_digest,
          input_reference: Object.values(reference).every((v) => v === "")
            ? null
            : reference,
          budget_usd: budget,
        };
        if (!validMaterialRequest(body, saved.digest)) invalidMaterial();
        p = { key: crypto.randomUUID(), etag: context.etag, body };
        sessionStorage.setItem(
          materialStorageKey(saved, memberId),
          JSON.stringify(p),
        );
        setPending(p);
      }
      try {
        const response = await api<unknown>(
          `${base}/material-execution-checks`,
          {
            method: "POST",
            key: p.key,
            etag: p.etag,
            body: p.body,
          },
        );
        const checked = await materialReceipt(
          response.data,
          p,
          saved,
          memberId,
        );
        if (active.current) setReceipt(checked);
      } catch (failure) {
        if (
          active.current &&
          failure instanceof ApiError &&
          failure.status === 412 &&
          failure.code === "REVISION_CONFLICT"
        )
          setStale(true);
        throw failure;
      }
    });
  }
  const labels: Record<keyof MaterialReference, string> = {
    seal_id: "材料封印编号",
    seal_digest: "材料封印摘要",
    input_digest: "完整输入摘要",
    quote_id: "报价记录编号",
    quote_digest: "报价记录摘要",
  };
  return (
    <section aria-label="完整材料执行申请">
      <h4>完整材料执行申请</h4>
      <PackagePredictionPipeline
        bidId={s.bid_id}
        scopeId={saved.manifest.id}
        memberId={memberId}
      />
      <PackageFormalPrediction
        bidId={s.bid_id}
        scopeId={saved.manifest.id}
        memberId={memberId}
      />
      <MaterialQualificationReview
        base={base}
        scopeId={saved.manifest.id}
        scopeDigest={saved.digest}
        memberId={memberId}
      />
      <p>
        沿用 DeepSeek / deepseek-flash
        配置，不代表该型号能力已经验收。当前只能保存被阻止的申请回执，不会创建评分任务、预留费用或发送模型请求。
      </p>
      {error != null && <ErrorNotice error={error} />}
      <button
        disabled={
          busy ||
          corrupt ||
          !!pending ||
          !supportsApi("GET", `${base}/material-execution-context`)
        }
        onClick={() => void load()}
      >
        读取完整材料执行条件
      </button>
      {context && (
        <>
          <p>当前资格尚未成立；材料和报价引用将保持未核验。</p>
          <fieldset disabled={busy || !!pending}>
            <legend>固定材料引用（可全部留空以核对缺失项）</legend>
            {(Object.keys(labels) as (keyof MaterialReference)[]).map((k) => (
              <label key={k}>
                {labels[k]}
                <input
                  value={reference[k]}
                  onChange={(e) =>
                    setReference({ ...reference, [k]: e.target.value })
                  }
                />
              </label>
            ))}
            <label>
              申请预算上限（USD）
              <input
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
              />
            </label>
          </fieldset>
          <button
            disabled={
              busy ||
              corrupt ||
              !!pending ||
              !supportsApi("POST", `${base}/material-execution-checks`)
            }
            onClick={() => void send()}
          >
            保存受阻申请并核对
          </button>
        </>
      )}
      {pending && (
        <>
          <p>
            已保留原请求。网络失败不等于服务没有记录；恢复时使用相同引用和操作编号，不自动重发。
          </p>
          <button
            disabled={
              busy ||
              corrupt ||
              !supportsApi("POST", `${base}/material-execution-checks`)
            }
            onClick={() => void send(pending)}
          >
            恢复原申请回执
          </button>
        </>
      )}
      {receipt && (
        <div role="status" aria-label="完整材料受阻回执">
          <p>
            申请仍被阻止；本次核对新增任务 0、模型请求
            0，未新增费用预留。材料引用与既有账户费用状态尚未核验。
          </p>
          <p>历史回执时间：{receipt.observed_at}；不是当前执行资格。</p>
          <p>回执编号：{receipt.command_id}</p>
          <ul>
            {receipt.blockers.map((g) => (
              <li key={g.id}>{g.message}</li>
            ))}
          </ul>
        </div>
      )}
      {stale && (
        <p>服务已拒绝失效条件，未登记此次核对；可明确开始新的条件核对。</p>
      )}
      {(receipt || stale) && (
        <button
          disabled={busy}
          onClick={() => {
            try {
              sessionStorage.removeItem(materialStorageKey(saved, memberId));
              setPending(null);
              setReceipt(null);
              setContext(null);
              setStale(false);
              setError(null);
            } catch (e) {
              setError(e);
            }
          }}
        >
          开始新的条件核对
        </button>
      )}
    </section>
  );
}
