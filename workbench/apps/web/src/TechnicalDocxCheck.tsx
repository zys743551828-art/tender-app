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
  DOCX_TEXT_DEFAULTS_MISMATCH:
    "实际 Word 声明的默认字号或段后间距不符合已绑定字段；不判断各段真实显示",
  DOCX_TEXT_DEFAULTS_UNINSPECTABLE:
    "字号或段后间距的冻结依据或 Word 样式声明不明确，须人工核对",
  DOCX_TEXT_DEFAULTS_NO_FROZEN_BASIS:
    "没有已确认冻结的默认字号或段后间距字段，须按招标原文人工核对",
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
const defaultFields = [
  ["DOCX_DEFAULT_FONT", "默认字号"],
  ["DOCX_DEFAULT_PARAGRAPH_AFTER", "默认段后距"],
] as const;
const defaultText = {
  RAW_MATCH: "原始声明与已确认冻结字段一致；实际显示仍须人工核对。",
  RAW_MISMATCH: "原始声明与已确认冻结字段不一致；请核对后修改或重建。",
  NO_FROZEN_BASIS: "缺少已确认冻结依据，未作对照；模板默认值不能代替招标要求。",
  UNINSPECTABLE: "冻结依据或 Word 原始声明无法可靠核对，须转人工。",
} as const;
type DefaultState = keyof typeof defaultText;
type DefaultFinding = { label: string; state: DefaultState; code: string };
const legacyDefaultCodes = new Set([
  "DOCX_TEXT_DEFAULTS_MISMATCH",
  "DOCX_TEXT_DEFAULTS_UNINSPECTABLE",
  "DOCX_TEXT_DEFAULTS_NO_FROZEN_BASIS",
]);

function readDefaultFindings(
  blocking: string[],
  manual: string[],
): DefaultFinding[] | null {
  const rows: DefaultFinding[] = [];
  for (const [prefix, label] of defaultFields) {
    const blocked = blocking.filter((code) => code.startsWith(prefix + "_"));
    const human = manual.filter((code) => code.startsWith(prefix + "_"));
    if (!blocked.length && !human.length) continue;
    if (blocked.length + human.length !== 1) return null;
    const code = blocked[0] ?? human[0];
    const state = (Object.keys(defaultText) as DefaultState[]).find(
      (key) => code === prefix + "_" + key,
    );
    if (
      !state ||
      (state === "RAW_MISMATCH" || state === "UNINSPECTABLE") !==
        (blocked.length === 1)
    )
      return null;
    rows.push({ label, state, code });
  }
  if (!rows.length) return rows; // Read older advisories with their original codes.
  if (
    rows.length !== defaultFields.length ||
    blocking.includes("DOCX_TEXT_DEFAULTS_MISMATCH") !==
      rows.some((row) => row.state === "RAW_MISMATCH") ||
    (blocking.includes("DOCX_TEXT_DEFAULTS_UNINSPECTABLE") &&
      !rows.some((row) => row.state === "UNINSPECTABLE")) ||
    manual.includes("DOCX_TEXT_DEFAULTS_NO_FROZEN_BASIS") !==
      rows.every((row) => row.state === "NO_FROZEN_BASIS")
  )
    return null;
  return rows;
}

function groupedFindings(report: Check) {
  const defaults =
    readDefaultFindings(report.blocking_codes, report.manual_check_codes) ?? [];
  function general(codes: string[]) {
    return defaults.length
      ? codes.filter(
          (code) =>
            !legacyDefaultCodes.has(code) &&
            !defaults.some((row) => row.code === code),
        )
      : codes;
  }
  return {
    defaults,
    machine: general(report.blocking_codes),
    manual: general(report.manual_check_codes),
  };
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
  new Set(v).size === v.length &&
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
    value.manual_check_codes.includes("FORMAT_AND_RENDER_REVIEW") &&
    readDefaultFindings(value.blocking_codes, value.manual_check_codes) !== null
  );
}

