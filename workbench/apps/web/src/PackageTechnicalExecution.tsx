import { useEffect, useRef, useState } from "react";
import { api, ApiError, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import type { PackageTechnicalScopeView } from "./contracts";
import {
  technicalScaleConfigured,
  technicalScales,
  type TechnicalScaleChoice,
} from "./packageTechnicalEligibilityCatalog";
import {
  technicalExecutionCheckRequest,
  validateTechnicalExecutionContext,
  validateTechnicalExecutionRefusal,
  type PackageTechnicalExecutionContext,
  type PackageTechnicalExecutionRefusal,
} from "./packageTechnicalExecutionProtocol";
import { TechnicalPager } from "./PackageTechnicalScopeSnapshot";

export function PackageTechnicalExecution({
  saved,
}: {
  saved: PackageTechnicalScopeView;
}) {
  return <ExecutionWorkspace key={saved.digest} saved={saved} />;
}

function ExecutionWorkspace({ saved }: { saved: PackageTechnicalScopeView }) {
  const scope = saved.manifest.preview.manifest.scope;
  const base = `/bids/${scope.bid_id}/packages/${scope.package_id}/revisions/${scope.revision_id}/technical-scopes/${saved.manifest.id}`;
  const [context, setContext] = useState<{
    data: PackageTechnicalExecutionContext;
    etag: string;
  } | null>(null);
  const [refusal, setRefusal] =
    useState<PackageTechnicalExecutionRefusal | null>(null);
  const [scales, setScales] = useState<TechnicalScaleChoice[]>([]);
  const [scaleId, setScaleId] = useState("");
  const [scaleStatus, setScaleStatus] = useState("");
  const [gapPage, setGapPage] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const active = useRef(false),
    running = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  function clear() {
    setContext(null);
    setRefusal(null);
    setError(null);
    setGapPage(0);
  }
  async function run(action: () => Promise<void>) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function loadScales() {
    await run(async () => {
      clear();
      setScaleId("");
      setScales([]);
      setScaleStatus("");
      const capabilities = await api<unknown>("/technical-scale-capabilities");
      const configured = technicalScaleConfigured(capabilities.data);
      if (!active.current) return;
      if (!configured) {
        setScaleStatus("当前服务尚未配置有据满分登记，仍可核对其他执行缺口。");
        return;
      }
      const response = await api<unknown>(
        `/bids/${scope.bid_id}/technical-scales`,
      );
      const choices = technicalScales(response.data, scope.bid_id).filter(
        (entry) => entry.purpose === "current_prebid",
      );
      if (!active.current) return;
      setScales(choices);
      setScaleStatus(
        "已读取量尺目录；仅展示当前用途的候选记录，选择后仍需核对原文和适用性。",
      );
    });
  }
  async function check() {
    await run(async () => {
      clear();
      const query = scaleId ? `?scale_id=${encodeURIComponent(scaleId)}` : "";
      const response = await api<unknown>(`${base}/execution-context${query}`);
      const data = await validateTechnicalExecutionContext(
        response.data,
        response.etag,
        saved,
        scaleId || null,
      );
      if (active.current) setContext({ data, etag: response.etag! });
    });
  }
  async function verifyRefusal() {
    if (!context) return;
    await run(async () => {
      setRefusal(null);
      try {
        await api<unknown>(`${base}/executions`, {
          method: "POST",
          etag: context.etag,
          body: technicalExecutionCheckRequest(context.data),
        });
      } catch (failure) {
        if (
          failure instanceof ApiError &&
          failure.code === "PACKAGE_TECHNICAL_EXECUTION_BLOCKED"
        ) {
          const checked = validateTechnicalExecutionRefusal(
            failure,
            context.data,
          );
          if (active.current) setRefusal(checked);
          return;
        }
        // A stale condition or network failure cannot become a zero-call receipt.
        if (active.current) setContext(null);
        throw failure;
      }
      if (active.current) setContext(null);
      throw new Error("服务器返回了当前协议不支持的执行结果，请核对任务记录。");
    });
  }
  const available = supportsApi("GET", `${base}/execution-context`);
  return (
    <section
      className="technical-scope__eligibility"
      aria-label="整包技术正式执行"
    >
      <h4>正式执行条件</h4>
      <p>
        针对这份已保存范围检查当前执行条件。正式执行尚未开放，完整图文、必要范围、模型方法和量尺都须分别具备有效依据。
      </p>
      {!available && <p>当前服务版本尚未提供此执行检查，已保存范围仍保留。</p>}
      <fieldset>
        <legend>本次执行检查使用的量尺</legend>
        <button
          type="button"
          disabled={
            busy || !supportsApi("GET", "/technical-scale-capabilities")
          }
          onClick={() => void loadScales()}
        >
          读取执行检查可用量尺
        </button>
        {scaleStatus && <p role="status">{scaleStatus}</p>}
        <label>
          技术满分依据
          <select
            aria-label="执行检查所用量尺"
            disabled={busy}
            value={scaleId}
            onChange={(event) => {
              if (running.current) return;
              setScaleId(event.target.value);
              clear();
            }}
          >
            <option value="">不选择，满分保持未知</option>
            {scales.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.scale_description || "量尺记录"} ·{" "}
                {new Date(entry.created_at).toLocaleString("zh-CN", {
                  timeZone: "Asia/Shanghai",
                  hour12: false,
                })}{" "}
                · {entry.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
      </fieldset>
      {error != null && <ErrorNotice error={error} />}
      <button
        type="button"
        disabled={busy || !available}
        onClick={() => void check()}
      >
        {busy ? "正在核对执行条件…" : "读取正式执行条件"}
      </button>
      {context && (
        <div
          className="technical-scope__eligibility-result"
          aria-label="正式执行条件结果"
        >
          <h5>当前正式执行被阻止</h5>
          <p>
            条件观察时间：
            {new Date(context.data.qualification.observed_at).toLocaleString(
              "zh-CN",
              { timeZone: "Asia/Shanghai", hour12: false },
            )}
            （北京时间）。资料或依据变化后须重新检查。
          </p>
          <dl>
            <dt>执行基础</dt>
            <dd>
              {context.data.producer.software_foundation === "installed"
                ? "已安装隔离验证基础，正式执行资格仍未成立"
                : "当前服务未安装整包执行基础"}
            </dd>
            <dt>真实模型运行</dt>
            <dd>尚未配置有资格的模型运行端口</dd>
            <dt>完整必要范围及图文依据</dt>
            <dd>尚未通过独立权威核验</dd>
            <dt>有据技术满分</dt>
            <dd>
              {context.data.qualification.denominator.maximum_usable
                ? `${context.data.qualification.denominator.technical_maximum} 分 · ${context.data.qualification.denominator.scale_description}`
                : "未知"}
            </dd>
            <dt>官方聚合规则</dt>
            <dd>尚不可执行</dd>
            <dt>正式有效独立判断</dt>
            <dd>每个适用条款仍需 3 次；失败和重试不计入次数</dd>
            <dt>正式分数及训练资格</dt>
            <dd>均不可生成</dd>
          </dl>
          <h5>执行缺口（{context.data.blockers.length}）</h5>
          <ul>
            {context.data.blockers
              .slice(gapPage * 20, (gapPage + 1) * 20)
              .map((gap) => (
                <li key={gap.id}>{gap.message}</li>
              ))}
          </ul>
          {context.data.blockers.length > 20 && (
            <TechnicalPager
              page={gapPage}
              total={context.data.blockers.length}
              onPage={setGapPage}
              label="执行缺口"
            />
          )}
          <p>
            可向服务核对上述正式执行限制。本次核对预算为
            0；当前服务会在创建任务和模型请求前拒绝申请。
          </p>
          <button
            type="button"
            disabled={busy || !supportsApi("POST", `${base}/executions`)}
            onClick={() => void verifyRefusal()}
          >
            核对正式执行限制
          </button>
          {refusal && (
            <div role="status" aria-label="正式执行拒绝回执">
              <p>服务已确认本范围的正式执行仍被阻止。</p>
              <p>本次创建任务：0；发送模型请求：0。</p>
              <p>回执编号：{refusal.requestId}</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
