import { useMemo, useState } from "react";
import { ErrorNotice } from "./components";
import type { PackageReviewHumanDecisionCurrent } from "./contracts";
import type { PackageReviewRow } from "./packageReviewProtocol";
import type { PackageReviewDecisionProps } from "./packageReviewDecisionProtocol";
import {
  packageReviewDecisionLabels,
  packageReviewDecisionQuotes,
  packageReviewDecisionStates,
} from "./packageReviewDecisionProtocol";
import { packageReviewDecisionScope } from "./packageReviewDecisionRecovery";
import { usePackageReviewDecisions } from "./usePackageReviewDecisions";
import PackageReviewReport from "./PackageReviewReport";
import PackageReviewDecisionHistory from "./PackageReviewDecisionHistory";

type Controller = ReturnType<typeof usePackageReviewDecisions>;
type HeadItem = PackageReviewHumanDecisionCurrent["items"][number];
type Props = PackageReviewDecisionProps & { focusRequirementId?: string };

function DecisionRow({
  p,
  row,
  head,
  controller,
  open,
  onOpen,
}: {
  p: PackageReviewDecisionProps;
  row: PackageReviewRow;
  head?: HeadItem;
  controller: Controller;
  open: boolean;
  onOpen: () => void;
}) {
  const draft = controller.draft(row),
    current = head?.current,
    pending = controller.record?.pending,
    disabled = controller.busy || !!pending || !controller.record,
    quotes = packageReviewDecisionQuotes(row),
    fieldId = `review-human-reason-${p.run.id}-${row.requirement_id}`;
  return (
    <section className="package-review__decision" aria-label="此项独立人工判断">
      <div className="package-review__heading">
        <div>
          <strong>人工判断</strong>
          {head ? (
            current ? (
              <>
                <p>
                  {packageReviewDecisionLabels[current.state]} · 第{" "}
                  {current.sequence_no} 版
                </p>
                <p>{current.reason}</p>
                <p className="muted">
                  最近读取的记录时间：{current.created_at}
                </p>
              </>
            ) : (
              <p className="muted">最近读取时尚无人工记录。</p>
            )
          ) : (
            <p className="muted">当前人工状态尚未读取。</p>
          )}
        </div>
        <button
          type="button"
          className="button secondary"
          aria-expanded={open}
          onClick={onOpen}
        >
          {open ? "收起人工判断" : "记录人工判断"}
        </button>
      </div>
      {open && (
        <>
          <p className="muted">
            人工意见单独留痕。“不采用此项判断”不表示风险已解决，也不改变原始机器结论或投递资格。
          </p>
          {!head && (
            <p>
              先读取当前人工状态，再提交本次意见。其他成员已更新的版本会由服务器拒绝覆盖。
            </p>
          )}
          <label htmlFor={fieldId}>本次人工理由（必填）</label>
          <textarea
            id={fieldId}
            value={draft.reason}
            maxLength={4000}
            disabled={disabled}
            onChange={(event) =>
              controller.changeDraft(row, {
                ...draft,
                reason: event.target.value,
              })
            }
            placeholder="说明采用、不采用或需要复查的依据与待处理问题"
          />
          <span className="muted">
            {Array.from(draft.reason).length} / 2000
            字。草稿随要求和原结果保存于当前浏览器会话。
          </span>
          {quotes.length > 0 && (
            <fieldset
              disabled={disabled}
              className="package-review__quote-choices"
            >
              <legend>本次意见引用的原文（可不选，最多 40 条）</legend>
              {quotes.map((quote, index) => (
                <label key={index} className="package-review__quote-choice">
                  <input
                    type="checkbox"
                    checked={draft.quoteIndexes.includes(index)}
                    onChange={(event) =>
                      controller.changeDraft(row, {
                        ...draft,
                        quoteIndexes: event.target.checked
                          ? [...draft.quoteIndexes, index]
                          : draft.quoteIndexes.filter(
                              (value) => value !== index,
                            ),
                      })
                    }
                  />
                  <span>
                    {quote.package_role === "target" ? "投标原文" : "招标依据"}{" "}
                    · {quote.member_id} · 物理页 {quote.physical_page}
                    <span className="package-review__quote-text">
                      {quote.quote}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>
          )}
          <div className="package-review__actions">
            {packageReviewDecisionStates.map((state) => (
              <button
                type="button"
                className="button secondary"
                key={state}
                disabled={
                  disabled ||
                  controller.reading ||
                  !head ||
                  !draft.reason.trim()
                }
                onClick={() => void controller.save(row, state)}
              >
                {packageReviewDecisionLabels[state]}
              </button>
            ))}
            <button
              type="button"
              className="button secondary"
              disabled={
                disabled || (!draft.reason && !draft.quoteIndexes.length)
              }
              onClick={() =>
                controller.changeDraft(row, { reason: "", quoteIndexes: [] })
              }
            >
              清空此项草稿
            </button>
          </div>
          {pending?.requirementId === row.requirement_id && (
            <p className="package-review__notice">
              本条原人工请求尚未确认：
              {packageReviewDecisionLabels[pending.body.state]}
              。请使用页面上的“恢复原人工处置请求”核对原键与原内容。
            </p>
          )}
          <PackageReviewDecisionHistory
            key={`${p.run.id}:${row.requirement_id}`}
            p={p}
            row={row}
          />
        </>
      )}
    </section>
  );
}

export default function PackageReviewHumanDecisions(p: Props) {
  if (!p.run.result) return null;
  return (
    <HumanDecisions
      key={JSON.stringify(packageReviewDecisionScope(p))}
      {...p}
    />
  );
}
function HumanDecisions(p: Props) {
  const controller = usePackageReviewDecisions(p),
    [selected, setSelected] = useState<string | null>(null),
    heads = useMemo(
      () =>
        new Map(
          controller.heads?.items.map((item) => [item.requirement_id, item]) ??
            [],
        ),
      [controller.heads],
    );
  const pending = controller.record?.pending,
    receipt = controller.receipt;
  return (
    <div className="package-review__human">
      <section
        className="package-review__human-controls"
        aria-label="人工处置当前状态与恢复"
      >
        <div className="package-review__heading">
          <div>
            <h4>人工复核记录</h4>
            <p>
              每项意见绑定本次报告及原条款。人工记录不新增事实证明，也不将整体覆盖提升为完整。
            </p>
          </div>
          <button
            type="button"
            className="button secondary"
            disabled={controller.busy || controller.reading}
            onClick={() => void controller.readCurrent()}
          >
            {controller.reading ? "正在读取人工状态…" : "读取当前人工状态"}
          </button>
        </div>
        {controller.heads && (
          <p role="status">
            已读取 {controller.heads.items.length}{" "}
            条要求的人工状态；保存时仍须通过版本核对。
          </p>
        )}
        {pending && (
          <div className="package-review__notice">
            <strong>原人工请求尚未确认</strong>
            <p>
              {packageReviewDecisionLabels[pending.body.state]} · 要求编号{" "}
              <code>{pending.requirementId}</code>
            </p>
            <p>{pending.body.reason}</p>
            <p>
              恢复会重发相同幂等键、条款摘要、原版本条件和原引用，期间不能另存其他人工判断。
            </p>
            <button
              type="button"
              className="button secondary"
              disabled={controller.busy}
              onClick={controller.recover}
            >
              {controller.busy ? "正在核对原人工请求…" : "恢复原人工处置请求"}
            </button>
          </div>
        )}
        {receipt && (
          <div className="package-review__selected" role="status">
            <strong>原请求已核对受理</strong>
            <p>
              {packageReviewDecisionLabels[receipt.manifest.state]} · 第{" "}
              {receipt.manifest.sequence_no} 版 · 要求{" "}
              <code>{receipt.manifest.requirement_id}</code>
            </p>
            <p>{receipt.manifest.reason}</p>
            <p className="muted">
              这是该请求的原回执。当前最新人工状态以上方重新读取及各条款显示为准。
            </p>
          </div>
        )}
        {controller.busy && !pending && <p role="status">正在保存人工记录…</p>}
        {controller.error != null && <ErrorNotice error={controller.error} />}
      </section>
      <PackageReviewReport
        key={p.focusRequirementId ?? "all"}
        run={p.run}
        focusRequirementId={p.focusRequirementId}
        renderDecision={(row) => (
          <DecisionRow
            p={p}
            row={row}
            head={heads.get(row.requirement_id)}
            controller={controller}
            open={selected === row.requirement_id}
            onOpen={() => {
              setSelected(
                selected === row.requirement_id ? null : row.requirement_id,
              );
              if (!controller.heads && !controller.reading && !controller.busy)
                void controller.readCurrent();
            }}
          />
        )}
      />
    </div>
  );
}
