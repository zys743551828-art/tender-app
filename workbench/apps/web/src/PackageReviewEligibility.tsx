import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import PackageExecutionInputWorkspace from "./PackageExecutionInputWorkspace";
import { freezePath } from "./packageFrozenInput";
import type { FreezeScope } from "./packageFrozenInput";
import type {
  PackageReviewEligibilityObservation,
  PackageReviewFrozenInputView,
} from "./contracts";
import {
  eligibilityMessages,
  matchesEligibility,
} from "./packageEligibilityObservation";

export default function PackageReviewEligibility({
  scope,
  frozen,
}: {
  scope: FreezeScope;
  frozen: PackageReviewFrozenInputView;
}) {
  const path = `${freezePath(scope)}/${frozen.manifest.id}/execution-check`;
  const available = supportsApi("POST", path);
  const generation = useRef(0);
  const active = useRef<PackageReviewFrozenInputView | null>(frozen);
  active.current = frozen;
  const [state, setState] = useState<{
    input: PackageReviewFrozenInputView;
    busy?: boolean;
    result?: PackageReviewEligibilityObservation;
    error?: unknown;
  } | null>(null);
  useEffect(() => {
    active.current = frozen;
    generation.current++;
    setState(null);
    return () => {
      active.current = null;
    };
  }, [frozen, path]);
  const current = state?.input === frozen ? state : null;
  async function check() {
    if (!available || current?.busy) return;
    const input = frozen,
      ticket = ++generation.current;
    setState({ input, busy: true });
    try {
      const { data } = await api<PackageReviewEligibilityObservation>(path, {
        method: "POST",
        body: { frozen_digest: input.digest },
      });
      if (ticket !== generation.current || active.current !== input) return;
      if (!matchesEligibility(data, input))
        throw new Error(
          "当前条件响应与所选冻结输入或观察边界不符，未采用该结果。",
        );
      setState({ input, result: data });
    } catch (error) {
      if (ticket === generation.current && active.current === input)
        setState({ input, error });
    }
  }
  return (
    <div className="package-frozen-input__eligibility">
      <h5>复核当前条件</h5>
      <p>
        针对记录 <code>{frozen.manifest.id}</code>{" "}
        检查当前身份、来源、事实、方法与精确解析引用。只读观察，不创建任务。
      </p>
      <p>
        原件字节未在此入口重核；观察不能作为启动或发布许可，正式发布须再次核对。
      </p>
      {!available && <p>当前服务尚未提供冻结输入条件复核。</p>}
      <button
        className="button secondary"
        type="button"
        disabled={!available || !!current?.busy}
        onClick={() => void check()}
      >
        {current?.busy ? "正在复核当前条件…" : "复核此冻结输入的当前条件"}
      </button>
      {current?.error != null && (
        <ErrorNotice error={current.error} onRetry={() => void check()} />
      )}
      {current?.result && (
        <div role="status">
          <p>
            暂不可正式执行或发布。复核时间：
            {new Date(current.result.checked_at).toLocaleString()}。
          </p>
          <p>
            {current.result.parse_evidence_status === "matched"
              ? "当前解析证据与冻结引用相符。"
              : "当前解析证据无法与冻结引用匹配。"}
            原件字节未重核。
          </p>
          <ul>
            {current.result.blockers.map((code) => (
              <li key={code}>{eligibilityMessages[code]}</li>
            ))}
          </ul>
        </div>
      )}
      <PackageExecutionInputWorkspace
        scope={scope}
        frozen={frozen}
        candidate={current?.result ?? null}
        disabled={!!current?.busy}
      />
    </div>
  );
}
