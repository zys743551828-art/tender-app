import { useEffect, useRef, useState } from "react";
import { api, ApiError, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import type {
  PackageCurrentFactPage,
  PackageCurrentFactDetail,
  PackageCurrentFactSummary,
  PackageFactChangeView,
  PackageReviewFrozenInputView,
  PackageFactChange_Head,
} from "./contracts";
import type { FreezeScope } from "./packageFrozenInput";
import { executionId } from "./executionInputValidation";
import {
  factChangeBase,
  validCurrentFactPage,
  validCurrentFactDetail,
  validPendingFactChange,
  validateFactChange,
} from "./factChangeProtocol";
import type { FactChangeScope, PendingFactChange } from "./factChangeProtocol";
import {
  loadFactChangeRecord,
  storeFactChangeRecord,
} from "./factChangeRecovery";
import type { FactChangeRecord } from "./factChangeRecovery";
import PackageFactEvidenceChoices from "./PackageFactEvidenceChoices";
import type { FactEvidenceChoice } from "./PackageFactEvidenceChoices";
import "./packageFactChange.css";
import { usePackageScopeGuard } from "./packageScopeGuard";

type Props = {
  scope: FreezeScope;
  frozen: PackageReviewFrozenInputView;
  disabled?: boolean;
  onCommitted?: () => void;
};
type Form = {
  serial: number;
  replaces: string | null;
  head: PackageFactChange_Head;
  subject: string;
  scope: string;
  name: string;
  text: string;
  mode: "text" | "yes" | "no" | "empty";
  unit: string;
  reason: string;
  confirmed: boolean;
  choices: FactEvidenceChoice[];
};
const rejected = new Set([
  "INVALID_REQUEST",
  "IDEMPOTENCY_REQUIRED",
  "FACT_HEAD_CHANGED",
  "PACKAGE_FACT_CHANGE_INVALID",
  "PACKAGE_FACT_CHANGE_REJECTED",
  "PACKAGE_FACT_EVIDENCE_INVALID",
  "PACKAGE_REVIEW_FROZEN_INPUT_CHANGED",
  "PACKAGE_REVIEW_FROZEN_INPUT_NOT_FOUND",
  "PACKAGE_REVIEW_PARSE_UNPROVEN",
  "PACKAGE_REVIEW_EVIDENCE_CHANGED",
  "PACKAGE_REVIEW_DOCUMENT_BINDING_MISMATCH",
  "SOURCE_NOT_EFFECTIVE",
  "SOURCE_CLOSURE_INCOMPLETE",
  "PROJECT_WORK_CLOSED",
]);
const size = (text: string) => Array.from(text).length;
const valueOf = (form: Form) =>
  form.mode === "text"
    ? form.text
    : form.mode === "yes"
      ? true
      : form.mode === "no"
        ? false
        : null;
export default function PackageFactChangeWorkspace(props: Props) {
  const keyScope = {
    ...props.scope,
    frozenId: props.frozen.manifest.id,
    frozenDigest: props.frozen.digest,
  };
  return (
    <Workspace key={JSON.stringify(keyScope)} {...props} keyScope={keyScope} />
  );
}
function Workspace({
  frozen,
  disabled = false,
  onCommitted,
  keyScope,
}: Props & { keyScope: FactChangeScope }) {
  const [loaded] = useState(() => {
    try {
      return { record: loadFactChangeRecord(keyScope), error: null };
    } catch (error) {
      return { record: null, error };
    }
  });
  const [record, setRecord] = useState<FactChangeRecord | null>(loaded.record),
    recordRef = useRef(record);
  const [open, setOpen] = useState(!!loaded.record?.pending),
    [page, setPage] = useState<PackageCurrentFactPage | null>(null),
    [items, setItems] = useState<PackageCurrentFactSummary[]>([]),
    [detail, setDetail] = useState<PackageCurrentFactDetail | null>(null),
    [form, setForm] = useState<Form | null>(null),
    [withdrawReason, setWithdrawReason] = useState("");
  const [error, setError] = useState<unknown>(loaded.error),
    [busy, setBusy] = useState(false),
    [reading, setReading] = useState(false),
    [readingDetail, setReadingDetail] = useState(false),
    [historyId, setHistoryId] = useState(loaded.record?.lastId ?? ""),
    [result, setResult] = useState<{
      value: PackageFactChangeView;
      history: boolean;
    } | null>(null);
  const active = useRef(false),
    writing = useRef(false),
    listTicket = useRef(0),
    detailTicket = useRef(0),
    historyTicket = useRef(0),
    serial = useRef(0),
    seen = useRef(new Set<string>());
  const base = factChangeBase(keyScope),
    available =
      supportsApi("GET", `${base}/fact-context`) &&
      supportsApi("POST", `${base}/fact-confirmations`) &&
      supportsApi("POST", `${base}/fact-withdrawals`);
  const locked = disabled || busy || !!record?.pending || !record;
  usePackageScopeGuard(`fact-change:${JSON.stringify(keyScope)}`, {
    busy,
    pending: !!record?.pending || !!loaded.error,
    dirty: !record?.pending && (!!form || !!withdrawReason),
  });
  useEffect(() => {
    const requests = [listTicket, detailTicket, historyTicket];
    for (const request of requests) request.current++;
    active.current = true;
    return () => {
      active.current = false;
      for (const request of requests) request.current++;
    };
  }, []);
  function persist(next: FactChangeRecord) {
    storeFactChangeRecord(next);
    recordRef.current = next;
    setRecord(next);
  }
  async function readList(more = false) {
    if (!available || writing.current || (more && !page?.next_cursor)) return;
    const ticket = ++listTicket.current,
      after = more ? page?.next_cursor : null;
    setReading(true);
    setError(null);
    if (!more) {
      setPage(null);
      setItems([]);
      seen.current.clear();
    }
    try {
      const { data } = await api<PackageCurrentFactPage>(
        `${base}/fact-context?frozen_digest=${frozen.digest}&limit=20${after ? `&cursor=${encodeURIComponent(after)}` : ""}`,
      );
      if (
        !validCurrentFactPage(data, keyScope) ||
        (data.next_cursor === after && data.has_more)
      )
        throw new Error(
          "当前事实列表的身份、版本或资格边界不符，未采用该列表。",
        );
      if (
        more &&
        page &&
        (data.head.id !== page.head.id ||
          data.head.revision !== page.head.revision)
      )
        throw new Error("事实集已变化，请重读后继续。");
      if (!active.current || ticket !== listTicket.current) return;
      if (data.items.some((item) => seen.current.has(item.fact_id)))
        throw new Error("事实列表重复返回已读取条目，请重读后继续。");
      data.items.forEach((item) => seen.current.add(item.fact_id));
      setItems((old) => (more ? [...old, ...data.items] : data.items));
      setPage(data);
    } catch (failure) {
      if (active.current && ticket === listTicket.current) setError(failure);
    } finally {
      if (active.current && ticket === listTicket.current) setReading(false);
    }
  }
  async function inspect(item: PackageCurrentFactSummary) {
    if (locked || writing.current) return;
    const ticket = ++detailTicket.current;
    setReadingDetail(true);
    setDetail(null);
    setForm(null);
    setWithdrawReason("");
    setError(null);
    try {
      const { data } = await api<PackageCurrentFactDetail>(
        `${base}/facts/${item.fact_id}?frozen_digest=${frozen.digest}`,
      );
      if (!validCurrentFactDetail(data, keyScope, item.fact_id, item))
        throw new Error("事实详情与选定事实或冻结范围不符，请重读列表。");
      if (!active.current || ticket !== detailTicket.current) return;
      setDetail(data);
      const fact = data.editable_fact;
      if (fact) {
        setForm({
          serial: ++serial.current,
          replaces: item.fact_id,
          head: { ...data.head },
          subject: fact.subject,
          scope: fact.scope,
          name: fact.name,
          text: typeof fact.value === "string" ? fact.value : "",
          mode:
            typeof fact.value === "string"
              ? "text"
              : fact.value === true
                ? "yes"
                : fact.value === false
                  ? "no"
                  : "empty",
          unit: fact.unit ?? "",
          reason: "",
          confirmed: false,
          choices: fact.evidence_ids.map((id, n) => {
            const ref = data.evidence_references.find((x) => x.id === id);
            return {
              id,
              documentId: ref?.document_version_id ?? "",
              parseId: ref?.parse_id ?? "",
              page: ref?.physical_page ?? 0,
              label: ref
                ? `原依据 ${n + 1} · 第 ${ref.physical_page} 页`
                : `待重新选择的原依据 ${n + 1}`,
              frozenParseMember: ref?.frozen_parse_member ?? false,
            };
          }),
        });
      }
    } catch (failure) {
      if (active.current && ticket === detailTicket.current) setError(failure);
    } finally {
      if (active.current && ticket === detailTicket.current)
        setReadingDetail(false);
    }
  }
  function add() {
    if (locked || !page) return;
    detailTicket.current++;
    setReadingDetail(false);
    setDetail(null);
    setWithdrawReason("");
    setForm({
      serial: ++serial.current,
      replaces: null,
      head: { ...page.head },
      subject: "",
      scope: "",
      name: "",
      text: "",
      mode: "text",
      unit: "",
      reason: "",
      confirmed: false,
      choices: [],
    });
  }
  function edit(
    key: "subject" | "scope" | "name" | "text" | "unit" | "reason",
    value: string,
  ) {
    if (locked) return;
    setForm((old) => (old ? { ...old, [key]: value, confirmed: false } : old));
  }
  const confirmReady =
    !!form &&
    (["subject", "scope", "name"] as const).every(
      (k) => form[k].trim().length > 0,
    ) &&
    form.reason.trim().length > 0 &&
    size(form.reason.trim()) <= 2000 &&
    (form.mode !== "text" || form.text.trim().length > 0) &&
    form.choices.length > 0 &&
    form.choices.length <= 100 &&
    form.choices.every((choice) => choice.frozenParseMember) &&
    form.confirmed;
  function confirmation(): PendingFactChange | null {
    if (!form || !confirmReady) return null;
    return {
      kind: "confirm",
      key: crypto.randomUUID(),
      body: {
        frozen_digest: frozen.digest,
        expected_head: { ...form.head },
        replaces_fact_id: form.replaces,
        confirmation: "confirmed",
        fact: {
          subject: form.subject,
          scope: form.scope,
          name: form.name,
          value: valueOf(form),
          unit: form.unit || null,
          evidence_ids: form.choices.map((x) => x.id),
          reason: form.reason.trim(),
        },
      },
    };
  }
  function withdrawal(): PendingFactChange | null {
    if (!detail || !withdrawReason.trim() || size(withdrawReason.trim()) > 2000)
      return null;
    return {
      kind: "withdraw",
      key: crypto.randomUUID(),
      body: {
        frozen_digest: frozen.digest,
        expected_head: { ...detail.head },
        fact_id: detail.summary.fact_id,
        reason: withdrawReason.trim(),
      },
    };
  }
  async function write(next: PendingFactChange | null, recover = false) {
    const current = recordRef.current,
      pending = recover ? current?.pending : next;
    if (
      !current ||
      !pending ||
      writing.current ||
      !available ||
      (!recover && (disabled || current.pending)) ||
      !validPendingFactChange(pending, keyScope)
    )
      return;
    writing.current = true;
    historyTicket.current++;
    setBusy(true);
    setError(null);
    setResult(null);
    detailTicket.current++;
    setReadingDetail(false);
    let committed = false;
    try {
      persist({ ...current, pending });
      let data: PackageFactChangeView;
      try {
        ({ data } = await api<PackageFactChangeView>(
          `${base}/${pending.kind === "confirm" ? "fact-confirmations" : "fact-withdrawals"}`,
          { method: "POST", key: pending.key, body: pending.body },
        ));
      } catch (failure) {
        if (
          active.current &&
          !recover &&
          failure instanceof ApiError &&
          rejected.has(failure.code)
        )
          persist({ ...current, pending: null });
        throw failure;
      }
      await validateFactChange(data, keyScope, pending);
      if (!active.current) return;
      persist({ ...current, pending: null, lastId: data.manifest.command_id });
      setHistoryId(data.manifest.command_id);
      setResult({ value: data, history: false });
      setForm(null);
      setDetail(null);
      setWithdrawReason("");
      committed = true;
      onCommitted?.();
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      writing.current = false;
      if (active.current) {
        setBusy(false);
        if (committed) void readList();
      }
    }
  }
  async function readHistory() {
    if (writing.current) return;
    const id = historyId.trim();
    if (!executionId(id) || !supportsApi("GET", `${base}/fact-changes/${id}`))
      return;
    const ticket = ++historyTicket.current;
    setError(null);
    try {
      const { data } = await api<PackageFactChangeView>(
        `${base}/fact-changes/${id}`,
      );
      await validateFactChange(data, keyScope);
      if (data.manifest.command_id !== id)
        throw new Error("历史回执编号不一致。");
      if (active.current && ticket === historyTicket.current)
        setResult({ value: data, history: true });
    } catch (failure) {
      if (active.current && ticket === historyTicket.current) setError(failure);
    }
  }
  return (
    <details
      className="package-fact-change"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>项目事实（可选）</summary>
      <div className="package-fact-change__body">
        <p>
          记录原页支持的项目事实。人工确认与当前使用资格分别核验；保存后需重新准备评审输入。
        </p>
        {!available && <p>当前服务尚未提供项目事实管理。</p>}
        {record?.pending && (
          <div className="package-fact-change__pending" role="status">
            <p>
              上次{record.pending.kind === "confirm" ? "确认" : "撤回"}
              的结果尚未确定，已保留原提交内容和幂等键。
            </p>
            <button
              type="button"
              className="button secondary"
              disabled={!available || busy}
              onClick={() => void write(null, true)}
            >
              {busy ? "正在核对保存结果…" : "恢复原事实操作"}
            </button>
            <details>
              <summary>查看上次提交内容</summary>
              {record.pending.kind === "confirm" ? (
                <dl>
                  <dt>事实主体</dt>
                  <dd>{record.pending.body.fact.subject}</dd>
                  <dt>适用范围</dt>
                  <dd>{record.pending.body.fact.scope}</dd>
                  <dt>事实名称</dt>
                  <dd>{record.pending.body.fact.name}</dd>
                  <dt>事实内容</dt>
                  <dd>
                    {record.pending.body.fact.value === null
                      ? "未填写"
                      : record.pending.body.fact.value === true
                        ? "是"
                        : record.pending.body.fact.value === false
                          ? "否"
                          : record.pending.body.fact.value}
                  </dd>
                  <dt>单位</dt>
                  <dd>{record.pending.body.fact.unit || "未填写"}</dd>
                  <dt>原页依据</dt>
                  <dd>{record.pending.body.fact.evidence_ids.length} 条</dd>
                  <dt>确认理由</dt>
                  <dd>{record.pending.body.fact.reason}</dd>
                </dl>
              ) : (
                <p>撤回理由：{record.pending.body.reason}</p>
              )}
            </details>
          </div>
        )}
        <div className="package-fact-change__actions">
          <button
            type="button"
            className="button secondary"
            disabled={!available || reading || busy}
            onClick={() => void readList()}
          >
            {reading ? "正在读取项目事实…" : "读取当前项目事实"}
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={locked || !page || reading}
            onClick={add}
          >
            新增项目事实
          </button>
        </div>
        {error != null && <ErrorNotice error={error} />}
        {page && (
          <>
            <p>当前事实 {page.fact_count} 条。确认记录不代表已满足必要条件。</p>
            {!items.length && <p>暂无项目事实。可继续核对资料和要求。</p>}
            <ul className="package-fact-change__list">
              {items.map((item) => (
                <li key={item.fact_id}>
                  <div>
                    <strong>{item.name || "未命名事实"}</strong>
                    <span>
                      {item.value_preview || "（空值）"}
                      {item.unit ? ` ${item.unit}` : ""}
                    </span>
                    <small>
                      {item.subject} · {item.scope} ·{" "}
                      {item.confirmation_recorded === "confirmed"
                        ? "已记录人工确认"
                        : item.confirmation_recorded === "rejected"
                          ? "已记录拒绝"
                          : "待人工确认"}
                      {item.preview_truncated ? " · 摘要已截断" : ""}
                    </small>
                  </div>
                  <button
                    type="button"
                    className="button secondary"
                    disabled={locked || readingDetail}
                    onClick={() => void inspect(item)}
                  >
                    查看并修改
                  </button>
                </li>
              ))}
            </ul>
            {page.has_more && (
              <button
                type="button"
                className="button secondary"
                disabled={reading || busy}
                onClick={() => void readList(true)}
              >
                更多项目事实
              </button>
            )}
          </>
        )}
        {readingDetail && <p role="status">正在读取准确事实详情…</p>}
        {detail?.editability === "unsupported_or_oversized" && (
          <p>
            此事实的类型或长度暂不支持直接编辑。保留原值，可另行录入或撤回。
          </p>
        )}
        {form && page && (
          <fieldset disabled={locked} className="package-fact-change__form">
            <legend>
              {form.replaces ? "修改并重新确认项目事实" : "新增项目事实"}
            </legend>
            <div className="package-fact-change__fields">
              {(
                [
                  ["subject", "事实主体"],
                  ["scope", "适用范围"],
                  ["name", "事实名称"],
                ] as const
              ).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    value={form[key]}
                    maxLength={5000}
                    onChange={(e) => edit(key, e.target.value)}
                  />
                </label>
              ))}
              <label>
                内容类型
                <select
                  value={form.mode}
                  onChange={(e) =>
                    setForm((old) =>
                      old
                        ? {
                            ...old,
                            mode: e.target.value as Form["mode"],
                            confirmed: false,
                          }
                        : old,
                    )
                  }
                >
                  <option value="text">文字</option>
                  <option value="yes">是</option>
                  <option value="no">否</option>
                  <option value="empty">未填写</option>
                </select>
              </label>
              {form.mode === "text" && (
                <label className="package-fact-change__wide">
                  事实内容
                  <textarea
                    value={form.text}
                    maxLength={20000}
                    rows={3}
                    onChange={(e) => edit("text", e.target.value)}
                  />
                </label>
              )}
              <label>
                单位（选填）
                <input
                  value={form.unit}
                  onChange={(e) => edit("unit", e.target.value)}
                />
              </label>
            </div>
            <PackageFactEvidenceChoices
              key={form.serial}
              scope={keyScope}
              packages={page.source_packages}
              selected={form.choices}
              disabled={locked}
              onPick={(choice) => {
                if (writing.current || recordRef.current?.pending) return;
                setForm((old) =>
                  old
                    ? {
                        ...old,
                        confirmed: false,
                        choices: [
                          ...old.choices.filter((x) => x.id !== choice.id),
                          choice,
                        ],
                      }
                    : old,
                );
              }}
              onRemove={(id) => {
                if (writing.current || recordRef.current?.pending) return;
                setForm((old) =>
                  old
                    ? {
                        ...old,
                        confirmed: false,
                        choices: old.choices.filter((x) => x.id !== id),
                      }
                    : old,
                );
              }}
            />
            <label>
              确认理由
              <textarea
                value={form.reason}
                maxLength={2000}
                rows={2}
                onChange={(e) => edit("reason", e.target.value)}
              />
            </label>
            <label className="package-fact-change__check">
              <input
                type="checkbox"
                checked={form.confirmed}
                onChange={(e) =>
                  setForm((old) =>
                    old ? { ...old, confirmed: e.target.checked } : old,
                  )
                }
              />
              我已核对原页并确认以上事实内容
            </label>
            <div className="package-fact-change__actions">
              <button
                type="button"
                className="button primary"
                disabled={locked || !confirmReady}
                onClick={() => void write(confirmation())}
              >
                {busy ? "正在保存事实…" : "确认并保存事实"}
              </button>
              <button
                type="button"
                className="button secondary"
                disabled={locked}
                onClick={() => setForm(null)}
              >
                关闭编辑
              </button>
            </div>
          </fieldset>
        )}
        {detail && (
          <fieldset disabled={locked} className="package-fact-change__withdraw">
            <legend>撤回当前事实</legend>
            <p>{detail.summary.name || "未命名事实"}</p>
            <label>
              撤回理由
              <textarea
                value={withdrawReason}
                maxLength={2000}
                rows={2}
                onChange={(e) => setWithdrawReason(e.target.value)}
              />
            </label>
            <button
              type="button"
              className="button secondary"
              disabled={locked || !withdrawReason.trim()}
              onClick={() => void write(withdrawal())}
            >
              撤回此事实
            </button>
          </fieldset>
        )}
        {result && (
          <div role="status" className="package-fact-change__result">
            <p>
              {result.history
                ? "历史事实回执，仅供核对。"
                : result.value.manifest.action === "confirmed"
                  ? "事实已确认保存，请重新复核当前条件并准备输入。"
                  : "事实已撤回，历史记录保留。"}
            </p>
            <p>{result.value.manifest.reason}</p>
            <details>
              <summary>操作身份与边界</summary>
              <p>
                操作编号：<code>{result.value.manifest.command_id}</code>
              </p>
              <p>
                回执摘要：<code>{result.value.digest}</code>
              </p>
              <p>原件字节和当前使用资格须另行核验，没有启动评审任务。</p>
              {result.value.manifest.version === "package-fact-change/1" && (
                <p>旧回执未记录完整请求摘要，按历史原样读取。</p>
              )}
            </details>
          </div>
        )}
        <details>
          <summary>读取已有事实回执</summary>
          <label>
            事实操作编号
            <input
              value={historyId}
              onChange={(e) => {
                historyTicket.current++;
                setHistoryId(e.target.value);
              }}
              placeholder="粘贴操作编号"
            />
          </label>
          <button
            type="button"
            className="button secondary"
            disabled={!executionId(historyId.trim()) || busy}
            onClick={() => void readHistory()}
          >
            读取事实回执
          </button>
        </details>
      </div>
    </details>
  );
}
