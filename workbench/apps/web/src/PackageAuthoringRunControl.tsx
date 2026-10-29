import { useEffect, useState } from "react";
import { ApiError } from "./api";
import type { RunView, TaskKindPage, TemplateView } from "./contracts";
import { ErrorNotice } from "./components";
import { PackageAuthoringInputDetails } from "./PackageAuthoringInput";
import {
  packageAuthoringCapability,
  type VerifiedAuthoringInput,
} from "./packageAuthoringInputProtocol";
import {
  isExactPackageAuthoring,
  validatePackageAuthoringTemplate,
  type PackageAuthoringTemplateView,
} from "./taskPackageAuthoringProtocol";
import type { PackageNavigationState } from "./packageNavigation";
import { usePackageScopeGuard } from "./packageScopeGuard";
import { useTaskPackageCommand } from "./useTaskPackageCommand";
import { taskRunNames } from "./taskState";
import {
  exactKeys,
  executionId,
  recordObject,
} from "./executionInputValidation";

export function PackageAuthoringRunControl({
  bidId,
  memberId,
  id,
  template,
  etag,
  kinds,
  disabled,
  onRun,
  onChanged,
  onStateChange,
}: {
  bidId: string;
  memberId: string;
  id: string;
  template?: TemplateView;
  etag: string | null;
  kinds?: TaskKindPage;
  disabled: boolean;
  onRun: (id: string) => void;
  onChanged: () => void;
  onStateChange?: (state: PackageNavigationState) => void;
}) {
  const command = useTaskPackageCommand({
    kind: "authoring_run",
    memberId,
    bidId,
    identity: id,
  });
  const [checked, setChecked] = useState<{
    source: TemplateView;
    value: PackageAuthoringTemplateView;
  } | null>(null);
  const [readError, setReadError] = useState<unknown>(null);
  const [input, setInput] = useState<VerifiedAuthoringInput | null>(null);
  const [accepted, setAccepted] = useState<RunView | null>(null);
  const [adopting, setAdopting] = useState(false);
  const [adoptedEtag, setAdoptedEtag] = useState<string | null>(null);
  const exact = !!template && isExactPackageAuthoring(template.configuration);
  useEffect(() => {
    let active = true;
    setReadError(null);
    if (template && exact)
      void validatePackageAuthoringTemplate(template, etag, bidId, id)
        .then((value) => {
          if (active) setChecked({ source: template, value });
        })
        .catch((error) => {
          if (active) setReadError(error);
        });
    return () => {
      active = false;
    };
  }, [template, exact, etag, bidId, id]);
  const current =
    checked &&
    checked.source === template &&
    checked.value.id === id &&
    checked.value.bid_id === bidId
      ? checked.value
      : null;
  const busy = command.busy || adopting,
    pending = !!command.pending || command.blocked;
  usePackageScopeGuard(`package-authoring-run:${memberId}:${bidId}:${id}`, {
    busy,
    pending,
  });
  useEffect(() => {
    onStateChange?.({ busy, pending, dirty: false });
  }, [onStateChange, busy, pending]);
  useEffect(
    () => () => onStateChange?.({ busy: false, pending: false, dirty: false }),
    [onStateChange],
  );
  let capability = null,
    capabilityError: unknown = null;
  try {
    capability = kinds ? packageAuthoringCapability(kinds) : null;
  } catch (error) {
    capabilityError = error;
  }
  const boundInput =
    !!current &&
    !!input &&
    input.manifest.bid_id === bidId &&
    input.manifest.id ===
      current.configuration.source_selection.input.authoring_input_id &&
    input.digest ===
      current.configuration.source_selection.input.authoring_input_digest &&
    input.manifest.selection.target_section.section_id ===
      current.configuration.section_id;
  const feeUnknown =
    command.error instanceof ApiError &&
    [
      "MODEL_CALL_REQUIRES_RECONCILIATION",
      "TASK_RECONCILIATION_REQUIRED",
    ].includes(command.error.code);
  const priorRequired =
    command.error instanceof ApiError &&
    command.error.code === "AUTHORING_PACKAGE_ORIGINAL_JOB_REQUIRED";
  const prior =
    priorRequired &&
    command.error instanceof ApiError &&
    recordObject(command.error.details) &&
    exactKeys(command.error.details, [
      "bid_id",
      "job_id",
      "task_run_id",
      "new_attempt_authorized",
    ]) &&
    command.error.details.bid_id === bidId &&
    executionId(command.error.details.job_id) &&
    executionId(command.error.details.task_run_id) &&
    command.error.details.new_attempt_authorized === false
      ? command.error.details.task_run_id
      : null;
  const available =
    exact &&
    !!current &&
    boundInput &&
    !readError &&
    !!capability?.available &&
    !current.paused &&
    !disabled &&
    !feeUnknown &&
    !priorRequired &&
    (adoptedEtag === null || adoptedEtag === etag);
  function accept(value: RunView | undefined) {
    if (value) {
      setAccepted(value);
      onRun(value.id);
      onChanged();
    }
  }
  async function run() {
    if (!available || busy || pending || command.conflict || !current || !etag)
      return;
    accept(
      (
        await command.run({
          path: `/bids/${bidId}/task-definitions/${id}/runs`,
          method: "POST",
          body: { rerun: false },
          etag,
          expected: { kind: "authoring_run", template: current },
        })
      )?.data,
    );
  }
  async function rebase() {
    if (busy || pending) return;
    setAdopting(true);
    try {
      const value = await command.adoptBasis();
      if (value?.etag) {
        setAdoptedEtag(value.etag);
        onChanged();
      }
    } finally {
      setAdopting(false);
    }
  }
  if (!exact && !pending && !command.error) return null;
  return (
    <section
      className="exact-package-task-command"
      aria-label="固定整包编写手动运行"
    >
      {current && (
        <PackageAuthoringInputDetails
          key={`${memberId}:${bidId}:${current.configuration.source_selection.input.authoring_input_id}:${current.configuration.source_selection.input.authoring_input_digest}`}
          bidId={bidId}
          selection={current.configuration.source_selection.input}
          onVerified={setInput}
        />
      )}
      <p className="notice neutral">
        手动运行会使用模板绑定的完整固定输入，可能调用模型并产生费用；随后核对已发布候选。运行不会自动采纳正文，也不会构建交付包。
      </p>
      {!capability?.available && (
        <p className="notice warning">
          固定整包编写当前不可运行
          {capability?.reason
            ? `（${capability.reason}）`
            : "：尚未读到服务能力"}
          。保存的模板与输入仍可读取。
        </p>
      )}
      {feeUnknown && (
        <p className="notice warning">
          原调用费用待核对；不能用新模板或新运行绕过账本。
        </p>
      )}
      {priorRequired && (
        <p className="notice warning">
          相同编写内容已有原任务，本次没有新建调用。
          {prior && (
            <a href={`/bids/${bidId}/tasks?run=${prior}`}>
              打开对应的原编写任务
            </a>
          )}
        </p>
      )}
      {adoptedEtag !== null && adoptedEtag !== etag && (
        <p role="status">正在读取已采用的服务器模板基准…</p>
      )}
      <ErrorNotice error={command.error ?? readError ?? capabilityError} />
      {exact && (
        <button
          type="button"
          className="button primary"
          disabled={!available || busy || pending || command.conflict}
          onClick={() => void run()}
        >
          手动生成固定整包章节候选
        </button>
      )}
      {command.conflict && (
        <div className="notice warning">
          <p>模板已变更，原请求没有自动改用新修订重发。</p>
          <button
            type="button"
            className="button secondary"
            disabled={busy || pending}
            onClick={() => void rebase()}
          >
            读取并采用当前模板，再明确运行
          </button>
        </div>
      )}
      {pending && (
        <p className="notice warning">
          上次运行尚未取得可信受理回执。恢复使用原模板、原请求和原键，当前模板变化不会改写它。
        </p>
      )}
      {command.pending && !command.busy && (
        <button
          type="button"
          className="button secondary"
          onClick={() =>
            void command.retry().then((value) => accept(value?.data))
          }
        >
          恢复原固定整包编写受理结果
        </button>
      )}
      {command.blocked && (
        <p className="notice error">
          本地恢复记录无法核验，保留记录并暂停新运行。
        </p>
      )}
      {accepted && (
        <p role="status">
          已核验原受理回执：{taskRunNames[accepted.state]}
          。请打开运行记录读取当前候选与发布状态。
        </p>
      )}
    </section>
  );
}
