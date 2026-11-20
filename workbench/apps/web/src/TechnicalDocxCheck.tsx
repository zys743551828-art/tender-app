import { useRef, useState } from "react";
import { api } from "./api";
import { ErrorNotice } from "./components";
import {
  exactKeys,
  executionSha,
  recordObject,
} from "./executionInputValidation";

type Scope = {
  bidId: string;
  buildId: string;
  documentId: string;
  snapshotId: string;
  snapshotDigest: string;
};
type Check = {
  protocol: "technical-candidate-docx-check/1";
  bid_id: string;
  build_id: string;
  document_version_id: string;
  snapshot_id: string;
  snapshot_digest: string;
  artifact_sha256: string;
  policy_sha256: string;
  blocking_codes: string[];
  manual_check_codes: string[];
  historical_advisory: true;
  publication_authorized: false;
};
const known: Record<string, string> = {
  CONTENT_AND_PROJECT_RULE_REVIEW: "人工核对正文、招标要求及响应覆盖",
  FORMAT_AND_RENDER_REVIEW: "打开 Word 核对实际排版、字体、分页和目录",
  IMAGE_VISUAL_AND_METADATA_REVIEW: "人工查看图表、照片及其可识别标识",
  PROHIBITED_NAME_FILENAME: "拟用文件名出现本次核查的禁止标识",
  AUTHOR_METADATA: "文件作者属性尚未清理",
  COMMENT_CONTENT: "文档保留了批注或批注标记",
  TRACKED_CHANGES: "文档保留了修订记录",
  HIDDEN_CONTENT: "文档含隐藏内容",
  CANDIDATE_DOCX_INVALID: "不是可核验的标准 DOCX",
  DOCX_EXPLICIT_PLACEHOLDER:
    "实际 Word 的正文、页眉页脚或脚注/尾注发现明确的占位标记，请逐项核对并补全",

  DOCX_PAGE_MARGINS_MISMATCH:
    "检测到 Word 页面边距与本稿冻结的已确认要求不一致",
  DOCX_PAGE_MARGINS_UNINSPECTABLE:
    "冻结的页边距依据或 Word 分节参数不完整，无法可靠核对",
  DOCX_PAGE_MARGINS_NO_FROZEN_BASIS:
    "没有可用于对照的已确认冻结页边距要求，须按招标原文人工核对",
};
function message(code: string) {
  return (
    known[code] ??
    (code.startsWith("PROHIBITED_NAME_")
      ? "文件内容、文档属性或内部部件出现本次核查的禁止标识"
      : "发现需要处理的文件项") +
      "（" +
      code +
      "）"
  );
}
const checkKeys = [
  "protocol",
  "bid_id",
  "build_id",
  "document_version_id",
  "snapshot_id",
  "snapshot_digest",
  "artifact_sha256",
  "policy_sha256",
  "blocking_codes",
  "manual_check_codes",
  "historical_advisory",
  "publication_authorized",
];
const validCodes = (v: unknown): v is string[] =>
  Array.isArray(v) &&
  v.length <= 100 &&
  v.every((x) => typeof x === "string" && /^[A-Z][A-Z0-9_]{2,80}$/.test(x));
function verified(value: unknown, scope: Scope): value is Check {
  return (
    recordObject(value) &&
    exactKeys(value, checkKeys) &&
    value.protocol === "technical-candidate-docx-check/1" &&
    value.bid_id === scope.bidId &&
    value.build_id === scope.buildId &&
    value.document_version_id === scope.documentId &&
    value.snapshot_id === scope.snapshotId &&
    value.snapshot_digest === scope.snapshotDigest &&
    executionSha(value.artifact_sha256) &&
    executionSha(value.policy_sha256) &&
    value.historical_advisory === true &&
    value.publication_authorized === false &&
    validCodes(value.blocking_codes) &&
    validCodes(value.manual_check_codes) &&
    value.manual_check_codes.includes("CONTENT_AND_PROJECT_RULE_REVIEW") &&
    value.manual_check_codes.includes("FORMAT_AND_RENDER_REVIEW")
  );
}

export function TechnicalDocxCheck({
  suggestedFilename,
  ...scope
}: Scope & { suggestedFilename: string }) {
  const [filename, setFilename] = useState(suggestedFilename);
  const [names, setNames] = useState("");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<Check | null>(null);
  const [error, setError] = useState<unknown>(null);
  const pending = useRef(false);
  const terms = Array.from(
    new Set(
      names
        .split(/\r?\n/)
        .map((term) => term.trim())
        .filter(Boolean),
    ),
  );
  const valid =
    filename.trim().length > 0 &&
    terms.length <= 100 &&
    terms.every((term) => Array.from(term).length <= 200);
  function clear() {
    setError(null);
    setReport(null);
  }
  async function inspect() {
    if (!valid || pending.current) return;
    clear();
    pending.current = true;
    setBusy(true);
    try {
      const response = await api<unknown>(
        "/bids/" +
          scope.bidId +
          "/builds/" +
          scope.buildId +
          "/technical-docx-check",
        {
          method: "POST",
          body: {
            document_version_id: scope.documentId,
            filename: filename.trim(),
            prohibited_names: terms,
          },
        },
      );
      if (!verified(response.data, scope))
        throw new Error(
          "核查结果与所选 Word 或固定快照不一致，未展示其它版本的结果。",
        );
      setReport(response.data);
    } catch (failure) {
      setError(failure);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <details className="coverage-details">
      <summary>技术标 Word 检查（送审前）</summary>
      <p className="small-note">
        检查本构建的实际文件，不改稿、不自动提交。请按招标要求输入要检查的名称和别名；留空不会检查项目禁用标识。
        页边距只对照本构建快照中人工确认并绑定来源的字段，不代替打开 Word
        检查版面。
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void inspect();
        }}
      >
        <fieldset disabled={busy}>
          <legend>当前 Word 的检查范围</legend>
          <label>
            拟用文件名
            <input
              value={filename}
              maxLength={255}
              onChange={(event) => {
                clear();
                setFilename(event.target.value);
              }}
            />
          </label>
          <label>
            本项目禁用标识（每行一项，可留空）
            <textarea
              value={names}
              maxLength={20100}
              rows={4}
              onChange={(event) => {
                clear();
                setNames(event.target.value);
              }}
            />
          </label>
          {!valid && (
            <p className="small-note">
              请填写拟用文件名，禁用标识最多 100 条，每条不超过 200 字。
            </p>
          )}
          <button
            type="submit"
            className="button secondary"
            disabled={!valid || busy}
          >
            {busy ? "正在核查实际 Word…" : "检查这个 Word"}
          </button>
        </fieldset>
      </form>
      <ErrorNotice error={error} />
      {report && (
        <div role="status">
          <p>
            {report.blocking_codes.length
              ? "发现需处理项。修改或重新构建后请再检查。"
              : "这次机器检查在可核范围内未发现问题，不等于满足暗标要求，也不代表已通过独立审核。"}
          </p>
          {report.blocking_codes.length > 0 && (
            <ul>
              {report.blocking_codes.map((code) => (
                <li key={code}>{message(code)}</li>
              ))}
            </ul>
          )}
          <p>仍需人工核对：</p>
          <ul>
            {report.manual_check_codes.map((code) => (
              <li key={code}>{message(code)}</li>
            ))}
          </ul>
          <p className="small-note identity-ref">
            受检文件 SHA-256：{report.artifact_sha256}
          </p>
        </div>
      )}
    </details>
  );
}
