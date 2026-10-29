import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import type { useKnowledgeReferenceTargets } from "./useKnowledgeReferenceTargets";
import "./KnowledgeReferenceTargets.css";

export function KnowledgeReferenceTargets({
  targets,
  value,
  onChange,
  disabled,
}: {
  targets: ReturnType<typeof useKnowledgeReferenceTargets>;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  const selected = targets.items.find((item) => item.id === value);
  return (
    <div className="knowledge-source knowledge-reference-targets">
      <ResourceState
        {...targets.resource}
        hasData={targets.ready}
        onRetry={() => void targets.resource.reload()}
      />
      {targets.mismatch && (
        <p className="notice error" role="alert">
          核查目录与当前项目不匹配，未开放选择。请重新读取项目。
        </p>
      )}
      <label>
        关联的整包核查
        <select
          value={value}
          disabled={disabled || !targets.ready}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">明确选择一次核查</option>
          {targets.items.map((item) => (
            <option key={item.id} value={item.id}>
              {new Date(item.created_at).toLocaleString("zh-CN")} · 核查{" "}
              {item.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </label>
      {targets.ready && !targets.items.length && (
        <p className="small-empty">此项目还没有可关联的整包核查记录。</p>
      )}
      {targets.hasMore && (
        <button
          type="button"
          className="text-button"
          disabled={disabled || targets.busy}
          onClick={() => void targets.next()}
        >
          {targets.busy ? "正在读取核查目录…" : "加载更多核查记录"}
        </button>
      )}
      <ErrorNotice error={targets.error} onRetry={() => void targets.next()} />
      {selected && (
        <details>
          <summary>核对所选核查与固定输入</summary>
          <dl>
            <dt>核查记录</dt>
            <dd className="digest">{selected.id}</dd>
            <dt>投标包修订</dt>
            <dd className="digest">{selected.revision_id}</dd>
            <dt>要求清单</dt>
            <dd className="digest">{selected.inventory_id}</dd>
            <dt>输入摘要</dt>
            <dd className="digest">{selected.input_digest}</dd>
          </dl>
        </details>
      )}
      <p className="small-note">
        参考将另行关联到这一次核查，不修改已冻结的输入、机器判断或人工意见。
      </p>
    </div>
  );
}
