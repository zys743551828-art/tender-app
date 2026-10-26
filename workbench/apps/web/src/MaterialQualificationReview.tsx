import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ErrorNotice } from "./components";
import { jsonDigest } from "./editorSchema";
import {
  executionId as uuid,
  recordObject as object,
} from "./executionInputValidation";

type View = {
  version: string;
  id: string;
  scope_id: string;
  digest: string;
  document: Record<string, unknown>;
  revision: number;
  state: string;
  decision: string | null;
  execution_authorized: false;
  accuracy_verified: false;
};
type Pending = {
  path: string;
  body: Record<string, unknown>;
  key: string;
  etag?: string;
};

export function MaterialQualificationReview(props: {
  base: string;
  scopeId: string;
  scopeDigest: string;
  memberId: string;
}) {
  return (
    <Review
      key={`${props.memberId}:${props.scopeId}:${props.scopeDigest}`}
      {...props}
    />
  );
}
function Review({
  base,
  scopeId,
  scopeDigest,
  memberId,
}: {
  base: string;
  scopeId: string;
  scopeDigest: string;
  memberId: string;
}) {
  const root = `${base}/material-qualifications`;
  const storage = `material-qualification:${memberId}:${scopeId}:${scopeDigest}`;
  const [text, setText] = useState(""),
    [id, setId] = useState(""),
    [reason, setReason] = useState("");
  const [view, setView] = useState<{ data: View; etag: string } | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false),
    [corrupt, setCorrupt] = useState(false);
  const active = useRef(false),
    running = useRef(false);
  useEffect(() => {
    active.current = true;
    try {
      const raw = sessionStorage.getItem(storage);
      if (raw) {
        const p = JSON.parse(raw) as Pending;
        const suffix = p.path?.slice(root.length + 1).split("/");
        if (
          !uuid(p.key) ||
          !object(p.body) ||
          !(
            p.path === root ||
            (p.path.startsWith(`${root}/`) &&
              suffix?.length === 2 &&
              uuid(suffix[0]) &&
              suffix[1] === "decisions" &&
              typeof p.etag === "string")
          )
        )
          throw new Error("待恢复审核记录损坏，请保留记录后联系管理员核对。");
        setPending(p);
      }
    } catch (e) {
      setError(e);
      setCorrupt(true);
    }
    return () => {
      active.current = false;
    };
  }, [storage, root]);
  async function run(fn: () => Promise<void>) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      if (active.current) setError(e);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function checked(data: unknown, etag: string | null) {
    if (
      !object(data) ||
      data.version !== "material-qualification-review-view/1" ||
      !uuid(data.id) ||
      data.scope_id !== scopeId ||
      !object(data.document) ||
      !object(data.document.binding) ||
      data.document.binding.scope_digest !== scopeDigest ||
      data.execution_authorized !== false ||
      data.accuracy_verified !== false ||
      !Number.isInteger(data.revision) ||
      (data.revision as number) < 0 ||
      etag !== `"material-qualification:${data.id}:${data.revision}"` ||
      (await jsonDigest(data.document)) !== data.digest
    )
      throw new Error("资格回执身份或摘要不一致，请保留原请求。");
    return { data: data as View, etag: etag! };
  }
  async function send(p: Pending) {
    sessionStorage.setItem(storage, JSON.stringify(p));
    setPending(p);
    const result = await api<unknown>(p.path, {
      method: "POST",
      body: p.body,
      key: p.key,
      etag: p.etag,
    });
    const resultView = await checked(result.data, result.etag);
    if (
      p.path === root
        ? (await jsonDigest(p.body)) !== resultView.data.digest
        : p.path !== `${root}/${resultView.data.id}/decisions` ||
          p.body.decision !== resultView.data.decision
    )
      throw new Error("资格回执与原请求不一致。");
    // A replay is a historical receipt. Explicit reload is required before another review.
    if (active.current) {
      setId(resultView.data.id);
      setView(null);
      setPending(null);
      sessionStorage.removeItem(storage);
    }
  }
  return (
    <section aria-label="模型资格证据审核">
      <h4>模型资格证据登记与审核</h4>
      <p>
        审核价格、能力和验证记录。审核通过不等于准确性验收，也不启用模型调用；原生接受与发送接线尚未完成。
      </p>
      <ErrorNotice error={error} />
      <label>
        资格协议 JSON
        <textarea
          value={text}
          disabled={busy || !!pending || corrupt}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <button
        disabled={busy || !!pending || corrupt || !text.trim()}
        onClick={() =>
          void run(async () => {
            const body: unknown = JSON.parse(text);
            if (!object(body)) throw new Error("请输入资格协议对象。");
            await send({ path: root, body, key: crypto.randomUUID() });
          })
        }
      >
        登记不可变证据版本
      </button>
      {pending && (
        <button
          disabled={busy || corrupt}
          onClick={() => void run(() => send(pending))}
        >
          恢复原审核请求
        </button>
      )}
      <label>
        资格记录编号
        <input
          value={id}
          disabled={busy || !!pending}
          onChange={(e) => {
            setId(e.target.value);
            setView(null);
          }}
        />
      </label>
      <button
        disabled={busy || !!pending || !uuid(id)}
        onClick={() =>
          void run(async () => {
            setView(null);
            const result = await api<unknown>(`${root}/${id}`);
            const value = await checked(result.data, result.etag);
            if (value.data.id !== id)
              throw new Error("读取返回了其他资格记录。");
            if (active.current) setView(value);
          })
        }
      >
        读取当前审核状态
      </button>
      {view && (
        <>
          <p>
            状态：{view.data.state}；版本：{view.data.revision}。执行未启用。
          </p>
          <pre>{JSON.stringify(view.data.document, null, 2)}</pre>
          <label>
            审核理由
            <input
              value={reason}
              maxLength={4000}
              disabled={busy || !!pending}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          {(["approved", "revoked"] as const).map((decision) => (
            <button
              key={decision}
              disabled={
                busy ||
                !!pending ||
                corrupt ||
                !reason.trim() ||
                view.data.decision === "revoked" ||
                view.data.decision === decision ||
                (decision === "approved" && view.data.state === "expired")
              }
              onClick={() =>
                void run(() =>
                  send({
                    path: `${root}/${view.data.id}/decisions`,
                    body: { decision, reason },
                    key: crypto.randomUUID(),
                    etag: view.etag,
                  }),
                )
              }
            >
              {decision === "approved" ? "批准所示证据" : "撤销所示证据"}
            </button>
          ))}
        </>
      )}
    </section>
  );
}
