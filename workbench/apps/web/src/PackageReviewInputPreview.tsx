import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import type {
  BidPackageStoredView,
  PackageCoverageAttemptView,
  PackageRequirementInventoryView,
  PackageReviewInputPreview as Preview,
} from "./contracts";

type Props = {
  bidId: string;
  packageView: BidPackageStoredView;
  inventory: PackageRequirementInventoryView | null;
  coverage: PackageCoverageAttemptView | null;
  coveragePending?: boolean;
  disabled?: boolean;
};
const messages: Record<Preview["blockers"][number], string> = {
  PROJECT_WORK_CLOSED: "项目已结束或归档，保留只读输入。",
  PACKAGE_BIDDER_UNCONFIRMED: "投标主体尚未确认。",
  PACKAGE_REVIEW_IDENTITY_STALE: "主体、工程、标段或轮次身份已变化。",
  PACKAGE_REVIEW_PACKAGE_STALE: "所选包已是历史修订，请明确核对当前包。",
  PACKAGE_REVIEW_INVENTORY_STALE: "所选要求清单已是历史版本。",
  PACKAGE_REVIEW_RULE_SET_STALE: "当前规则集已更新，需重新核对要求清单。",
  PACKAGE_REVIEW_SOURCE_UNPROVEN: "尚无可证明的完整来源范围。",
  PACKAGE_REVIEW_SOURCE_CHANGED: "来源效力记录已变化，旧输入保持原样。",
  PACKAGE_REVIEW_SOURCE_NOT_EFFECTIVE: "来源尚未生效、已撤回、过期或用途不符。",
  PACKAGE_REVIEW_MEMBERS_UNPROVEN: "成员的解析、页数或逻辑范围仍未明确。",
  PACKAGE_REVIEW_PHYSICAL_RANGE_GAP: "包内仍有未纳入逻辑范围的物理页。",
  PACKAGE_REVIEW_EXTRACTION_UNPROVEN: "要求抽取尚无精确冻结输入与完成绑定。",
  PACKAGE_REVIEW_REQUIREMENT_COMPLETENESS_UNPROVEN:
    "要求清单完整性尚未获得证明。",
  PACKAGE_REVIEW_EXECUTOR_NOT_READY: "正式整包评审执行器尚未接入。",
};

