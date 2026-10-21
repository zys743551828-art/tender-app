import { useEffect, useState } from "react";
import type { TemplateRequest, TemplateView } from "./contracts";
import { ErrorNotice } from "./components";
import {
  discardKnowledgeForm,
  knowledgeStorageKey,
  useKnowledgeInput,
} from "./knowledgeStorage";
import {
  PackageAuthoringInputDetails,
  PackageAuthoringInputPicker,
} from "./PackageAuthoringInput";
import {
  packageAuthoringScope,
  type VerifiedAuthoringInput,
} from "./packageAuthoringInputProtocol";
import {
  isExactPackageAuthoring,
  normalizePackageAuthoringRequest,
  samePackageAuthoringSource,
} from "./taskPackageAuthoringProtocol";
import { useTaskPackageCommand } from "./useTaskPackageCommand";
import { usePackageScopeGuard } from "./packageScopeGuard";
import { historicalSame } from "./historicalImportProtocol";
import type { TaskTemplateEditorProps } from "./TaskTemplateEditor";

export function PackageAuthoringTemplateEditor({
  bidId,
  memberId,
  template,
  etag,
  onSaved,
  onClose,
  onStateChange,
  initialConfiguration,
  formIdentity,
  external,
}: TaskTemplateEditorProps) {
  const identity = template?.id ?? "new";
  const formKey =
    knowledgeStorageKey(memberId, bidId) +
    `task-package-authoring-template:${formIdentity ?? identity}:`;
  const [initial] = useState<TemplateRequest>(() =>
    structuredClone(
      initialConfiguration ??
        template?.configuration ?? {
          name: "",
          task_kind: "chapter_suggestion",
          instructions: "",
          section_id: null,
          trigger: { mode: "manual", cron: null, timezone: "Asia/Shanghai" },
        },
    ),
  );
  const [input, setInput] = useKnowledgeInput<TemplateRequest>(
    formKey + "input",
    initial,
  );
  const [basis, setBasis] = useKnowledgeInput(formKey + "etag", etag ?? "");
  const [previous, setPrevious] = useKnowledgeInput<TemplateView | null>(
    formKey + "previous",
    template,
  );
  const [verified, setVerified] = useState<VerifiedAuthoringInput | null>(null);
  const [saved, setSaved] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [rebasing, setRebasing] = useState(false);
  const [adopted, setAdopted] = useState<{
    etag: string;
    prop: string | null;
  } | null>(null);
  const [sourceChanged, setSourceChanged] = useState(false);
  const command = useTaskPackageCommand({
    kind: "authoring_template",
    memberId,
    bidId,
    identity,
  });
  const selected = isExactPackageAuthoring(input)
    ? input.source_selection.input
    : null;
  const fixed = !!template || isExactPackageAuthoring(initial);
  const sourceMatches = !fixed || samePackageAuthoringSource(input, initial);
  const exactInput =
    !!verified &&
    selected?.authoring_input_id === verified.manifest.id &&
    selected.authoring_input_digest === verified.digest &&
    input.section_id === verified.manifest.selection.target_section.section_id;
  const pending = !!command.pending || command.blocked || !!external?.pending;
  const busy = command.busy || rebasing || !!external?.busy;
  const conflict = command.conflict || !!external?.conflict;
  const staleBasis =
    basis !== etag && !(adopted?.etag === basis && adopted.prop === etag);
  const dirty = !saved && !historicalSame(input, initial);
  usePackageScopeGuard(
    `package-authoring-template:${memberId}:${bidId}:${formIdentity ?? identity}`,
    { busy, pending, dirty },
  );
  useEffect(() => {
    onStateChange?.({ busy, pending, dirty });
  }, [onStateChange, busy, pending, dirty]);
  useEffect(
    () => () => onStateChange?.({ busy: false, pending: false, dirty: false }),
    [onStateChange],
  );
  let valid = false;
  try {
    normalizePackageAuthoringRequest(input);
    valid = true;
  } catch {
    /* Editable fields may be incomplete. */
  }
  const locked = busy || pending || saved;
  function select(value: VerifiedAuthoringInput) {
    if (fixed || locked) return;
    setVerified(null);
    setInput((old) => ({
      ...old,
      task_kind: "chapter_suggestion",
      section_id: value.manifest.selection.target_section.section_id,
      source_selection: {
        mode: "exact_package_authoring",
        input: {
          authoring_input_id: value.manifest.id,
          authoring_input_digest: value.digest,
        },
      },
      trigger: { mode: "manual", cron: null, timezone: "Asia/Shanghai" },
    }));
  }
  function accept(value: TemplateView | undefined) {
    if (!value) return;
    setSaved(true);
    discardKnowledgeForm(formKey);
    onSaved(value);
  }
  async function save() {
    if (
      locked ||
      conflict ||
      staleBasis ||
      sourceChanged ||
      !sourceMatches ||
      !exactInput ||
      !valid ||
      !basis
    )
      return;
    if (external) {
      accept(await external.submit(input));
      return;
    }
    const result = await command.run({
      path: template
        ? `/bids/${bidId}/task-definitions/${template.id}`
        : `/bids/${bidId}/task-definitions`,
      method: template ? "PUT" : "POST",
      body: input,
      etag: basis,
      expected: { kind: "authoring_template", request: input, previous },
    });
    accept(result?.data);
  }
  async function adoptBasis() {
    if (locked) return;
    setRebasing(true);
    setFailure(null);
    try {
      if (external) {
        const next = await external.rebase();
        setBasis(next);
        setAdopted({ etag: next, prop: etag });
        return;
      }
      const response = await command.adoptBasis();
      if (!response?.etag) return;
      if (template) {
        if (
          !("configuration" in response.data) ||
          !samePackageAuthoringSource(response.data.configuration, initial)
        ) {
          setSourceChanged(true);
          throw new Error(
            "当前模板已绑定其他输入。已保留原表单，请核对对应模板，不能把其他输入替入本表单。",
          );
        }
        setPrevious(response.data);
      }
      setSourceChanged(false);
      setBasis(response.etag);
      setAdopted({ etag: response.etag, prop: etag });
    } catch (error) {
      setFailure(error);
    } finally {
      setRebasing(false);
    }
  }
  return (
    <section
      className="panel task-editor exact-package-task-command"
      aria-label="固定整包编写模板编辑"
    >
      <div className="section-title">
        <h3>
          {external
            ? "完善固定整包编写草案"
            : template
              ? "保存固定整包编写模板新版本"
              : "新建固定整包编写模板"}
        </h3>
        <button type="button" className="text-button" onClick={onClose}>
          收起表单，保留输入
        </button>
      </div>
      <p>{packageAuthoringScope}</p>
      <p className="small-note">
        保存只记录模板；明确手动运行才可能调用模型并产生费用。
      </p>
      {!fixed && (
        <PackageAuthoringInputPicker
          key={`${memberId}:${bidId}`}
          bidId={bidId}
          disabled={locked}
          onSelect={select}
        />
      )}
      {selected && (
        <PackageAuthoringInputDetails
          key={`${memberId}:${bidId}:${selected.authoring_input_id}:${selected.authoring_input_digest}`}
          bidId={bidId}
          selection={selected}
          onVerified={setVerified}
        />
      )}
      {!sourceMatches && (
        <p className="notice error">
          表单来源与原模板不一致，原输入仍保留；请恢复对应模板后继续。
        </p>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <fieldset disabled={locked}>
          <label>
            模板名称
            <input
              required
              maxLength={200}
              aria-label="固定整包编写模板名称"
              value={typeof input.name === "string" ? input.name : ""}
              onChange={(e) =>
                setInput((old) => ({ ...old, name: e.target.value }))
              }
            />
          </label>
          <label>
            编写要求
            <textarea
              required
              maxLength={8000}
              rows={5}
              aria-label="固定整包编写要求"
              value={
                typeof input.instructions === "string" ? input.instructions : ""
              }
              onChange={(e) =>
                setInput((old) => ({ ...old, instructions: e.target.value }))
              }
            />
          </label>
          <p>任务类型：固定整包章节建议；触发方式：仅手动。</p>
          {(input.task_kind !== "chapter_suggestion" ||
            input.trigger?.mode !== "manual" ||
            input.trigger?.cron != null) && (
            <p className="notice warning">
              原草案尚未明确为手动章节编写。
              <button
                type="button"
                className="button secondary"
                onClick={() =>
                  setInput((old) => ({
                    ...old,
                    task_kind: "chapter_suggestion",
                    trigger: {
                      mode: "manual",
                      cron: null,
                      timezone: "Asia/Shanghai",
                    },
                  }))
                }
              >
                明确改为仅手动的固定整包章节编写
              </button>
            </p>
          )}
        </fieldset>
        <ErrorNotice error={failure ?? command.error ?? external?.error} />
        {(!valid || !exactInput || !sourceMatches || !basis) && (
          <p className="notice neutral">
            请明确选择并核对完整固定输入，填写名称和编写要求。目标章节取自该输入保存的正文快照。
          </p>
        )}
        <button
          className="button primary"
          disabled={
            locked ||
            conflict ||
            staleBasis ||
            sourceChanged ||
            !valid ||
            !exactInput ||
            !sourceMatches ||
            !basis
          }
        >
          {external
            ? "保存为固定整包编写模板，不运行"
            : "保存固定整包编写模板，不运行"}
        </button>
        {external?.saveDraftOnly && (
          <button
            type="button"
            className="button secondary"
            disabled={
              locked ||
              conflict ||
              staleBasis ||
              !valid ||
              !exactInput ||
              !sourceMatches
            }
            onClick={() => void external.saveDraftOnly?.(input)}
          >
            只保存可编辑草案
          </button>
        )}
      </form>
      {(conflict || staleBasis || !basis) && (
        <div className="notice warning">
          <p>服务器修订基准需要重新核对；原表单保留，不自动换成新修订重发。</p>
          <button
            type="button"
            className="button secondary"
            disabled={locked}
            onClick={() => void adoptBasis()}
          >
            读取并采用当前基准，保留编写要求
          </button>
        </div>
      )}
      {pending && (
        <p className="notice warning">
          上次保存尚未取得可信回执。保留完整原请求、原修订和原键，恢复前不能改变绑定输入。
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
          恢复原固定整包模板保存结果
        </button>
      )}
      {command.blocked && (
        <p className="notice error">
          原恢复记录无法核验，已暂停新写入；请保留原记录并核对服务器历史。
        </p>
      )}
      {saved && <p role="status">模板已保存；尚未启动编写。</p>}
    </section>
  );
}
