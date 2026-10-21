import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Bid, AssistantSourcePage } from "./contracts";
import type {
  TaskDraftView,
  TaskDraftPage,
  TaskDraftRequest,
  TemplateRequest,
  TemplateView,
  TaskKindPage,
} from "./taskTriggerContracts";
import { ErrorNotice } from "./components";
import { knowledgeStorageKey, useKnowledgeInput } from "./knowledgeStorage";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useTaskPage } from "./useTaskPage";
import { useRecordedCommand } from "./useRecordedCommand";
import { TaskTemplateEditor } from "./TaskTemplateEditor";
import { TaskTemplateCard } from "./TaskTemplateCard";
import {
  isExactPackageTask,
  newTaskConfiguration,
  sameTaskPackageSource,
} from "./taskState";
import {
  normalizeTaskPackageRequest,
  validateTaskPackageTemplate,
} from "./taskPackageProtocol";
import { historicalSame } from "./historicalImportProtocol";
import { jsonDigest } from "./editorSchema";
import { PackageAuthoringInputDetails } from "./PackageAuthoringInput";
import { PackageAuthoringInputChooser } from "./PackageAuthoringInputChooser";
import type { VerifiedAuthoringInput } from "./packageAuthoringInputProtocol";
import {
  isExactPackageAuthoring,
  normalizePackageAuthoringRequest,
  samePackageAuthoringSource,
  validatePackageAuthoringTemplate,
} from "./taskPackageAuthoringProtocol";

const isFixedTask = (value: TemplateRequest) =>
  isExactPackageTask(value) || isExactPackageAuthoring(value);
const normalizeFixedTask = (value: TemplateRequest) =>
  isExactPackageAuthoring(value)
    ? normalizePackageAuthoringRequest(value)
    : normalizeTaskPackageRequest(value);
const sameFixedTaskSource = (a: TemplateRequest, b: TemplateRequest) =>
  isExactPackageAuthoring(a)
    ? samePackageAuthoringSource(a, b)
    : sameTaskPackageSource(a, b);

