import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  PackageAuthoringSelection,
  PackageAuthoringInputContext,
} from "./contracts";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import {
  isPackageAuthoringSelection,
  validateAuthoringInput,
  validateAuthoringInputPage,
  validateAuthoringPublicContext,
  type VerifiedAuthoringInput,
} from "./packageAuthoringInputProtocol";

export function AuthoringInputSummary({
  input,
}: {
  input: VerifiedAuthoringInput;
}) {
  const m = input.manifest,
    target = m.selection.target_section;
  return (
    <section
      className="exact-package-task-scope"
      aria-label="固定整包编写输入范围"
    >
      <p>
        保存时间：{new Date(m.saved_at).toLocaleString("zh-CN")}
        ；正文基准：稿件修订 {target.base_draft_revision}、章节修订{" "}
        {target.base_section_revision}。
      </p>
      <p>
        整包 {m.counts.logical_members} 份文件、{m.counts.physical_pages} 页、
        {m.counts.requirements} 项需求；已绑定 {m.counts.facts} 项事实及{" "}
        {m.fact_declarations.length} 项用途声明。
      </p>
      <p className="small-note">
        这里只读取保存时的范围。运行时会重新核验原件、当前来源和事实资格；读取历史输入不会授予运行或采纳资格。
      </p>
      <details className="identity-details">
        <summary>核对具体包、清单和正文身份</summary>
        <dl>
          <dt>编写输入</dt>
          <dd>{m.id}</dd>
          <dt>输入摘要</dt>
          <dd>{input.digest}</dd>
          <dt>目标包／修订</dt>
          <dd>
            {m.selection.package_context.target.package_id} ／{" "}
            {m.selection.package_context.target.revision_id}
          </dd>
          <dt>依据包／修订</dt>
          <dd>
            {m.selection.package_context.authority.package_id} ／{" "}
            {m.selection.package_context.authority.revision_id}
          </dd>
          <dt>需求清单</dt>
          <dd>{m.selection.package_context.inventory.id}</dd>
          <dt>稿件／快照</dt>
          <dd>
            {target.draft_id} ／ {target.snapshot_id}
          </dd>
          <dt>章节／文字节点</dt>
          <dd>
            {target.section_id} ／ {target.node_id}
          </dd>
          <dt>项目／标段／轮次／投标主体</dt>
          <dd>
            {m.scope.engineering_project_id} ／ {m.scope.lot_id} ／{" "}
            {m.scope.round_id} ／ {m.scope.bidder_id}
          </dd>
        </dl>
      </details>
    </section>
  );
}

function PublicContext({ input }: { input: VerifiedAuthoringInput }) {
  const resource = useResource<PackageAuthoringInputContext>(
    `/bids/${input.manifest.bid_id}/authoring/package-inputs/${input.manifest.id}/context`,
  );
  let context: PackageAuthoringInputContext | null = null,
    error: unknown = null;
  if (resource.data)
    try {
      context = validateAuthoringPublicContext(resource.data, input);
    } catch (caught) {
      error = caught;
    }
  return (
    <section aria-label="保存的完整编写上下文">
      <ResourceState
        {...resource}
        hasData={!!context}
        onRetry={() => void resource.reload()}
      />
      <ErrorNotice error={error} />
      {context && (
        <>
          <p className="small-note">
            以下保留保存时的完整公开上下文。内部文件存储地址已隐藏；本次读取没有重新下载并核验原件字节。
          </p>
          <details>
            <summary>展开来源、需求、事实声明与正文快照</summary>
            <pre className="preserve-text">
              {JSON.stringify(context.context, null, 2)}
            </pre>
          </details>
        </>
      )}
    </section>
  );
}

