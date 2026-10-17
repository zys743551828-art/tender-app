import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  AuthoringDocument,
  AuthoringSourceReference,
  DocumentEvidenceView,
  EvidenceAuthoringReferenceView,
  MaterialView,
  RuleSetView,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";

export function AuthoringReferences({
  bidId,
  content,
  disabled,
  changeAttrs,
}: {
  bidId: string;
  content: AuthoringDocument;
  disabled: boolean;
  changeAttrs: (
    update: (attrs: AuthoringDocument["attrs"]) => AuthoringDocument["attrs"],
  ) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="coverage-details"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        本章要求与来源 · {content.attrs.rule_ids.length} 条要求／
        {content.attrs.source_refs.length} 处来源
      </summary>
      {open && (
        <div className="authoring-references">
          <p className="small-note">
            关联用于编写定位，不表示正文已经满足要求。移除本章关联不会删除响应矩阵中的要求或历史证据。
          </p>
          <AuthoringRulePicker
            bidId={bidId}
            selected={content.attrs.rule_ids}
            disabled={disabled}
            onToggle={(id, checked) =>
              changeAttrs((attrs) => ({
                ...attrs,
                rule_ids: checked
                  ? [...new Set([...attrs.rule_ids, id])]
                  : attrs.rule_ids.filter((item) => item !== id),
              }))
            }
          />
          {content.attrs.source_refs.map((ref) => (
            <div
              className="authoring-reference-row"
              key={`${ref.source_id}:${ref.source_revision}:${ref.evidence_id}`}
            >
              <EvidenceLinks ids={[ref.evidence_id]} label="查看本章来源原页" />
              <button
                className="text-button"
                disabled={disabled}
                onClick={() =>
                  changeAttrs((attrs) => ({
                    ...attrs,
                    source_refs: attrs.source_refs.filter(
                      (item) =>
                        item.evidence_id !== ref.evidence_id ||
                        item.source_id !== ref.source_id,
                    ),
                  }))
                }
              >
                移除此章关联
              </button>
            </div>
          ))}
          <AuthoringSourcePicker
            bidId={bidId}
            disabled={disabled}
            onAdd={(reference) =>
              changeAttrs((attrs) => ({
                ...attrs,
                source_refs: [
                  ...attrs.source_refs.filter(
                    (item) =>
                      item.evidence_id !== reference.evidence_id ||
                      item.source_id !== reference.source_id,
                  ),
                  reference,
                ],
              }))
            }
          />
        </div>
      )}
    </details>
  );
}
export function AuthoringRulePicker({
  bidId,
  selected,
  disabled,
  onToggle,
}: {
  bidId: string;
  selected: string[];
  disabled: boolean;
  onToggle: (id: string, checked: boolean) => void;
}) {
  const rules = useResource<RuleSetView>(`/bids/${bidId}/rules`);
  return (
    <fieldset className="authoring-rule-picker">
      <legend>关联当前项目要求</legend>
      <ResourceState
        {...rules}
        hasData={!!rules.data}
        onRetry={() => void rules.reload()}
      />
      {rules.data?.rules.length === 0 && (
        <p className="small-note">
          当前尚无可关联的生效规则，仍可人工编写；这不表示项目没有要求。
        </p>
      )}
      {rules.data?.rules.map((rule) => (
        <label className="checkbox-label" key={rule.id}>
          <input
            type="checkbox"
            checked={selected.includes(rule.id)}
            disabled={
              disabled ||
              (!selected.includes(rule.id) &&
                rule.provenance_status !== "effective")
            }
            onChange={(event) => onToggle(rule.id, event.target.checked)}
          />
          <span>
            {rule.statement}
            {rule.provenance_status !== "effective" && (
              <small>来源或适用性仍待核对</small>
            )}
          </span>
        </label>
      ))}
    </fieldset>
  );
}
export function AuthoringSourcePicker({
  bidId,
  disabled,
  onAdd,
}: {
  bidId: string;
  disabled: boolean;
  onAdd: (reference: AuthoringSourceReference) => void;
}) {
  const active = useRef(true);
  const blocked = useRef(disabled);
  blocked.current = disabled;
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const materials = useResource<MaterialView>(`/bids/${bidId}/materials`);
  const [documentId, setDocumentId] = useState("");
  const evidence = useResource<DocumentEvidenceView>(
    documentId ? `/documents/${documentId}/evidence` : null,
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [projection, setProjection] =
    useState<EvidenceAuthoringReferenceView | null>(null);
  const [lastId, setLastId] = useState("");
  async function attach(id: string) {
    if (disabled || busy) return;
    setBusy(id);
    setLastId(id);
    setError(null);
    setProjection(null);
    try {
      const { data } = await api<EvidenceAuthoringReferenceView>(
        `/evidence/${id}/authoring-reference`,
      );
      if (!active.current) return;
      if (blocked.current)
        throw new Error(
          "正文正在执行其他操作，此来源尚未加入。请稍后重新核验并关联。",
        );
      if (
        data.bid_id !== bidId ||
        data.evidence_id !== id ||
        data.document_version_id !== documentId
      )
        throw new Error("来源身份不一致，未关联其他项目或版本。");
      setProjection(data);
      if (data.authoring_reference) {
        if (
          data.authoring_reference.evidence_id !== id ||
          data.authoring_reference.document_version_id !== documentId
        )
          throw new Error("编写引用与此原页身份不一致，尚未加入本章。");
        onAdd(data.authoring_reference);
      }
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      if (active.current) setBusy(null);
    }
  }
  return (
    <fieldset className="authoring-source-picker">
      <legend>添加有原页依据的编写来源</legend>
      <ResourceState
        {...materials}
        hasData={!!materials.data}
        onRetry={() => void materials.reload()}
      />
      <label>
        已入库来源文件
        <select
          aria-label="已入库来源文件"
          value={documentId}
          disabled={disabled || !!busy}
          onChange={(event) => {
            setDocumentId(event.target.value);
            setProjection(null);
            setError(null);
          }}
        >
          <option value="">选择本项目资料</option>
          {materials.data?.documents
            .filter((doc) => doc.role !== "official_result")
            .map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.filename} · 版本 {doc.file_revision}
              </option>
            ))}
        </select>
      </label>
      <p className="small-note">
        来源版本和用途由服务器核验，不以检索摘录或文件同名替代有效依据。
      </p>
      <ResourceState
        {...evidence}
        hasData={!!evidence.data}
        onRetry={() => void evidence.reload()}
      />
      <ErrorNotice
        error={error}
        onRetry={lastId ? () => void attach(lastId) : undefined}
      />
      {projection && (
        <div
          className={`notice ${projection.authoring_reference ? "neutral" : "warning"}`}
        >
          <div>
            <strong>
              {projection.authoring_reference
                ? "已关联本章，等待章节保存确认"
                : "此原页暂不能用于编写引用"}
            </strong>
            {projection.reasons.map((reason, index) => (
              <p key={index}>{reason}</p>
            ))}
          </div>
        </div>
      )}
      {evidence.data?.gaps.map((gap, index) => (
        <p className="small-note" key={index}>
          {gap}
        </p>
      ))}
      {evidence.data?.items.map((item) => (
        <article className="source-quote-choice" key={item.id}>
          <Badge>物理页 {item.physical_page}</Badge>
          <p>{item.quote}</p>
          <button
            className="text-button"
            disabled={disabled || !!busy || item.source_status !== "published"}
            onClick={() => void attach(item.id)}
          >
            {busy === item.id ? "正在核验此原页来源…" : "核验并关联此原页"}
          </button>
        </article>
      ))}
    </fieldset>
  );
}