export function TaskDraftPanel({
  bidId,
  memberId,
  bidEtag,
  onSaved,
}: {
  bidId: string;
  memberId: string;
  bidEtag: string | null;
  onSaved: () => void;
}) {
  const key = knowledgeStorageKey(memberId, bidId) + "task-draft-request:";
  const [text, setText] = useKnowledgeInput(key + "text", "");
  const [sectionId, setSectionId] = useKnowledgeInput(key + "section", "");
  const [sourceMode, setSourceMode] = useKnowledgeInput<
    "versions" | "package-authoring"
  >(key + "source-mode", "versions");
  const [selectedInput, setSelectedInput] = useKnowledgeInput<{
    authoring_input_id: string;
    authoring_input_digest: string;
    section_id: string;
  } | null>(key + "authoring-input", null);
  const [verifiedInput, setVerifiedInput] =
    useState<VerifiedAuthoringInput | null>(null);
  const [basis, setBasis] = useKnowledgeInput(key + "etag", bidEtag ?? "");
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(() =>
    new URLSearchParams(window.location.search).get("task_draft"),
  );
  const [failure, setFailure] = useState<unknown>(null);
  const createExpected = useRef<{
    body: TaskDraftRequest;
    etag: string;
  } | null>(null);
  const command = useRecordedCommand(
    `task-draft:${memberId}:${bidId}:create`,
    async (response) => {
      const original = createExpected.current;
      if (original?.body.source_selection?.mode === "exact_package_authoring") {
        const item = response.data as TaskDraftView,
          p = item.interpretation;
        if (
          !item.id ||
          item.bid_id !== bidId ||
          item.created_by !== memberId ||
          item.revision !== 1 ||
          response.etag !== `"task-draft:${item.id}:1"` ||
          !p ||
          p.raw_request !== original.body.request ||
          p.section_id !== original.body.section_id ||
          !historicalSame(p.source_selection, original.body.source_selection) ||
          p.template_saved !== false ||
          p.run_created !== false ||
          p.formal_decisions_allowed !== false ||
          item.saved_template_id !== null ||
          item.configuration_digest !== (await jsonDigest(p))
        )
          throw new Error(
            "固定整包编写草案的回执与原请求不一致，保留原请求继续恢复。",
          );
      }
    },
  );
  if (command.pending)
    createExpected.current = {
      body: command.pending.body as TaskDraftRequest,
      etag: command.pending.etag,
    };
  const packageInputReady =
    !!selectedInput &&
    !!verifiedInput &&
    selectedInput.authoring_input_id === verifiedInput.manifest.id &&
    selectedInput.authoring_input_digest === verifiedInput.digest &&
    selectedInput.section_id ===
      verifiedInput.manifest.selection.target_section.section_id;
  const drafts = useTaskPage<TaskDraftPage>(
    `/bids/${bidId}/task-definition-drafts?limit=20`,
    0,
    (page) => (page.has_more ? page.next_cursor : null),
  );
  const sections = useResource<AssistantSourcePage>(
    open && sourceMode === "versions"
      ? `/assistant/sources?kind=section&bid_id=${bidId}`
      : null,
  );
  const kinds = useResource<TaskKindPage>("/task-kinds");
  useEffect(() => {
    const sync = () =>
      setSelected(
        new URLSearchParams(window.location.search).get("task_draft"),
      );
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  function select(id: string) {
    const query = new URLSearchParams(window.location.search);
    query.set("task_draft", id);
    window.history.pushState({}, "", `${window.location.pathname}?${query}`);
    setSelected(id);
  }
  function accept(value: TaskDraftView | undefined) {
    if (!value) return;
    if (value.bid_id !== bidId || value.created_by !== memberId) {
      setFailure(new Error("草案成员或项目身份不一致，未采用。"));
      return;
    }
    select(value.id);
    void drafts.reload();
  }
  async function create() {
    if (
      !text.trim() ||
      !basis ||
      (sourceMode === "package-authoring" && !packageInputReady)
    )
      return;
    const body: TaskDraftRequest = {
      request: text.trim(),
      section_id:
        sourceMode === "package-authoring"
          ? selectedInput!.section_id
          : sectionId || null,
      source_selection:
        sourceMode === "package-authoring"
          ? {
              mode: "exact_package_authoring",
              input: {
                authoring_input_id: selectedInput!.authoring_input_id,
                authoring_input_digest: selectedInput!.authoring_input_digest,
              },
            }
          : { mode: "current_project", version_ids: [] },
    };
    createExpected.current = { body, etag: basis };
    const result = await command.run<TaskDraftView>(
      `/bids/${bidId}/task-definition-drafts`,
      body,
      basis,
    );
    accept(result?.data);
  }
  return (
    <section className="task-draft-entry">
      <button
        className="text-button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        用自然语言拟定任务草案／恢复已有草案
      </button>
      {open && (
        <>
          <p className="small-note">
            当前为限定中文解释器，不代表通用自然语言理解已验收。生成的是你的私有可编辑草案，不保存模板、不建立计划、不请求模型或收费运行。
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void create();
            }}
          >
            <label>
              草案来源
              <select
                aria-label="任务草案来源"
                value={sourceMode}
                disabled={command.busy || !!command.pending}
                onChange={(event) =>
                  setSourceMode(
                    event.target.value as "versions" | "package-authoring",
                  )
                }
              >
                <option value="versions">项目来源与章节</option>
                <option value="package-authoring">
                  明确保存的固定整包编写输入
                </option>
              </select>
            </label>
            {sourceMode === "package-authoring" && (
              <>
                <PackageAuthoringInputChooser
                  key={`${memberId}:${bidId}`}
                  bidId={bidId}
                  memberId={memberId}
                  disabled={command.busy || !!command.pending}
                  onSelect={(input) => {
                    setVerifiedInput(null);
                    setSelectedInput({
                      authoring_input_id: input.manifest.id,
                      authoring_input_digest: input.digest,
                      section_id:
                        input.manifest.selection.target_section.section_id,
                    });
                  }}
                />
                {selectedInput && (
                  <PackageAuthoringInputDetails
                    key={`${memberId}:${bidId}:${selectedInput.authoring_input_id}:${selectedInput.authoring_input_digest}`}
                    bidId={bidId}
                    selection={{
                      authoring_input_id: selectedInput.authoring_input_id,
                      authoring_input_digest:
                        selectedInput.authoring_input_digest,
                    }}
                    onVerified={setVerifiedInput}
                  />
                )}
                <p className="small-note">
                  只解释你明确选择的固定输入；目标章节来自其正文快照。自动或不明确的要求会保留为待明确草案。
                </p>
              </>
            )}
            <label>
              想反复完成什么工作
              <textarea
                required
                maxLength={8000}
                aria-label="想反复完成什么工作"
                rows={3}
                value={text}
                disabled={command.busy || !!command.pending}
                onChange={(event) => {
                  if (!basis && bidEtag) setBasis(bidEtag);
                  setText(event.target.value);
                }}
              />
            </label>
            {sourceMode === "versions" && (
              <label>
                如需章节建议，明确选择目标章节
                <select
                  aria-label="如需章节建议，明确选择目标章节"
                  value={sectionId}
                  disabled={command.busy || !!command.pending}
                  onChange={(event) => setSectionId(event.target.value)}
                >
                  <option value="">尚未指定章节</option>
                  {sections.data?.items
                    .filter(
                      (item) =>
                        item.available &&
                        item.bid_id === bidId &&
                        item.reference?.kind === "section",
                    )
                    .map((item) => (
                      <option
                        value={item.reference!.id}
                        key={item.reference!.id}
                      >
                        {item.title}
                      </option>
                    ))}
                </select>
              </label>
            )}
            <ResourceState
              {...sections}
              hasData={!!sections.data}
              onRetry={() => void sections.reload()}
            />
            <ErrorNotice error={failure ?? command.error} />
            <button
              className="button secondary"
              disabled={
                !text.trim() ||
                !basis ||
                (sourceMode === "package-authoring" && !packageInputReady) ||
                command.busy ||
                !!command.pending ||
                !!command.conflict
              }
            >
              生成可编辑草案，不保存模板
            </button>
            {command.conflict && (
              <button
                type="button"
                className="text-button"
                onClick={async () => {
                  try {
                    const value = await api<Bid>(`/bids/${bidId}`);
                    if (value.data.id !== bidId || !value.etag)
                      throw new Error("项目身份不一致");
                    setBasis(value.etag);
                    command.clearError();
                  } catch (error) {
                    setFailure(error);
                  }
                }}
              >
                核对当前项目后保留原请求继续
              </button>
            )}
          </form>
          {command.pending && !command.busy && (
            <button
              className="button secondary"
              onClick={() =>
                void command
                  .retry<TaskDraftView>()
                  .then((result) => accept(result?.data))
              }
            >
              恢复原草案受理结果
            </button>
          )}
          <ResourceState
            {...drafts}
            hasData={!!drafts.data}
            onRetry={() => void drafts.reload()}
          />
          <ErrorNotice error={drafts.moreError} />
          {drafts.items
            .filter(
              (item) => item.bid_id === bidId && item.created_by === memberId,
            )
            .map((item) => (
              <button
                className="history-row"
                key={item.id}
                onClick={() => select(item.id)}
              >
                {item.interpretation.name} · 草案修订{item.revision} ·{" "}
                {item.saved_template_id ? "已保存模板" : "可继续编辑"}
              </button>
            ))}
          {drafts.hasMore && (
            <button
              className="text-button"
              disabled={drafts.moreBusy}
              onClick={() => void drafts.more()}
            >
              加载更多我的草案
            </button>
          )}
        </>
      )}
      {selected && (
        <TaskDraftDetail
          key={selected}
          bidId={bidId}
          memberId={memberId}
          id={selected}
          kinds={kinds.data}
          onSaved={() => {
            void drafts.reload();
            onSaved();
          }}
        />
      )}
    </section>
  );
}
function TaskDraftDetail({
  bidId,
  memberId,
  id,
  kinds,
  onSaved,
}: {
  bidId: string;
  memberId: string;
  id: string;
  kinds: TaskKindPage | undefined;
  onSaved: () => void;
}) {
  const path = `/bids/${bidId}/task-definition-drafts/${id}`;
  const resource = useResource<TaskDraftView>(path);
  const draft =
    resource.data?.id === id &&
    resource.data.bid_id === bidId &&
    resource.data.created_by === memberId
      ? resource.data
      : undefined;
  const editExpected = useRef<{ input: TemplateRequest; etag: string } | null>(
    null,
  );
  const edit = useRecordedCommand(
    `task-draft:${memberId}:${bidId}:${id}:edit`,
    async (reply) => {
      const original = editExpected.current;
      if (original && isFixedTask(original.input)) {
        const item = reply.data as TaskDraftView;
        const revision = original.etag.match(
          new RegExp(`^"task-draft:${id}:(\\d+)"$`),
        );
        if (
          !revision ||
          item.id !== id ||
          item.bid_id !== bidId ||
          item.created_by !== memberId ||
          item.revision !== Number(revision[1]) + 1 ||
          reply.etag !== `"task-draft:${id}:${item.revision}"` ||
          !historicalSame(
            normalizeFixedTask(draftConfiguration(item)),
            normalizeFixedTask(original.input),
          ) ||
          item.configuration_digest !== (await jsonDigest(item.interpretation))
        )
          throw new Error(
            "整包草案更新回执与原请求不一致，保留同一次更新请求。",
          );
      }
    },
  );
  if (edit.pending)
    editExpected.current = {
      input: edit.pending.body as TemplateRequest,
      etag: edit.pending.etag,
    };
  const [failure, setFailure] = useState<unknown>(null);
  const [ack, setAck] = useKnowledgeInput<{
    etag: string;
    configuration?: TemplateRequest;
  } | null>(knowledgeStorageKey(memberId, id) + "task-draft-save-ack", null);
  const ackRef = useRef(ack);
  ackRef.current = ack;
  const save = useRecordedCommand(
    `task-draft:${memberId}:${bidId}:${id}:save`,
    async (result) => {
      const original = ackRef.current?.configuration;
      if (original && isFixedTask(original)) {
        const validateTemplate = isExactPackageAuthoring(original)
          ? validatePackageAuthoringTemplate
          : validateTaskPackageTemplate;
        const item = await validateTemplate(result.data, result.etag, bidId);
        if (
          item.revision !== 1 ||
          item.paused ||
          !historicalSame(item.configuration, normalizeFixedTask(original))
        )
          throw new Error("原草案保存的整包输入或模板回执不一致，保留原请求。");
      }
    },
  );
  const [intent, setIntent] = useKnowledgeInput<"draft" | "template">(
    knowledgeStorageKey(memberId, id) + "task-draft-intent",
    "draft",
  );
  async function saveAck(
    value: { data: TaskDraftView; etag: string | null } | null,
    expected?: TemplateRequest,
  ) {
    if (!value) return;
    const current = value.data;
    if (
      current.id !== id ||
      current.bid_id !== bidId ||
      current.created_by !== memberId ||
      !value.etag
    )
      throw new Error("草案确认身份或修订不一致。");
    if (
      current.interpretation.unresolved.length ||
      !current.interpretation.ready_for_template_form
    )
      throw new Error("仍有待明确项；输入可继续编辑，未保存模板。");
    const configuration = draftConfiguration(current);
    if (isFixedTask(configuration)) {
      if (
        !expected ||
        !historicalSame(
          normalizeFixedTask(expected),
          normalizeFixedTask(configuration),
        ) ||
        current.configuration_digest !==
          (await jsonDigest(current.interpretation))
      )
        throw new Error("原草案更新回执与明确整包输入不一致，未继续保存模板。");
    }
    const accepted = { etag: value.etag, configuration };
    setAck(accepted);
    ackRef.current = accepted;
    const result = await save.run<TemplateView>(`${path}/save`, {}, value.etag);
    if (result?.data.bid_id === bidId) {
      void resource.reload();
      return result.data;
    }
    void resource.reload();
  }
  async function submit(input: TemplateRequest) {
    setIntent("template");
    setFailure(null);
    try {
      editExpected.current = { input, etag: ack?.etag ?? resource.etag ?? "" };
      const result = await edit.run<TaskDraftView>(
        path,
        input,
        ack?.etag ?? resource.etag ?? "",
        "PUT",
      );
      return await saveAck(result, input);
    } catch (error) {
      setFailure(error);
    }
  }
  async function saveDraftOnly(input: TemplateRequest) {
    setIntent("draft");
    setFailure(null);
    try {
      editExpected.current = { input, etag: ack?.etag ?? resource.etag ?? "" };
      const value = await edit.run<TaskDraftView>(
        path,
        input,
        ack?.etag ?? resource.etag ?? "",
        "PUT",
      );
      if (value) {
        if (
          value.data.id !== id ||
          value.data.created_by !== memberId ||
          !value.etag
        )
          throw new Error("草案保存身份不一致。");
        if (
          isFixedTask(input) &&
          (!historicalSame(
            normalizeFixedTask(draftConfiguration(value.data)),
            normalizeFixedTask(input),
          ) ||
            value.data.configuration_digest !==
              (await jsonDigest(value.data.interpretation)))
        )
          throw new Error("原草案的整包输入回执不一致，输入保留。");
        setAck({ etag: value.etag });
        void resource.reload();
      }
    } catch (error) {
      setFailure(error);
    }
  }
  async function rebase() {
    const current = await api<TaskDraftView>(path);
    if (
      current.data.id !== id ||
      current.data.created_by !== memberId ||
      !current.etag
    )
      throw new Error("草案基准身份不一致。");
    if (
      draft &&
      isFixedTask(draftConfiguration(draft)) &&
      !sameFixedTaskSource(
        draftConfiguration(draft),
        draftConfiguration(current.data),
      )
    )
      throw new Error(
        "当前草案的原输入已改变，保留本地输入，不自动采用新来源。",
      );
    setAck({ etag: current.etag });
    edit.clearError();
    save.clearError();
    void resource.reload();
    return current.etag;
  }
  const proposal = draft?.interpretation;
  const initial: TemplateRequest = draft
    ? draftConfiguration(draft)
    : newTaskConfiguration();
  return (
    <section className="task-draft-detail">
      <ResourceState
        {...resource}
        hasData={!!draft}
        onRetry={() => void resource.reload()}
      />
      {resource.data && !draft && (
        <p className="notice error">草案身份不一致，未读取其他成员的草案。</p>
      )}
      {draft && proposal && (
        <>
          <h3>我的可编辑任务草案 · 修订{draft.revision}</h3>
          <p className="small-note">
            创建{new Date(draft.created_at).toLocaleString("zh-CN")}，最近保存
            {new Date(draft.updated_at).toLocaleString("zh-CN")}
            。仅草案持久保存不等于模板或运行。
          </p>
          <details className="coverage-details">
            <summary>原始请求与解释范围</summary>
            <p className="preserve-text">{proposal.raw_request}</p>
            <p>目标：{proposal.target_description}</p>
            <p>输出：{proposal.output_description}</p>
          </details>
          {proposal.unresolved.length > 0 && (
            <div className="notice warning">
              <p>仍需明确，可直接在下方修改，不锁死编辑：</p>
              <ul>
                {proposal.unresolved.map((item, index) => (
                  <li key={index}>
                    {item.field}：{item.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {draft.saved_template_id ? (
            <>
              <p className="notice success">
                此草案已一次保存为以下模板；继续修改请建立该模板的新版本，未另建重复模板。
              </p>
              <TaskTemplateCard
                bidId={bidId}
                memberId={memberId}
                id={draft.saved_template_id}
                kinds={kinds}
                onChanged={onSaved}
                onRun={(run) => {
                  window.location.href = `/bids/${bidId}/tasks?run=${encodeURIComponent(run)}`;
                }}
              />
            </>
          ) : (
            <TaskTemplateEditor
              key={id}
              formIdentity={`draft:${id}`}
              bidId={bidId}
              memberId={memberId}
              template={null}
              etag={resource.etag}
              initialConfiguration={initial}
              requireKindSelection={proposal.task_kind === null}
              external={{
                busy: edit.busy || save.busy,
                pending: !!edit.pending || !!save.pending,
                error: failure ?? edit.error ?? save.error,
                conflict: !!edit.conflict || !!save.conflict,
                submit,
                saveDraftOnly,
                rebase,
              }}
              onSaved={() => {
                void resource.reload();
                onSaved();
              }}
              onClose={() => {
                const query = new URLSearchParams(window.location.search);
                query.delete("task_draft");
                window.location.href = `${window.location.pathname}${query.size ? `?${query}` : ""}`;
              }}
            />
          )}
          <ErrorNotice error={failure} />
          {edit.pending && !edit.busy && (
            <button
              className="button secondary"
              onClick={() =>
                void edit
                  .retry<TaskDraftView>()
                  .then(async (value) => {
                    if (intent === "template") {
                      const result = await saveAck(
                        value,
                        edit.pending?.body as TemplateRequest | undefined,
                      );
                      if (result) onSaved();
                      return;
                    }
                    if (value?.data.id === id && value.etag) {
                      setAck({ etag: value.etag });
                      void resource.reload();
                    }
                  })
                  .catch(setFailure)
              }
            >
              恢复原草案更新结果（保留原保存意图）
            </button>
          )}
          {save.pending && !save.busy && (
            <button
              className="button secondary"
              onClick={() =>
                void save.retry<TemplateView>().then((value) => {
                  if (!value) return;
                  void resource.reload();
                  onSaved();
                })
              }
            >
              恢复同一次模板保存结果
            </button>
          )}
        </>
      )}
    </section>
  );
}

function draftConfiguration(draft: TaskDraftView): TemplateRequest {
  const proposal = draft.interpretation;
  return {
    name: proposal.name,
    task_kind: proposal.task_kind ?? "supplement_impact",
    instructions: proposal.instructions,
    section_id: proposal.section_id,
    source_selection: proposal.source_selection,
    trigger: proposal.trigger,
  };
}