export function PackageAuthoringInputDetails({
  bidId,
  selection,
  onVerified,
}: {
  bidId: string;
  selection: PackageAuthoringSelection;
  onVerified?: (input: VerifiedAuthoringInput | null) => void;
}) {
  const valid = isPackageAuthoringSelection(selection);
  const resource = useResource<unknown>(
    valid
      ? `/bids/${bidId}/authoring/package-inputs/${selection.authoring_input_id}`
      : null,
  );
  const [checked, setChecked] = useState<{
    source: unknown;
    value: VerifiedAuthoringInput;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [open, setOpen] = useState(false);
  const inputId = selection?.authoring_input_id,
    digest = selection?.authoring_input_digest;
  useEffect(() => {
    let active = true;
    setError(null);
    if (!valid) setError(new Error("已保存编写输入身份无效，未自动替换。"));
    else if (resource.data)
      void validateAuthoringInput(resource.data, bidId, {
        authoring_input_id: inputId,
        authoring_input_digest: digest,
      })
        .then((value) => {
          if (active) setChecked({ source: resource.data, value });
        })
        .catch((error) => {
          if (active) setError(error);
        });
    return () => {
      active = false;
    };
  }, [resource.data, bidId, inputId, digest, valid]);
  const input =
    checked?.value.manifest.bid_id === bidId &&
    checked.value.manifest.id === inputId &&
    checked.value.digest === digest
      ? checked.value
      : null;
  const ready =
    !!input &&
    checked?.source === resource.data &&
    !resource.loading &&
    !resource.error &&
    !error;
  useEffect(() => {
    onVerified?.(ready ? input : null);
  }, [onVerified, ready, input]);
  useEffect(() => () => onVerified?.(null), [onVerified]);
  return (
    <section aria-label="模板绑定的固定编写输入">
      <ResourceState
        {...resource}
        hasData={!!input}
        onRetry={() => void resource.reload()}
      />
      <ErrorNotice error={error} />
      {input && (
        <>
          <AuthoringInputSummary input={input} />
          {!ready && (
            <p className="notice warning">
              保留上次已核验输入，当前读取尚未核验通过；新的保存和运行暂不可用。
            </p>
          )}
          <button
            type="button"
            className="text-button"
            disabled={!ready}
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            查看保存的完整编写上下文
          </button>
          {open && (
            <PublicContext
              key={`${bidId}:${inputId}:${digest}`}
              input={input}
            />
          )}
        </>
      )}
    </section>
  );
}

export function PackageAuthoringInputPicker({
  bidId,
  disabled = false,
  onSelect,
}: {
  bidId: string;
  disabled?: boolean;
  onSelect: (input: VerifiedAuthoringInput) => void;
}) {
  const [items, setItems] = useState<VerifiedAuthoringInput[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const scope = useRef({
    bidId,
    epoch: 0,
    active: true,
    running: false,
    cursors: new Set<string>(),
  });
  useEffect(() => {
    const current = {
      bidId,
      epoch: 0,
      active: true,
      running: false,
      cursors: new Set<string>(),
    };
    scope.current = current;
    setItems([]);
    setCursor(null);
    setLoaded(false);
    setError(null);
    setBusy(false);
    return () => {
      current.active = false;
      ++current.epoch;
    };
  }, [bidId]);
  async function read(more: boolean) {
    const current = scope.current;
    if (
      disabled ||
      current.running ||
      !current.active ||
      current.bidId !== bidId ||
      (more && !cursor)
    )
      return;
    current.running = true;
    const epoch = ++current.epoch;
    setBusy(true);
    setError(null);
    const position = more ? cursor : null;
    try {
      const response = await api<unknown>(
        `/bids/${bidId}/authoring/package-inputs?limit=20${position ? `&cursor=${encodeURIComponent(position)}` : ""}`,
      );
      const page = await validateAuthoringInputPage(
        response.data,
        bidId,
        more ? items : [],
        position,
      );
      if (
        !current.active ||
        scope.current !== current ||
        current.epoch !== epoch
      )
        return;
      if (more && page.next_cursor && current.cursors.has(page.next_cursor))
        throw new Error("输入目录游标循环，已停止继续加载。");
      if (!more) current.cursors.clear();
      if (position) current.cursors.add(position);
      setItems(more ? [...items, ...page.items] : page.items);
      setCursor(page.next_cursor);
      setLoaded(true);
    } catch (error) {
      if (
        current.active &&
        scope.current === current &&
        current.epoch === epoch
      )
        setError(error);
    } finally {
      current.running = false;
      if (
        current.active &&
        scope.current === current &&
        current.epoch === epoch
      )
        setBusy(false);
    }
  }
  return (
    <section aria-label="明确选择已保存的编写输入">
      <p>
        从已保存的固定输入中明确选择一份。目录不会默认勾选第一条或把最新修订替入已有模板。
      </p>
      <button
        type="button"
        className="button secondary"
        disabled={disabled || busy}
        onClick={() => void read(false)}
      >
        {loaded ? "刷新固定输入目录" : "读取固定输入目录"}
      </button>
      <ErrorNotice error={error} />
      {busy && <p role="status">正在核验固定输入目录…</p>}
      {loaded && (
        <p className="small-note">
          本次已读 {items.length} 条，按服务器稳定标识顺序显示。
          {cursor
            ? "还有后续记录。"
            : "本次分页已读完；这不表示所有记录仍具备运行资格。"}
        </p>
      )}
      {loaded && !items.length && (
        <p className="small-empty">
          尚无已保存的固定编写输入。需要先明确包、清单、事实与正文快照并保存完整输入，才能建立这类模板。
        </p>
      )}
      {items.map((item) => (
        <article className="panel" key={item.manifest.id}>
          <AuthoringInputSummary input={item} />
          <button
            type="button"
            className="button secondary"
            disabled={disabled || busy || !!error}
            onClick={() => onSelect(item)}
          >
            选择这份编写输入 · {item.manifest.id.slice(0, 8)}
          </button>
        </article>
      ))}
      {cursor && (
        <button
          type="button"
          className="text-button"
          disabled={disabled || busy || !!error}
          onClick={() => void read(true)}
        >
          加载更多固定编写输入
        </button>
      )}
    </section>
  );
}
