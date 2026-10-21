import { useEffect, useState } from "react";
import { ErrorNotice } from "./components";
import { ExactPackageTaskScope } from "./ExactPackageTaskScope";
import { ExactPackageTaskTriggerFields } from "./ExactPackageTaskTriggerFields";
import { historicalSame } from "./historicalImportProtocol";
import { knowledgeStorageKey, useKnowledgeInput } from "./knowledgeStorage";
import {
  packageTaskTriggerCapability,
  taskPackageTriggerMissing,
} from "./packageTaskTemplateSelection";
import { usePackageScopeGuard } from "./packageScopeGuard";
import { normalizeTaskPackageRequest } from "./taskPackageProtocol";
import {
  exactPackageTaskScope,
  isExactPackageTask,
  newTaskConfiguration,
  sameTaskPackageSource,
} from "./taskState";
import type { TaskKindPage, TemplateRequest } from "./taskTriggerContracts";
import type { TaskTemplateEditorProps } from "./TaskTemplateEditor";
import { useResource } from "./useResource";

/** Private draft commands retain their original two-step draft/save receipt, with exact sources kept read-only. */
export function ExactPackageTaskDraftEditor({
  bidId,
  memberId,
  formIdentity,
  initialConfiguration,
  etag,
  external,
  onSaved,
  onClose,
  onStateChange,
}: TaskTemplateEditorProps) {
  const key =
    knowledgeStorageKey(memberId, bidId) + `task-template:${formIdentity}:`;
  const [initial] = useState(() =>
    structuredClone(initialConfiguration ?? newTaskConfiguration()),
  );
  const [input, setInput] = useKnowledgeInput<TemplateRequest>(
    key + "input",
    initial,
  );
  const [basis, setBasis] = useKnowledgeInput(key + "etag", etag ?? "");
  const [saved, setSaved] = useState(false);
  const [working, setWorking] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const kinds = useResource<TaskKindPage>("/task-kinds");
  let capability = null;
  let capabilityError: unknown = null;
  try {
    capability = kinds.data ? packageTaskTriggerCapability(kinds.data) : null;
  } catch (error) {
    capabilityError = error;
  }
  const busy = working || !!external?.busy;
  const pending = !!external?.pending;
  const dirty = !saved && !historicalSame(input, initial);
  usePackageScopeGuard(`task-draft-form:${memberId}:${bidId}:${formIdentity}`, {
    busy,
    pending,
    dirty,
  });
  useEffect(() => {
    onStateChange?.({ busy, pending, dirty });
  }, [onStateChange, busy, pending, dirty]);
  useEffect(
    () => () => onStateChange?.({ busy: false, pending: false, dirty: false }),
    [onStateChange],
  );
  const missing = [
    ...(!sameTaskPackageSource(input, initial) ? ["原精确整包来源"] : []),
    ...(input.task_kind !== "denial_check" || input.section_id != null
      ? ["明确选择整包否决核对"]
      : []),
    ...(!input.name?.trim() ? ["模板名称"] : []),
    ...(!input.instructions?.trim() ? ["任务说明"] : []),
    ...(!basis ? ["草案原修订基准"] : []),
    ...(taskPackageTriggerMissing(input, capability)
      ? [taskPackageTriggerMissing(input, capability)]
      : []),
  ];
  const locked = busy || pending || saved;
  async function submit(draftOnly: boolean) {
    if (!external || locked || external.conflict || missing.length) return;
    setWorking(true);
    setFailure(null);
    try {
      const request = normalizeTaskPackageRequest(input);
      if (draftOnly) await external.saveDraftOnly?.(request);
      else {
        const value = await external.submit(request);
        if (value) {
          setSaved(true);
          onSaved(value);
        }
      }
    } catch (error) {
      setFailure(error);
    } finally {
      setWorking(false);
    }
  }
  return (
    <section className="panel task-editor exact-package-task-command">
      <div className="section-title">
        <h3>核对并保存整包任务草案</h3>
        <button type="button" className="text-button" onClick={onClose}>
          收起表单，保留输入
        </button>
      </div>
      <p className="notice neutral">{exactPackageTaskScope}</p>
      {isExactPackageTask(initial) && (
        <ExactPackageTaskScope
          bidId={bidId}
          selection={initial.source_selection.input}
        />
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit(false);
        }}
      >
        <fieldset disabled={locked}>
          <label>
            模板名称
            <input
              aria-label="模板名称"
              required
              maxLength={200}
              value={input.name}
              onChange={(event) =>
                setInput({ ...input, name: event.target.value })
              }
            />
          </label>
          <label>
            任务类型
            <select
              aria-label="任务类型"
              value={input.task_kind === "denial_check" ? "denial_check" : ""}
              onChange={(event) => {
                if (event.target.value === "denial_check")
                  setInput({
                    ...input,
                    task_kind: "denial_check",
                    section_id: null,
                  });
              }}
            >
              <option value="">明确选择任务类型</option>
              <option value="denial_check">整包否决核对</option>
            </select>
          </label>
          <label>
            任务说明
            <textarea
              aria-label="任务说明"
              required
              maxLength={8000}
              rows={4}
              value={input.instructions}
              onChange={(event) =>
                setInput({ ...input, instructions: event.target.value })
              }
            />
          </label>
          <ExactPackageTaskTriggerFields
            input={input}
            change={setInput}
            capability={capability}
          />
        </fieldset>
        <ErrorNotice error={failure ?? external?.error ?? capabilityError} />
        {missing.length > 0 && (
          <p role="status" className="small-note">
            仍需填写或核对：{missing.join("、")}。
          </p>
        )}
        {pending && (
          <p className="notice warning">
            原草案或模板保存请求尚未确认，请在下方恢复同一次请求；固定输入继续保留。
          </p>
        )}
        {external?.conflict && (
          <p className="notice warning">
            草案修订已变化，请明确核对当前草案；不会自动替换原输入。
          </p>
        )}
        <div className="review-shortcuts">
          <button
            className="button primary"
            disabled={locked || !!external?.conflict || !!missing.length}
          >
            保存任务模板，不运行
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={locked || !!external?.conflict || !!missing.length}
            onClick={() => void submit(true)}
          >
            仅保存草案修改
          </button>
          <button
            type="button"
            className="text-button"
            disabled={locked}
            onClick={async () => {
              if (!external) return;
              setWorking(true);
              try {
                setBasis(await external.rebase());
              } catch (error) {
                setFailure(error);
              } finally {
                setWorking(false);
              }
            }}
          >
            核对当前草案修订，保留输入
          </button>
          <button
            type="button"
            className="text-button"
            disabled={locked}
            onClick={() => setInput(structuredClone(initial))}
          >
            放弃未发送的文字修改
          </button>
        </div>
      </form>
      {saved && <p className="notice success">模板已保存，未运行。</p>}
    </section>
  );
}
