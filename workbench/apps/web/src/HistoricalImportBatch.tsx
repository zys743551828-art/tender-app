import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  HistoricalImportBatch as Batch,
  HistoricalImportRequest,
  HistoricalImportSource,
} from "./contracts";
import { ErrorNotice } from "./components";
import { HistoricalImportRecordDetails } from "./HistoricalImportRecords";
import {
  historicalErrorNames,
  historicalFailure,
  historicalImportEtag,
  historicalImportPath,
  historicalSame,
  historicalRecordCounts,
  normalizeHistoricalRequest,
  validateHistoricalBatch,
  validateHistoricalSource,
  type HistoricalPending,
} from "./historicalImportProtocol";

const states = {
  pending: "预检查可处理",
  imported: "已登记或复用",
  conflict: "预检查冲突",
  failed: "确认时失败",
};
export function HistoricalImportBatch({
  id,
  disabled,
  onBusy,
  onConfirm,
  onRetry,
}: {
  id: string;
  disabled: boolean;
  onBusy: (value: boolean) => void;
  onConfirm: (pending: HistoricalPending) => Promise<void>;
  onRetry: (request: HistoricalImportRequest, label: string) => void;
}) {
  const [batch, setBatch] = useState<Batch | null>(null),
    [rows, setRows] = useState<Batch["records"]>([]);
  const [source, setSource] = useState<HistoricalImportSource | null>(null),
    [etag, setEtag] = useState<string | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [stale, setStale] = useState(false);
  const [confirmed, setConfirmed] = useState(false),
    [selected, setSelected] = useState<Set<string>>(new Set()),
    [shown, setShown] = useState(20);
  const active = useRef(false),
    running = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    onBusy(busy);
    return () => onBusy(false);
  }, [busy, onBusy]);
  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    running.current = true;
    void api<unknown>(`${historicalImportPath(id)}?limit=100`)
      .then((result) => {
        const checked = validateHistoricalBatch(result.data, {
          id,
          etag: result.etag,
        });
        if (cancelled) return;
        setBatch(checked);
        setRows(checked.records);
        setEtag(result.etag);
      })
      .catch((failure) => {
        if (!cancelled) setError(failure);
      })
      .finally(() => {
        if (!cancelled) {
          running.current = false;
          setBusy(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id]);
  async function reload() {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    setConfirmed(false);
    setSource(null);
    setSelected(new Set());
    try {
      const result = await api<unknown>(
        `${historicalImportPath(id)}?limit=100`,
      );
      const checked = validateHistoricalBatch(result.data, {
        id,
        etag: result.etag,
      });
      if (active.current) {
        setBatch(checked);
        setRows(checked.records);
        setEtag(result.etag);
        setStale(false);
        setShown(20);
      }
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function allRecords() {
    if (!batch || running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    setConfirmed(false);
    const captured = batch,
      tag = etag;
    let merged = [...rows],
      offset = merged.length;
    try {
      while (offset < captured.counts.total) {
        const result = await api<unknown>(
          `${historicalImportPath(id)}?limit=100&offset=${offset}`,
        );
        const page = validateHistoricalBatch(result.data, {
          id,
          offset,
          etag: result.etag,
        });
        if (
          result.etag !== tag ||
          page.revision !== captured.revision ||
          page.mode !== captured.mode ||
          page.manifest_blob_id !== captured.manifest_blob_id ||
          !historicalSame(page.counts, captured.counts)
        ) {
          if (active.current) setStale(true);
          historicalFailure(
            "批次在读取期间已变化，请保留当前结果并重新读取，不能按混合版本确认。",
          );
        }
        const known = new Set(merged.map((row) => row.external_record_id));
        if (page.records.some((row) => known.has(row.external_record_id)))
          historicalFailure("批次分页出现重复记录，未混合保存这些结果。");
        merged = [...merged, ...page.records];
        offset = merged.length;
        if (!active.current) return;
      }
      if (!historicalSame(historicalRecordCounts(merged), captured.counts))
        historicalFailure(
          "全部记录状态与批次汇总不一致，请重新读取核对，不能据此确认。",
        );
      if (source)
        await validateHistoricalSource(source, {
          ...captured,
          records: merged,
        });
      if (active.current) setRows(merged);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function readSource() {
    if (!batch || running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    setSource(null);
    setConfirmed(false);
    try {
      const result = await api<unknown>(`${historicalImportPath(id)}/source`);
      const checked = await validateHistoricalSource(result.data, {
        ...batch,
        records: rows,
      });
      if (active.current) setSource(checked);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  const complete = !!batch && rows.length === batch.counts.total;
  const allowed =
    !!batch &&
    !!source &&
    complete &&
    !stale &&
    !disabled &&
    !busy &&
    batch.mode === "dry_run" &&
    batch.counts.pending > 0;
  async function confirm() {
    if (!allowed || !batch || !source || !confirmed || running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    const captured = batch,
      sourceDigest = source.manifest_digest;
    try {
      const result = await api<unknown>(
        `${historicalImportPath(id)}?limit=100`,
      );
      const fresh = validateHistoricalBatch(result.data, {
        id,
        etag: result.etag,
      });
      if (result.etag !== etag || !historicalSame(fresh, captured)) {
        if (active.current) {
          setStale(true);
          setConfirmed(false);
        }
        historicalFailure(
          "这份预检查已变化，请重新读取和核对后再确认，不能自动改用新版本。",
        );
      }
      if (!active.current) return;
      await onConfirm({
        kind: "confirm",
        key: crypto.randomUUID(),
        body: {},
        etag: historicalImportEtag(id, captured.revision),
        batchId: id,
        baseRevision: captured.revision,
        manifestBlobId: captured.manifest_blob_id,
        manifestDigest: sourceDigest,
      });
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  function retry() {
    if (!source || !complete || disabled || busy || stale || !selected.size)
      return;
    const eligible = new Set(
      rows
        .filter(
          (row) =>
            (row.state === "failed" || row.state === "conflict") &&
            selected.has(row.external_record_id),
        )
        .map((row) => row.external_record_id),
    );
    if (eligible.size !== selected.size) {
      setError(new Error("重试选择包含非异常项，请重新核对。"));
      return;
    }
    const records = source.request.records.filter((record) =>
      eligible.has(record.external_record_id),
    );
    if (records.length !== eligible.size) {
      setError(new Error("异常项与原清单不一致，未准备新请求。"));
      return;
    }
    try {
      onRetry(
        normalizeHistoricalRequest({ records }),
        `从批次 ${id} 选出的 ${records.length} 条异常记录`,
      );
    } catch (failure) {
      setError(failure);
    }
  }
  const original = new Map(
    source?.request.records.map((record) => [
      record.external_record_id,
      record,
    ]),
  );
  function downloadSource() {
    if (!source) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(source.request, null, 2)], {
        type: "application/json",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `historical-import-${id}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  return (
    <section className="historical-import-batch" aria-label="历史导入批次详情">
      <div className="section-heading">
        <h3>2. 核对预检查与导入结果</h3>
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={() => void reload()}
        >
          重新读取此批
        </button>
      </div>
      {busy && <p role="status">正在核对导入批次…</p>}
      {error != null && <ErrorNotice error={error} />}
      {batch && (
        <>
          <p>
            <strong>
              {batch.mode === "dry_run"
                ? "已保存预检查，尚未登记实交与成绩"
                : "已确认导入，逐项结果已保留"}
            </strong>{" "}
            · 修订 {batch.revision}
          </p>
          <dl className="historical-import-counts">
            <div>
              <dt>总记录</dt>
              <dd>{batch.counts.total}</dd>
            </div>
            <div>
              <dt>可处理</dt>
              <dd>{batch.counts.pending}</dd>
            </div>
            <div>
              <dt>已登记 / 复用</dt>
              <dd>{batch.counts.imported}</dd>
            </div>
            <div>
              <dt>冲突 / 失败</dt>
              <dd>{batch.counts.errors}</dd>
            </div>
          </dl>
          <p className="notice neutral">
            历史导入保留线下实交事实，不补造当时的标准提交检查。资料入库也不表示成绩已核验或样本已准入；正式样本需另行核验技术成绩、来源及分组条件。
          </p>
          <div className="historical-import-toolbar">
            {!complete && (
              <button
                type="button"
                className="button secondary"
                disabled={busy}
                onClick={() => void allRecords()}
              >
                读取并核对全部 {batch.counts.total} 条记录（已读 {rows.length}）
              </button>
            )}
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() => void readSource()}
            >
              {source ? "重新核对原始清单" : "读取并核对本批原始清单"}
            </button>
          </div>
          {source && (
            <>
              <p className="notice success">
                已核对确切原始清单、完整记录数量及文件摘要。原件字节仍由确认服务重新读取核验。
              </p>
              <div className="historical-import-toolbar">
                <button
                  type="button"
                  className="text-button"
                  onClick={downloadSource}
                >
                  下载本批原始清单 JSON
                </button>
                <p className="small-note">
                  若待核验原件总量超过 1
                  GiB，请下载清单并明确拆分，另建预检查。下载不改变本批。
                </p>
              </div>
            </>
          )}
          {rows.slice(0, shown).map((row) => (
            <article
              key={row.external_record_id}
              className="historical-import-record"
            >
              <div className="section-heading">
                <h4>{row.external_record_id}</h4>
                <span className={`historical-import-state state-${row.state}`}>
                  {states[row.state]}
                </span>
              </div>
              {row.errors.length > 0 && (
                <ul>
                  {row.errors.map((code, index) => (
                    <li key={`${code}:${index}`}>
                      {historicalErrorNames[code] ??
                        "服务端记录了此项异常，请核对原始资料后再处理。"}
                      <small className="historical-import-code">{code}</small>
                    </li>
                  ))}
                </ul>
              )}
              {original.has(row.external_record_id) ? (
                <details>
                  <summary>核对本项原始实交与成绩</summary>
                  <HistoricalImportRecordDetails
                    record={original.get(row.external_record_id)!}
                    allowDownloads
                  />
                </details>
              ) : (
                <p className="small-note">
                  读取原始清单后可核对实交正文、证明、时间和成绩口径。
                </p>
              )}
              {(row.state === "failed" || row.state === "conflict") && (
                <label className="historical-import-check">
                  <input
                    type="checkbox"
                    disabled={disabled || busy || !source || !complete || stale}
                    checked={selected.has(row.external_record_id)}
                    onChange={(event) =>
                      setSelected((old) => {
                        const next = new Set(old);
                        if (event.target.checked)
                          next.add(row.external_record_id);
                        else next.delete(row.external_record_id);
                        return next;
                      })
                    }
                  />
                  <span>
                    仅选择异常项 {row.external_record_id}，修正后另建预检查
                  </span>
                </label>
              )}
            </article>
          ))}
          {shown < rows.length && (
            <button
              type="button"
              className="text-button"
              onClick={() => setShown((old) => old + 20)}
            >
              查看后续已读取记录（还剩 {rows.length - shown} 条）
            </button>
          )}
          {batch.counts.errors > 0 && (
            <div className="historical-import-toolbar">
              <button
                type="button"
                className="button secondary"
                disabled={
                  disabled ||
                  busy ||
                  !source ||
                  !complete ||
                  stale ||
                  !selected.size
                }
                onClick={retry}
              >
                准备所选 {selected.size} 条异常项的新清单
              </button>
              <p className="small-note">
                已登记项不会进入新清单；原批次保留，不会自动确认或覆写原成绩。
              </p>
            </div>
          )}
          {batch.mode === "dry_run" && (
            <div className="historical-import-confirm">
              <label className="historical-import-check">
                <input
                  type="checkbox"
                  disabled={!allowed}
                  checked={confirmed && allowed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                <span>
                  我已核对全部 {batch.counts.total}{" "}
                  条记录与原始清单，同意仅处理其中 {batch.counts.pending}{" "}
                  条可处理记录；{batch.counts.errors} 条异常保留，不当作成功。
                </span>
              </label>
              <button
                type="button"
                className="button primary"
                disabled={!allowed || !confirmed}
                onClick={() => void confirm()}
              >
                确认登记本批可处理的历史实交与成绩
              </button>
              {!source || !complete ? (
                <p className="small-note">
                  确认前须读取全部记录并核对本批原始清单。
                </p>
              ) : batch.counts.pending === 0 ? (
                <p>没有可处理项，请先修正异常并创建新的预检查。</p>
              ) : null}
            </div>
          )}
          <details>
            <summary>批次和清单身份</summary>
            <p>批次 {batch.id}</p>
            <p>清单文件 {batch.manifest_blob_id}</p>
            {source && <p>清单 SHA256 {source.manifest_digest}</p>}
            <p>
              行摘要是服务端按原件字节和实交、成绩身份建立的去重指纹；不会按记录编号制造独立样本。
            </p>
          </details>
        </>
      )}
    </section>
  );
}