export function PackageReviewInputPreview({
  bidId,
  packageView,
  inventory,
  coverage,
  coveragePending = false,
  disabled = false,
}: Props) {
  const m = packageView.manifest;
  const key = JSON.stringify([
    bidId,
    m.package_id,
    m.revision_id,
    packageView.digest,
    inventory?.manifest.id,
    inventory?.digest,
    coverage?.manifest.id,
    coverage?.digest,
  ]);
  const active = useRef(key);
  const generation = useRef(0);
  active.current = key;
  const [state, setState] = useState<{
    key: string;
    busy?: boolean;
    result?: Preview;
    error?: unknown;
  } | null>(null);
  useEffect(() => {
    active.current = key;
    generation.current += 1;
    setState(null);
    return () => {
      active.current = "";
      generation.current += 1;
    };
  }, [key]);
  const current = state?.key === key ? state : null;
  const base = `/bids/${bidId}/packages/${m.package_id}/revisions/${m.revision_id}/requirement-inventories`;
  const path = `${base}/${inventory?.manifest.id ?? "missing"}/review-input-preview`;
  const available = supportsApi("POST", path);

  async function inspect() {
    if (
      !inventory ||
      coveragePending ||
      disabled ||
      current?.busy ||
      !available
    )
      return;
    const captured = key;
    const ticket = ++generation.current;
    setState({ key: captured, busy: true });
    try {
      const { data } = await api<Preview>(path, {
        method: "POST",
        body: {
          package_digest: packageView.digest,
          inventory_digest: inventory.digest,
          coverage_attempt_id: coverage?.manifest.id ?? null,
          coverage_digest: coverage?.digest ?? null,
        },
      });
      if (active.current !== captured || generation.current !== ticket) return;
      const input = data.manifest;
      if (
        input?.version !== "bid-package-review-input/1" ||
        input.kind !== "preview" ||
        input.bid_id !== bidId ||
        input.target?.digest !== packageView.digest ||
        input.target.manifest.package_id !== m.package_id ||
        input.target.manifest.revision_id !== m.revision_id ||
        input.target.manifest.kind !== "bid" ||
        Object.entries(m.scope).some(
          ([field, value]) =>
            input.target.manifest.scope[field as keyof typeof m.scope] !==
            value,
        ) ||
        input.authority?.digest !== inventory.manifest.authority_digest ||
        input.authority.manifest.revision_id !==
          inventory.manifest.authority_revision_id ||
        input.authority.manifest.kind !== "authority" ||
        Object.entries(m.scope).some(
          ([field, value]) =>
            input.authority.manifest.scope[field as keyof typeof m.scope] !==
            value,
        ) ||
        input.inventory?.digest !== inventory.digest ||
        input.inventory.manifest.id !== inventory.manifest.id ||
        input.inventory.manifest.package_digest !== packageView.digest ||
        input.inventory.manifest.rule_set_id !==
          inventory.manifest.rule_set_id ||
        input.inventory.manifest.rule_set_digest !==
          inventory.manifest.rule_set_digest ||
        (coverage
          ? input.coverage?.manifest.id !== coverage.manifest.id ||
            input.coverage.digest !== coverage.digest
          : input.coverage !== null) ||
        data.review_ready !== false ||
        data.launch_available !== false ||
        !/^[a-f0-9]{64}$/.test(data.digest) ||
        !Array.isArray(data.blockers) ||
        !data.blockers.length ||
        data.blockers.some(
          (code) => !Object.prototype.hasOwnProperty.call(messages, code),
        ) ||
        !Array.isArray(data.physical_page_gaps)
      )
        throw new Error(
          "预检响应与所选包、清单或范围记录不一致，未采用其他输入。",
        );
      setState({ key: captured, result: data });
    } catch (error) {
      if (active.current === captured && generation.current === ticket)
        setState({ key: captured, error });
    }
  }

  return (
    <div>
      <h4>整包评审输入预检</h4>
      <p>
        核对当前明确选择的本方包、权威依据和要求清单；可附上所选人工范围记录。只读检查，不启动评审或模型调用。
      </p>
      {!inventory && <p>先读取一版要求清单，再检查它对应的整包输入。</p>}
      {!available && <p>当前服务尚未提供整包输入预检。</p>}
      <button
        type="button"
        disabled={
          !inventory ||
          coveragePending ||
          disabled ||
          !!current?.busy ||
          !available
        }
        onClick={() => void inspect()}
      >
        {current?.busy ? "正在核对整包输入…" : "检查所选整包评审输入"}
      </button>
      {current?.error != null && (
        <ErrorNotice error={current.error} onRetry={() => void inspect()} />
      )}
      {current?.result && (
        <div role="status">
          <h5>暂不可正式评审</h5>
          <p>
            没有创建评审任务；人工范围声明、解析成功或预检成功均不表示整包合规。
          </p>
          <ul>
            {current.result.blockers.map((code) => (
              <li key={code}>{messages[code]}</li>
            ))}
          </ul>
          {!!current.result.physical_page_gaps.length && (
            <ul>
              {current.result.physical_page_gaps.map((gap, i) => (
                <li key={i}>
                  {gap.role === "target" ? "本方包" : "权威依据包"}成员{" "}
                  {gap.member_id}：物理页 {gap.first_page}—{gap.last_page}{" "}
                  未纳入逻辑范围
                </li>
              ))}
            </ul>
          )}
          <details>
            <summary>本次明确选择的输入身份</summary>
            <p>输入摘要 {current.result.digest}</p>
            <p>
              本方包修订 {current.result.manifest.target.manifest.revision_id} ·{" "}
              {current.result.manifest.target.manifest.members.length}{" "}
              个文件版本
            </p>
            <p>
              权威依据修订{" "}
              {current.result.manifest.authority.manifest.revision_id} ·{" "}
              {current.result.manifest.authority.manifest.members.length}{" "}
              个文件版本
            </p>
            <p>要求清单 {current.result.manifest.inventory.manifest.id}</p>
            {(["target", "authority"] as const).map((role) => (
              <ul key={role}>
                {current.result!.manifest[role].manifest.members.map(
                  (file, index) => (
                    <li key={file.member_id}>
                      {role === "target" ? "本方文件" : "权威文件"} {index + 1}{" "}
                      ·{" "}
                      {file.page_count === null
                        ? "页数未知"
                        : `${file.page_count}页`}{" "}
                      ·{" "}
                      {file.parse.status === "frozen"
                        ? "精确解析已冻结"
                        : "解析身份未冻结"}{" "}
                      ·{" "}
                      {file.parts.length
                        ? `${file.parts.length}个逻辑部分`
                        : "逻辑范围未划分"}
                    </li>
                  ),
                )}
              </ul>
            ))}
            <p>
              {current.result.manifest.coverage
                ? `人工范围记录 ${current.result.manifest.coverage.manifest.id}`
                : "本次未附人工范围记录"}
            </p>
          </details>
        </div>
      )}
    </div>
  );
}
