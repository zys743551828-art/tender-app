import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import { matchesExecutionContext } from "./packageReviewContext";
import type {
  PackageReviewInputPreview,
  PackageReviewOriginalVerification as Observation,
} from "./contracts";

type Props = {
  preview: PackageReviewInputPreview;
  disabled?: boolean;
  onVerified?: (result: Observation | null) => void;
};

export function PackageOriginalVerification({
  preview,
  onVerified,
  disabled = false,
}: Props) {
  const selected = preview.manifest;
  const target = selected.target.manifest;
  const path = `/bids/${selected.bid_id}/packages/${target.package_id}/revisions/${target.revision_id}/requirement-inventories/${selected.inventory.manifest.id}/review-original-verification`;
  const available = supportsApi("POST", path);
  const generation = useRef(0);
  const active = useRef(preview);
  active.current = preview;
  const [state, setState] = useState<{
    input: PackageReviewInputPreview;
    busy?: boolean;
    result?: Observation;
    error?: unknown;
  } | null>(null);
  useEffect(() => {
    generation.current += 1;
    setState(null);
    return () => {
      generation.current += 1;
    };
  }, [preview]);
  const current = state?.input === preview ? state : null;

  async function verify() {
    if (disabled || !available || current?.busy) return;
    onVerified?.(null);
    const ticket = ++generation.current;
    const input = preview;
    setState({ input, busy: true });
    try {
      const { data } = await api<Observation>(path, {
        method: "POST",
        body: {
          package_digest: selected.target.digest,
          inventory_digest: selected.inventory.digest,
          coverage_attempt_id: selected.coverage?.manifest.id ?? null,
          coverage_digest: selected.coverage?.digest ?? null,
          input_digest: preview.digest,
        },
      });
      if (ticket !== generation.current || active.current !== input) return;
      const expected = (["target", "authority"] as const).flatMap((role) =>
        selected[role].manifest.members.map((member) => ({ role, member })),
      );
      if (
        !matchesExecutionContext(
          data.execution_context,
          input.digest,
          data.checked_at,
        ) ||
        data.kind !== "observation" ||
        data.input_digest !== input.digest ||
        data.originals_verified !== true ||
        data.review_ready !== false ||
        data.launch_available !== false ||
        typeof data.checked_at !== "string" ||
        !Number.isFinite(Date.parse(data.checked_at)) ||
        !Array.isArray(data.blockers) ||
        !data.blockers.length ||
        data.blockers.length !== input.blockers.length ||
        data.blockers.some((code, index) => code !== input.blockers[index]) ||
        !Array.isArray(data.originals) ||
        data.originals.length !== expected.length ||
        data.originals.some((record, index) => {
          const { role, member } = expected[index];
          return (
            record.role !== role ||
            record.member_id !== member.member_id ||
            record.document_version_id !== member.document_version_id ||
            record.parse_run_id !== member.parse.parse_run_id ||
            record.file_digest !== member.file_digest ||
            !Number.isSafeInteger(record.byte_size) ||
            record.byte_size < 0
          );
        })
      )
        throw new Error("原件核验响应与所选输入不一致，未采用该结果。");
      setState({ input, result: data });
      onVerified?.(data);
    } catch (error) {
      if (ticket === generation.current && active.current === input)
        setState({ input, error });
    }
  }

  return (
    <div>
      <h5>原件字节核验</h5>
      <p>
        读取所选两份包内的全部原件，核对大小和摘要。核验结果仅为本次观察，不启动正式评审。
      </p>
      {!available && <p>当前服务尚未提供原件字节核验。</p>}
      <button
        type="button"
        disabled={disabled || !available || !!current?.busy}
        onClick={() => void verify()}
      >
        {current?.busy ? "正在核对原件…" : "核对所选原件"}
      </button>
      {current?.error != null && (
        <ErrorNotice error={current.error} onRetry={() => void verify()} />
      )}
      {current?.result && (
        <div>
          <p role="status">
            本次已核对 {current.result.originals.length}{" "}
            个成员原件，正式评审仍未就绪。核验时间：
            {new Date(current.result.checked_at).toLocaleString()}
            。后续执行需重新核验。
          </p>
          <details>
            <summary>本次候选执行上下文</summary>
            <p>
              用途：标前合规核对。事实{" "}
              {current.result.execution_context.fact_count} 条，其中人工确认为{" "}
              {current.result.execution_context.confirmed_fact_count}{" "}
              条；事实输入资格尚未核验。
            </p>
            <p>
              方法、事实与来源摘要已纳入本次核对；候选尚未持久化，不能用于正式执行或评分。
            </p>
            <p>上下文摘要 {current.result.execution_context.semantic_digest}</p>
          </details>
        </div>
      )}
    </div>
  );
}
