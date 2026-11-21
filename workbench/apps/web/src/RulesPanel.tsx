import { useState } from "react";
import type {
  BatchRuleConfirmation,
  Bid,
  Operation,
  ReviewStateView,
  RuleSetView,
} from "./contracts";
import { ApiError, supportsApi } from "./api";
import { ruleConfirmationLimit } from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { DecisionForm } from "./DecisionForm";
import { EvidenceLinks } from "./EvidenceLinks";
import { ResourceState } from "./ResourceState";
import { ManualRuleForm } from "./ManualRuleForm";
import { useCommand } from "./useCommand";
import { useResource } from "./useResource";
import { confirmationNames, ruleKindNames } from "./workspaceTypes";

export function RulesPanel({
  bid,
  reviewState,
  reviewStateError,
  onChanged,
  onMaterials,
}: {
  bid: Bid;
  reviewState?: ReviewStateView;
  reviewStateError?: unknown;
  onChanged: () => void;
  onMaterials?: () => void;
}) {
  const resource = useResource<RuleSetView>(`/bids/${bid.id}/rules`);
  const notReady =
    !resource.data &&
    resource.error instanceof ApiError &&
    resource.error.status === 409 &&
    resource.error.code === "RULE_SET_NOT_READY";
  const state =
    reviewState?.bid_id === bid.id &&
    reviewState.material_revision === bid.material_revision
      ? reviewState
      : undefined;
  const needsMaterials =
    state?.current_material_snapshot_id === null && state.request === null;
  const request =
    state?.request &&
    state.request.material_snapshot_id === state.current_material_snapshot_id &&
    state.request.material_revision === state.material_revision
      ? state.request
      : null;
  const waitingForService =
    state?.review_execution_configured === false &&
    (!request || request.state === "preparing");
  const blocked =
    notReady &&
    !state?.current_rule_set_id &&
    request?.state === "blocked" &&
    !request.review_id;
  const operation = useResource<Operation>(
    blocked ? `/operations/${request.prepare_operation_id}` : null,
  );
  const operationError =
    operation.error ??
    (operation.data &&
    (operation.data.bid_id !== bid.id ||
      operation.data.id !== request?.prepare_operation_id)
      ? new Error("准备任务与当前请求不一致，请重新读取。")
      : undefined);
  const failedExtraction =
    blocked &&
    !reviewStateError &&
    !operationError &&
    operation.data?.kind === "prepare-review" &&
    operation.data.state === "failed";
  const [selected, setSelected] = useState<string[]>([]);
  const [manual, setManual] = useState(false);
  const [batchResult, setBatchResult] = useState<{
    confirmed: number;
    skipped: number;
  } | null>(null);
  const [batchReason, setBatchReason] = useState("");
  const command = useCommand(`rules:confirm:${resource.data?.id ?? bid.id}`);
  const rules = resource.data?.rules ?? [];
  const current = resource.data?.material_revision === bid.material_revision;
  const pending = rules.filter((rule) => rule.confirmation === "pending");
  const selectedPending = pending.filter((rule) => selected.includes(rule.id));
  function refresh() {
    void resource.reload();
    onChanged();
  }
  return (
    <div>
      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>规则核对</h2>
            <p className="muted">
              核对条款解释、条件和例外；普通浏览不要求先确认全部条款。
            </p>
          </div>
          {resource.data && <Badge>{pending.length} 项待核对</Badge>}
        </div>
        <ResourceState
          {...resource}
          error={notReady ? reviewStateError : resource.error}
          hasData={!!resource.data}
          onRetry={notReady ? onChanged : () => void resource.reload()}
        />
        {blocked && !reviewStateError && (
          <ResourceState
            {...operation}
            error={operationError}
            hasData={!!operation.data}
            onRetry={() => void operation.reload()}
          />
        )}
        {notReady &&
          !reviewStateError &&
          (!blocked || (!operationError && operation.data)) &&
          (failedExtraction ? (
            <div className="notice warning">
              <p>
                本次要求提取失败。可按本次冻结的原文逐条建立清单，整体覆盖仍为未知。
              </p>
              <button
                className="button secondary"
                disabled={
                  !supportsApi("POST", `/bids/${bid.id}/manual-rule-set`)
                }
                onClick={() => setManual(!manual)}
                aria-expanded={manual}
              >
                人工建立要求清单
              </button>
            </div>
          ) : (
            <div className="small-empty resource-empty">
              <p role="status">
                {needsMaterials
                  ? "尚未生成要求清单。请先在「项目资料」上传招标原件和受检正文。"
                  : waitingForService
                    ? "当前部署未启用单稿评审服务，尚未生成要求清单。可先在项目资料中核对招标原件。"
                    : request?.state === "preparing"
                      ? "正在准备本轮要求，清单生成后可在这里核对。"
                      : blocked
                        ? "本次准备未完成。请在「处理记录」查看具体原因。"
                        : "尚未生成要求清单。请在「项目资料」核对招标原件和受检正文，再开始评审。"}
              </p>
              {(needsMaterials || waitingForService) && onMaterials && (
                <button
                  type="button"
                  className="button secondary"
                  onClick={onMaterials}
                >
                  打开项目资料
                </button>
              )}
            </div>
          ))}
        {resource.data && (
          <div className="rules-intro">
            {rules.length > 0 &&
              rules.every((rule) => rule.origin_kind !== "model_extracted") && (
                <p className="notice warning">
                  本清单由人工逐条录入，整体覆盖未知；不代表模型提取成功或全部合规。
                </p>
              )}
            <p className="muted">
              规则包对应资料修订 {resource.data.material_revision} · 包内共{" "}
              {rules.length} 项。已识别清单不代表原文零漏提。
            </p>
            {!current && (
              <div className="notice warning">
                当前资料已变化，此包属于先前资料范围。请核对来源与影响后重新提取或评审。
              </div>
            )}
            {resource.data.coverage !== "complete" && (
              <div className="notice warning">
                {resource.data.coverage === "conflict"
                  ? "条款或来源存在冲突，需先核对。"
                  : "核心条款提取范围不完整，不能据此认定全稿已核对。"}
              </div>
            )}
            <button
              className="button secondary"
              disabled={
                !current ||
                !supportsApi("POST", `/bids/${bid.id}/rule-set-corrections`)
              }
              aria-expanded={manual}
              onClick={() => setManual(!manual)}
            >
              补充并确认条款
            </button>
            <p className="small-note">
              人工补入的核心要求保留来源身份，不会仅因模型重新提取未列出而消失。
            </p>
          </div>
        )}
      </section>
      {manual && (
        <ManualRuleForm
          bid={bid}
          ruleSet={resource.data ?? null}
          ruleSetETag={resource.etag}
          initialAvailable={failedExtraction}
          onSaved={refresh}
          onClose={() => setManual(false)}
        />
      )}
      {rules.length > 0 && (
        <div className="batch-rule-toolbar">
          <span>
            仅勾选本次明确核对的待处理条款，当前每次最多{ruleConfirmationLimit}
            项。
          </span>
          <label>
            所选条款的核对理由
            <input
              value={batchReason}
              maxLength={2000}
              onChange={(event) => setBatchReason(event.target.value)}
              placeholder="说明本次已核对的解释与依据"
            />
          </label>
          <button
            className="button secondary"
            disabled={
              !current ||
              !resource.etag ||
              command.busy ||
              selectedPending.length === 0 ||
              !batchReason.trim() ||
              !supportsApi("POST", `/bids/${bid.id}/rules/decisions`)
            }
            onClick={() => {
              if (!resource.data) return;
              const body: BatchRuleConfirmation = {
                base_rule_set_id: resource.data.id,
                rule_ids: selectedPending.map((rule) => rule.id),
                reason: batchReason.trim(),
              };
              void command
                .run<RuleSetView>(
                  `/bids/${bid.id}/rules/decisions`,
                  body,
                  resource.etag,
                )
                .then((result) => {
                  if (result) {
                    const confirmed = selectedPending.filter((rule) =>
                      result.data.rules.some(
                        (item) =>
                          item.id === rule.id &&
                          item.confirmation === "confirmed",
                      ),
                    ).length;
                    setBatchResult({
                      confirmed,
                      skipped: selectedPending.length - confirmed,
                    });
                    setSelected([]);
                    refresh();
                  }
                });
            }}
          >
            确认所选 {selectedPending.length} 项条款解释
          </button>
        </div>
      )}
      <ErrorNotice error={command.error} />
      {command.conflict && (
        <div className="notice warning">
          <span>
            规则包已变化，勾选内容保留。请刷新并重新核对，不自动套用旧确认。
          </span>
          <button className="button secondary" onClick={refresh}>
            刷新规则包
          </button>
        </div>
      )}
      {batchResult && (
        <div className="notice neutral" role="status">
          本次已按逐项结果记录，条款解释确认不代表正文满足。
          <p>
            所选项中 {batchResult.confirmed} 项已确认，{batchResult.skipped}{" "}
            项未覆盖原决定。以当前逐条状态为准。
          </p>
        </div>
      )}
      {resource.data && rules.length === 0 && (
        <div className="panel small-empty">
          当前规则包尚未列出规则。这不表示招标文件没有要求或不存在风险。
        </div>
      )}
      {rules.map((rule) => (
        <article className="panel rule-card" key={rule.id}>
          <div className="rule-card-heading">
            <label className="rule-selection">
              <input
                type="checkbox"
                checked={selected.includes(rule.id)}
                disabled={
                  !current ||
                  rule.confirmation !== "pending" ||
                  (!selected.includes(rule.id) &&
                    selected.length >= ruleConfirmationLimit)
                }
                onChange={(event) =>
                  setSelected((old) =>
                    event.target.checked
                      ? [...old, rule.id]
                      : old.filter((id) => id !== rule.id),
                  )
                }
                aria-label={`选择条款：${rule.statement}`}
              />
              <Badge
                tone={
                  rule.kind === "disqualification" || rule.kind === "mandatory"
                    ? "warning"
                    : ""
                }
              >
                {ruleKindNames[rule.kind]}
              </Badge>
            </label>
            <Badge>{confirmationNames[rule.confirmation]}</Badge>
          </div>
          <h3>{rule.statement}</h3>
          <div className="rule-qualifiers">
            <p>
              <strong>适用范围：</strong>
              {rule.scope.description}
            </p>
            <p>
              <strong>条件：</strong>
              {rule.conditions.length
                ? rule.conditions.join("；")
                : "未记录条件，请与原文核对"}
            </p>
            <p>
              <strong>例外：</strong>
              {rule.exceptions.length
                ? rule.exceptions.join("；")
                : "未记录例外，请与原文核对"}
            </p>
            {rule.maximum !== null && (
              <p>
                <strong>本条满分：</strong>
                {rule.maximum}
              </p>
            )}
          </div>
          {rule.origin_kind !== "model_extracted" && (
            <p className="manual-origin">
              人工补入来源保留
              {rule.provenance_status === "needs_revalidation"
                ? " · 来源效力或适用范围待重新核验"
                : rule.provenance_status === "superseded"
                  ? " · 已有据结束当前义务，历史保留"
                  : " · 当前来源有效"}
            </p>
          )}
          {rule.carryover && (
            <p className="small-note">
              沿用经等价核验的原决定，来源决定{" "}
              {rule.carryover.from_decision_id.slice(0, 8)}。
            </p>
          )}
          <EvidenceLinks ids={rule.evidence_ids} label="查看条款原文" />
          <DecisionForm
            kind="rules"
            id={rule.id}
            revision={rule.decision_revision}
            evidenceIds={rule.evidence_ids}
            onSaved={refresh}
          />
        </article>
      ))}
    </div>
  );
}
