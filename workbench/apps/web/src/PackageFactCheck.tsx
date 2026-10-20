import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import type {
  PackageExecutionFactCheck,
  PackageExecutionInputView,
} from "./contracts";
import type { FreezeScope } from "./packageFrozenInput";
import { executionPath } from "./executionInputRecovery";
import { factCheckMessages, matchesFactCheck } from "./packageFactValidation";
import PackageFactScopeWorkspace from "./PackageFactScopeWorkspace";
type Props = {
  scope: FreezeScope;
  frozenId: string;
  prepared: PackageExecutionInputView;
};
export default function PackageFactCheck(props: Props) {
  return (
    <Check
      key={JSON.stringify([
        props.scope,
        props.frozenId,
        props.prepared.manifest.id,
        props.prepared.digest,
      ])}
      {...props}
    />
  );
}
function Check({ scope, frozenId, prepared }: Props) {
  const [result, setResult] = useState<PackageExecutionFactCheck | null>(null),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  const active = useRef(false),
    running = useRef(false);
  const path = `${executionPath(scope, frozenId)}/${prepared.manifest.id}/fact-check`,
    available = supportsApi("POST", path);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function check() {
    if (running.current || !available) return;
    running.current = true;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const { data } = await api<PackageExecutionFactCheck>(path, {
        method: "POST",
        body: { execution_input_digest: prepared.digest },
      });
      if (!matchesFactCheck(data, scope, frozenId, prepared))
        throw new Error("事实核对响应身份、数量或资格边界不符，未采纳。");
      if (active.current) setResult(data);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <section
      className="package-frozen-input__fact-check"
      aria-label="事实依据核对"
    >
      <h6>事实依据核对</h6>
      <p>
        核对当前事实的确认决定、原页与来源。主体和标段范围仍须明确；核对不验证原件字节，也不授予执行资格。
      </p>
      <button
        className="button secondary"
        type="button"
        disabled={busy || !available}
        onClick={() => void check()}
      >
        {busy ? "正在核对事实依据…" : "核对事实依据"}
      </button>
      {!available && <p>当前服务尚未提供事实核对。</p>}
      {error != null && <ErrorNotice error={error} />}
      {result && (
        <div role="status">
          <p>
            当前 {result.fact_count} 条事实，{result.provenance_verified_count}{" "}
            条依据链相符。事实执行资格仍未通过。
          </p>
          {!result.matches_prepared_context && (
            <p>当前上下文已变化，此观察不能替换原准备快照；请先核对变化。</p>
          )}
          {!result.fact_count && (
            <p>当前尚无可核对事实，不能默认无事实要求。</p>
          )}
          <p>
            核对时间：{new Date(result.checked_at).toLocaleString()}
            。原件字节未重核。
          </p>
          {result.fact_count > 0 && (
            <details>
              <summary>逐项核对结果</summary>
              <ul>
                {result.fact_checks.map((item) => (
                  <li key={item.fact_id}>
                    <p>
                      事实编号：<code>{item.fact_id}</code> ·{" "}
                      {item.provenance_status === "verified"
                        ? "依据链相符"
                        : "依据待核实"}
                    </p>
                    <ul>
                      {item.blockers.map((code) => (
                        <li key={code}>{factCheckMessages[code]}</li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      <PackageFactScopeWorkspace
        scope={scope}
        frozenId={frozenId}
        prepared={prepared}
        factIds={
          result?.matches_prepared_context
            ? result.fact_checks.map((x) => x.fact_id)
            : []
        }
      />
    </section>
  );
}
