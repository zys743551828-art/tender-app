import { useEffect, useRef, useState } from "react";
import type { HistoricalImportRequest } from "./contracts";
import { ErrorNotice } from "./components";
import { HistoricalImportRecordDetails } from "./HistoricalImportRecords";
import {
  historicalImportLimit,
  parseHistoricalFile,
} from "./historicalImportProtocol";

export type HistoricalSeed = {
  request: HistoricalImportRequest;
  label: string;
};
const template = {
  records: [
    {
      external_record_id: "历史档案-001",
      bid_id: "替换为确切项目UUID",
      actual_document_version_id: "替换为已登记实交正文版本UUID",
      submitted_at: "2025-01-01T09:00:00+08:00",
      evidence_ref: "替换为实交证明原件版本UUID",
      explanation: "说明这份文件何时以何种方式实际提交，并保留相应证明。",
      score_kind: "unknown",
      value: null,
      maximum: null,
      source_version_id: null,
      known_at: null,
    },
  ],
};
export function HistoricalImportEditor({
  disabled,
  seed,
  onPreview,
}: {
  disabled: boolean;
  seed: HistoricalSeed | null;
  onPreview: (request: HistoricalImportRequest) => Promise<void>;
}) {
  const [raw, setRaw] = useState(
    seed ? JSON.stringify(seed.request, null, 2) : "",
  );
  const [label, setLabel] = useState(seed?.label ?? ""),
    [checked, setChecked] = useState<HistoricalImportRequest | null>(null);
  const [error, setError] = useState<unknown>(null),
    [reading, setReading] = useState(false),
    [shown, setShown] = useState(20);
  const reader = useRef<FileReader | null>(null),
    active = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      reader.current?.abort();
    };
  }, []);
  function edit(value: string) {
    reader.current?.abort();
    setReading(false);
    setRaw(value);
    setChecked(null);
    setError(null);
    setShown(20);
  }
  function load(file: File) {
    if (disabled) return;
    reader.current?.abort();
    setRaw("");
    setChecked(null);
    setError(null);
    setShown(20);
    setLabel(file.name);
    if (file.size > historicalImportLimit) {
      setError(new Error("文件超过 8 MiB，请拆分清单后再选择。"));
      return;
    }
    setReading(true);
    const next = new FileReader();
    reader.current = next;
    next.onload = () => {
      if (!active.current || reader.current !== next) return;
      setRaw(String(next.result ?? ""));
      setReading(false);
    };
    next.onerror = () => {
      if (!active.current || reader.current !== next) return;
      setReading(false);
      setError(new Error("无法读取所选文件，请重新选择。"));
    };
    next.readAsText(file, "utf-8");
  }
  function check() {
    try {
      setError(null);
      setChecked(parseHistoricalFile(raw));
      setShown(20);
    } catch (failure) {
      setChecked(null);
      setError(failure);
    }
  }
  function download() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(template, null, 2)], {
        type: "application/json",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "historical-import-template.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  return (
    <section className="historical-import-editor" aria-label="准备历史导入清单">
      <h3>1. 准备并核对清单</h3>
      <p>
        先在对应项目登记实交正文、实交证明和官方成绩原件，再选择这些确切版本。每批最多
        1000 条、8 MiB；不会以文件名或最新版本代替。
      </p>
      {seed && (
        <p className="notice neutral">
          {seed.label}。这里只准备新的清单，不改原批次，也未创建新预检查。
        </p>
      )}
      <div className="historical-import-toolbar">
        <label>
          选择 JSON 清单
          <input
            type="file"
            accept=".json,application/json"
            disabled={disabled || reading}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) load(file);
              event.target.value = "";
            }}
          />
        </label>
        <button type="button" className="button secondary" onClick={download}>
          下载清单格式示例
        </button>
      </div>
      <details>
        <summary>清单字段与成绩填写规则</summary>
        <p>
          最外层只含 records 数组。每条需
          external_record_id、bid_id、actual_document_version_id、submitted_at、evidence_ref、explanation、score_kind、value、maximum、source_version_id、known_at；缺省值明确写
          null。
        </p>
        <p>
          score_kind 为
          technical_total（技术总分）、comprehensive_total（综合总分）或
          unknown（未知）。分数用字符串保留小数：真实零分写 "0" 并填满分，未知写
          null；已知成绩须附官方原件与取得时间。
        </p>
        <p>
          时间须含秒和时区，最多六位小数。例如
          2025-01-01T09:00:00.123456+08:00。校验只规范 UUID 大小写、UTC
          表示和小数位，不截断微秒或更换时间。
        </p>
      </details>
      {label && <p className="small-note">当前清单：{label}</p>}
      <label>
        清单 JSON（可修正后重新校验）
        <textarea
          aria-label="清单 JSON（可修正后重新校验）"
          className="historical-import-json"
          rows={12}
          value={raw}
          disabled={disabled || reading}
          onChange={(event) => edit(event.target.value)}
          spellCheck={false}
        />
      </label>
      <div className="historical-import-toolbar">
        <button
          type="button"
          className="button secondary"
          disabled={disabled || reading || !raw.trim()}
          onClick={check}
        >
          {reading ? "正在读取文件…" : "校验本地清单"}
        </button>
        <p className="small-note">本地校验不会发送或保存导入批次。</p>
      </div>
      {error != null && <ErrorNotice error={error} />}
      {checked && (
        <div className="historical-import-local-preview">
          <h4>本地清单可读取 · {checked.records.length} 条</h4>
          <p className="small-note">
            以下为将提交的规范值。项目、原件、重复资料和成绩关系仍需服务端预检查，原件字节将在确认时重新核验。
          </p>
          {checked.records.slice(0, shown).map((record) => (
            <details
              key={record.external_record_id}
              className="historical-import-record"
            >
              <summary>
                {record.external_record_id} ·{" "}
                {record.value === null
                  ? "未知分值"
                  : `${record.value} / ${record.maximum}`}
              </summary>
              <HistoricalImportRecordDetails record={record} />
            </details>
          ))}
          {shown < checked.records.length && (
            <button
              type="button"
              className="text-button"
              onClick={() => setShown((old) => old + 20)}
            >
              查看后续本地记录
            </button>
          )}
          <button
            type="button"
            className="button primary"
            disabled={disabled || reading}
            onClick={() => void onPreview(structuredClone(checked))}
          >
            创建并保存导入预检查（{checked.records.length} 条）
          </button>
          <p className="small-note">
            此按钮会保存一份导入清单及逐项预检查记录。实交和成绩尚未登记，需在下一步明确确认。
          </p>
        </div>
      )}
    </section>
  );
}