function InternalReviewNotes({
  result,
  submittedIdentifierCount,
}: {
  result: Check;
  submittedIdentifierCount: number;
}) {
  const [copyState, setCopyState] = useState<"copied" | "unavailable" | null>(
    null,
  );
  const finding = (code: string) =>
    "• " + (known[code] ? message(code) + "（" + code + "）" : message(code));
  const { defaults, machine, manual } = groupedFindings(result);
  const lines = [
    "技术标 Word 内部核查摘要",
    "仅供工作台内部复核。这是固定历史文件的辅助检查，不是签收、独立审批、提交许可或版面合规证明。",
    `项目：${result.bid_id}`,
    `构建：${result.build_id}`,
    `文档版本：${result.document_version_id}`,
    `草稿快照：${result.snapshot_id}`,
    `草稿快照 SHA-256：${result.snapshot_digest}`,
    `受检文件 SHA-256：${result.artifact_sha256}`,
    `检查范围 SHA-256：${result.policy_sha256}`,
    submittedIdentifierCount
      ? `本次提交了 ${submittedIdentifierCount} 条自填禁用标识，不附明文，不是权威清单。`
      : "本次未提供项目禁用标识，未做该项比对。",
    "",
    "机器可核项：",
    ...(machine.length
      ? machine.map(finding)
      : [
          result.blocking_codes.length
            ? "默认文字样式的需处理项见下；其他可核项未见问题。"
            : "可核范围内未发现需处理项；仍须完成下列人工核对。",
        ]),
    ...(defaults.length
      ? [
          "",
          "Word 默认文字样式（只对照原始声明，不判断排版）：",
          ...defaults.map(
            ({ label, state, code }) =>
              `• ${label}：${defaultText[state]}（${code}）`,
          ),
        ]
      : []),
    "",
    "待人工核对（请另行记录结果）：",
    ...manual.map(finding),
  ];
  const summary = lines.join("\n");
  async function copy() {
    try {
      await navigator.clipboard.writeText(summary);
      setCopyState("copied");
    } catch {
      setCopyState("unavailable");
    }
  }
  return (
    <details className="coverage-details">
      <summary>内部核查摘要（单独留存）</summary>
      <p className="small-note">
        不附 Word
        正文、拟用文件名或自填标识，不写入提交文件，也不会发送给任何人。
      </p>
      <label>
        本次 Word 内部核查摘要
        <textarea readOnly value={summary} rows={8} />
      </label>
      <button
        type="button"
        className="button secondary"
        onClick={() => void copy()}
      >
        复制内部核查摘要
      </button>
      {copyState === "copied" && <p role="status">已复制，仅供内部核对。</p>}
      {copyState === "unavailable" && (
        <p role="status">当前不能访问剪贴板，可手动选中上方摘要。</p>
      )}
    </details>
  );
}

function Findings({ report }: { report: Check }) {
  const { defaults, machine, manual } = groupedFindings(report);
  return (
    <div role="status">
      <p>
        {report.blocking_codes.length
          ? "发现需处理项。修改或重新构建后请再检查。"
          : "这次机器检查在可核范围内未发现问题，不等于满足暗标要求，也不代表已通过独立审核。"}
      </p>
      {machine.length > 0 && (
        <ul>
          {machine.map((code) => (
            <li key={code}>{message(code)}</li>
          ))}
        </ul>
      )}
      {defaults.length > 0 && (
        <>
          <p>Word 默认文字样式（只对照原始声明，不判断排版）：</p>
          <ul aria-label="Word 默认文字样式逐字段核对">
            {defaults.map(({ label, state, code }) => (
              <li key={code}>
                <strong>{label}</strong>：{defaultText[state]}
              </li>
            ))}
          </ul>
        </>
      )}
      <p>仍需人工核对：</p>
      <ul>
        {manual.map((code) => (
          <li key={code}>{message(code)}</li>
        ))}
      </ul>
      <p className="small-note identity-ref">
        受检文件 SHA-256：{report.artifact_sha256}
      </p>
    </div>
  );
}

type DocxCheckProps = Scope & { suggestedFilename: string };

export function TechnicalDocxCheck(props: DocxCheckProps) {
  const key = JSON.stringify([
    props.bidId,
    props.buildId,
    props.documentId,
    props.snapshotId,
    props.snapshotDigest,
    props.suggestedFilename,
  ]);
  return <ScopedTechnicalDocxCheck key={key} {...props} />;
}

function ScopedTechnicalDocxCheck({
  suggestedFilename,
  ...scope
}: DocxCheckProps) {
  const [filename, setFilename] = useState(suggestedFilename);
  const [names, setNames] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastCheck, setLastCheck] = useState<{
    result: Check;
    submittedIdentifierCount: number;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const pending = useRef(false);
  const report =
    lastCheck && verified(lastCheck.result, scope) ? lastCheck.result : null;
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
    setLastCheck(null);
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
      setLastCheck({
        result: response.data,
        submittedIdentifierCount: terms.length,
      });
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
        页边距、默认字号和段后间距只对照本构建快照中人工确认并绑定来源的字段。
        Word 声明值不代替打开文件检查逐段样式或实际版面。
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
      {report && lastCheck && (
        <>
          <Findings report={report} />
          <InternalReviewNotes
            result={report}
            submittedIdentifierCount={lastCheck.submittedIdentifierCount}
          />
        </>
      )}
    </details>
  );
}
