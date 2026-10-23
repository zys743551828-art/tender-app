import { useCallback, useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import { HistoricalImportBatch } from "./HistoricalImportBatch";
import { HistoricalImportDirectory } from "./HistoricalImportDirectory";
import {
  HistoricalImportEditor,
  type HistoricalSeed,
} from "./HistoricalImportEditor";
import {
  definitiveHistoricalFailure,
  historicalImportPath,
  historicalSame,
  validateHistoricalReceipt,
  type HistoricalPending,
} from "./historicalImportProtocol";
import {
  readHistoricalRecovery,
  writeHistoricalRecovery,
  type HistoricalRecovery,
} from "./historicalImportRecovery";
import "./HistoricalImports.css";

export function HistoricalImports({
  memberId,
  onImported,
}: {
  memberId: string;
  onImported: () => void;
}) {
  const [initial] = useState(() => {
    try {
      return { recovery: readHistoricalRecovery(memberId), error: null };
    } catch (error) {
      return {
        recovery: {
          version: 1,
          memberId,
          pending: null,
          lastBatchId: null,
        } as HistoricalRecovery,
        error,
      };
    }
  });
  const [recovery, setRecovery] = useState(initial.recovery),
    [opened, setOpened] = useState(
      !!initial.recovery.pending || !!initial.error,
    );
  const [error, setError] = useState<unknown>(initial.error),
    [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false),
    [readBusy, setReadBusy] = useState(false);
  const [selected, setSelected] = useState(
    initial.recovery.pending?.kind === "confirm"
      ? initial.recovery.pending.batchId
      : initial.recovery.lastBatchId,
  );
  const [version, setVersion] = useState(0),
    [seed, setSeed] = useState<HistoricalSeed | null>(null),
    [editorVersion, setEditorVersion] = useState(0);
  const active = useRef(false),
    running = useRef(false),
    record = useRef(recovery);
  const onReadBusy = useCallback((value: boolean) => setReadBusy(value), []);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  function remember(next: HistoricalRecovery) {
    writeHistoricalRecovery(next);
    record.current = next;
    setRecovery(next);
  }
  async function send(pending: HistoricalPending) {
    if (running.current || initial.error) return;
    if (
      record.current.pending &&
      !historicalSame(record.current.pending, pending)
    ) {
      setError(new Error("尚有未核对的原导入请求，不能另发新操作。"));
      return;
    }
    running.current = true;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      if (!record.current.pending) remember({ ...record.current, pending });
      const path =
        pending.kind === "preview"
          ? "/research/import-previews"
          : `${historicalImportPath(pending.batchId)}/confirm`;
      const result = await api<unknown>(path, {
        method: "POST",
        body: pending.body,
        key: pending.key,
        etag: pending.etag,
      });
      const checked = await validateHistoricalReceipt(
        result.data,
        memberId,
        pending,
        result.etag,
      );
      if (!active.current) return;
      remember({ ...record.current, pending: null, lastBatchId: checked.id });
      setSelected(checked.id);
      setVersion((old) => old + 1);
      setNotice(
        pending.kind === "preview"
          ? `已保存 ${checked.counts.total} 条预检查记录，尚未登记实交或成绩。请继续核对该批原始清单。`
          : `本批已确认：${checked.counts.imported} 条已登记或复用，${checked.counts.errors} 条冲突或失败原样保留。请分别核对逐项结果。`,
      );
      if (pending.kind === "confirm") onImported();
    } catch (failure) {
      if (!active.current) return;
      if (record.current.pending && definitiveHistoricalFailure(failure)) {
        try {
          remember({ ...record.current, pending: null });
          if (pending.kind === "confirm") {
            setSelected(pending.batchId);
            setVersion((old) => old + 1);
          }
        } catch (storageFailure) {
          setError(storageFailure);
          return;
        }
      }
      setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  const pending = recovery.pending,
    locked = busy || !!pending || !!initial.error;
  return (
    <section
      className="panel historical-imports"
      aria-label="历史实交与成绩批量导入"
    >
      <div className="section-heading">
        <div>
          <h2>历史实交与成绩批量导入</h2>
          <p className="muted">
            保存预检查、核对原始清单，再明确登记可处理记录。异常项和原批次始终保留。
          </p>
        </div>
        <button
          type="button"
          className="button secondary"
          aria-expanded={opened}
          onClick={() => setOpened((old) => !old)}
        >
          {opened ? "收起历史导入" : "打开历史导入"}
        </button>
      </div>
      {pending && !opened && (
        <p className="notice neutral">
          历史导入有尚未核对的原请求，请打开面板恢复。新导入和确认保持锁定。
        </p>
      )}
      <div className="historical-import-body" hidden={!opened}>
        {error != null && <ErrorNotice error={error} />}
        {notice && (
          <p className="notice success" role="status">
            {notice}
          </p>
        )}
        {pending && (
          <section className="notice neutral" aria-label="恢复未决历史导入">
            <strong>
              {pending.kind === "preview"
                ? "预检查保存结果尚未核对"
                : "导入确认结果尚未核对"}
            </strong>
            <p>
              原请求和幂等键已保留；确认操作还保留原版本条件。读取批次目录不会结束未决状态，请使用原操作恢复。
            </p>
            <details>
              <summary>原操作身份</summary>
              <p>操作键 {pending.key}</p>
              {pending.kind === "preview" ? (
                <p>原清单 {pending.body.records.length} 条</p>
              ) : (
                <>
                  <p>
                    批次 {pending.batchId} · 原修订 {pending.baseRevision}
                  </p>
                  <p>清单 SHA256 {pending.manifestDigest}</p>
                </>
              )}
            </details>
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() => void send(pending)}
            >
              {busy
                ? "正在核对原导入请求…"
                : pending.kind === "preview"
                  ? "恢复原预检查请求"
                  : "恢复原确认请求"}
            </button>
          </section>
        )}
        <HistoricalImportEditor
          key={editorVersion}
          seed={seed}
          disabled={
            locked ||
            readBusy ||
            !supportsApi("POST", "/research/import-previews")
          }
          onPreview={(request) =>
            send({
              kind: "preview",
              key: crypto.randomUUID(),
              body: request,
              etag: null,
            })
          }
        />
        {selected && (
          <HistoricalImportBatch
            key={`${selected}:${version}`}
            id={selected}
            disabled={locked}
            onBusy={onReadBusy}
            onConfirm={send}
            onRetry={(request, label) => {
              if (locked) return;
              setSeed({ request, label });
              setEditorVersion((old) => old + 1);
              setNotice(
                "已将所选异常项放入上方新清单。请修正、重新校验并明确创建预检查；没有发送任何新导入。",
              );
            }}
          />
        )}
        <HistoricalImportDirectory
          key={`directory:${version}`}
          selected={selected}
          onSelect={(id) => setSelected(id)}
        />
      </div>
    </section>
  );
}
