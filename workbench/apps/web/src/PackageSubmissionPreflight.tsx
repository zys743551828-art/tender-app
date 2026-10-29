import { Fragment, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Badge, ErrorNotice } from "./components";
import type {
  PackageSubmissionPreflightView,
  PackageSubmissionPreview,
} from "./contracts";
import {
  packageSubmissionBase,
  type PackageSubmissionScope,
} from "./packageSubmissionProtocol";
import { validateSubmissionPreflight } from "./packageSubmissionPreflightProtocol";
import { historyTime } from "./packageHistoryPresentation";

const stateNames = {
  pass: "此项已满足",
  unknown: "仍有未知",
  blocked: "存在阻断",
};
const gateNames = {
  current_input: "当前输入与来源",
  core_coverage: "已知核心要求覆盖",
  mandatory_confirmation: "核心条款逐项确认",
  known_blocking_risks: "全项目已知阻断风险",
};

export function PackageSubmissionPreflight({
  preview,
  scope,
  disabled = false,
}: {
  preview: PackageSubmissionPreview;
  scope: PackageSubmissionScope;
  disabled?: boolean;
}) {
  const [receipt, setReceipt] = useState<{
    identity: string;
    value: PackageSubmissionPreflightView;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const generation = useRef(0);
  const working = useRef(false);
  const identity = `${scope.bidId}:${scope.memberId}:${preview.input_digest}:${preview.bid_etag}:${preview.gate.digest}`;
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;
  const result = receipt?.identity === identity ? receipt.value : null;
  useEffect(() => {
    generation.current += 1;
    working.current = false;
    setReceipt(null);
    setBusy(false);
    setError(null);
    return () => {
      generation.current += 1;
    };
  }, [identity]);
  useEffect(() => {
    function expired() {
      generation.current += 1;
      working.current = false;
      setReceipt(null);
      setBusy(false);
      setError(new Error("登录状态已变化，请重新登录后读取提交检查。"));
    }
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  async function verify() {
    if (disabled || working.current) return;
    const token = ++generation.current,
      chosenIdentity = identity;
    working.current = true;
    setBusy(true);
    setReceipt(null);
    setError(null);
    try {
      const { data } = await api<PackageSubmissionPreflightView>(
        `${packageSubmissionBase(scope.bidId, preview.selection_request)}/submission-preflight`,
        {
          method: "POST",
          etag: preview.bid_etag,
          body: {
            selection: preview.selection_request,
            input_digest: preview.input_digest,
          },
        },
      );
      const checked = await validateSubmissionPreflight(data, preview, scope);
      if (
        generation.current === token &&
        currentIdentity.current === chosenIdentity
      )
        setReceipt({ identity: chosenIdentity, value: checked });
    } catch (failure) {
      if (
        generation.current === token &&
        currentIdentity.current === chosenIdentity
      )
        setError(failure);
    } finally {
      if (
        generation.current === token &&
        currentIdentity.current === chosenIdentity
      ) {
        working.current = false;
        setBusy(false);
      }
    }
  }
  return (
    <section
      className="package-submission-gates"
      aria-label="原件与运行依据复核"
    >
      <h3>提交前原件复核</h3>
      <p>
        读取所选投标包、依据包及来源祖先的原件，核对文件大小与摘要，并重新检查项目状态和所选核查的运行依据。
      </p>
      <button
        type="button"
        className="button secondary"
        disabled={disabled || busy}
        onClick={() => void verify()}
      >
        {busy ? "正在核验原件与运行依据…" : "核验所选整包原件"}
      </button>
      <p className="small-note">
        每份原件在本次读取时核验，随后重读数据库状态。复核结果仅适用于显示的检查时点；不登记提交事实，也不授予标准提交资格。
      </p>
      <ErrorNotice error={error} />
      {result && (
        <div role="status">
          <p>
            <strong>本次原件核验已完成</strong>：
            {result.manifest.originals.length} 份原件与来源文件。
          </p>
          <p>
            运行依据：
            {result.manifest.review_runtime.state === "matched"
              ? "已与原核查逐项匹配"
              : result.manifest.review_runtime.state === "not_selected"
                ? "尚未选择核查运行"
                : "存在变化或阻断"}
            。
          </p>
          <p className="small-note">
            复核时点（北京时间） {historyTime(result.manifest.checked_at)}
          </p>
          <dl className="package-submission-counts">
            {(Object.keys(gateNames) as (keyof typeof gateNames)[]).map(
              (key) => (
                <Fragment key={key}>
                  <dt>{gateNames[key]}</dt>
                  <dd>
                    <Badge
                      tone={
                        result.manifest.gates[key].state === "pass"
                          ? ""
                          : "warning"
                      }
                    >
                      {stateNames[result.manifest.gates[key].state]}
                    </Badge>
                  </dd>
                </Fragment>
              ),
            )}
          </dl>
          <p className="notice warning">
            标准登记仍未获准。清单语义完整性与核查质量仍需证明。
          </p>
          <details>
            <summary>查看原件复核身份与原因</summary>
            <p className="digest">复核摘要 {result.digest}</p>
            <p className="digest">原始复核时刻 {result.manifest.checked_at}</p>
            <p className="digest">所选检查 {result.manifest.input_digest}</p>
            <ul>
              {result.manifest.gates.current_input.codes.map((code) => (
                <li className="digest" key={code}>
                  {code}
                </li>
              ))}
            </ul>
            <p className="small-note">
              原件读取与数据库复查不构成跨存储的原子快照；之后发生的变化需要重新核验。
            </p>
          </details>
        </div>
      )}
    </section>
  );
}
