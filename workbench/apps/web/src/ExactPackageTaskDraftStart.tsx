import { useRef, useState } from "react";
import { api } from "./api";
import type { Bid } from "./contracts";
import { ErrorNotice } from "./components";
import { jsonDigest } from "./editorSchema";
import { executionId, recordObject } from "./executionInputValidation";
import { historicalSame } from "./historicalImportProtocol";
import { knowledgeStorageKey, useKnowledgeInput } from "./knowledgeStorage";
import { usePackageScopeGuard } from "./packageScopeGuard";
import { isExactPackageTask } from "./taskState";
import type {
  TaskDraftRequest,
  TaskDraftView,
  TemplateRequest,
} from "./taskTriggerContracts";
import { useRecordedCommand } from "./useRecordedCommand";

/** Create a private draft from the already verified selection; the interpreter cannot choose its source. */
export function ExactPackageTaskDraftStart({
  bidId,
  memberId,
  identity,
  configuration,
  etag,
}: {
  bidId: string;
  memberId: string;
  identity: string;
  configuration: TemplateRequest;
  etag: string;
}) {
  const scope = `task-draft:${memberId}:${bidId}:${identity}:create`;
  const formKey =
    knowledgeStorageKey(memberId, bidId) + `task-package-draft:${identity}:`;
  const [open, setOpen] = useState(false);
  const [text, setText] = useKnowledgeInput(formKey + "text", "");
  const [basis, setBasis] = useKnowledgeInput(formKey + "etag", etag);
  const [saved, setSaved] = useState<TaskDraftView | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const original = useRef<TaskDraftRequest | null>(null);
  const path = `/bids/${bidId}/task-definition-drafts`;
  const source = isExactPackageTask(configuration)
    ? {
        mode: "exact_package_review" as const,
        input: configuration.source_selection.input,
      }
    : null;
  const [damaged] = useState(() => {
    try {
      const raw = sessionStorage.getItem(`tender:command-record:${scope}`);
      if (!raw) return false;
      const record = JSON.parse(raw);
      return (
        !recordObject(record) ||
        record.path !== path ||
        ![undefined, "POST"].includes(record.method as string | undefined) ||
        !executionId(record.key) ||
        typeof record.etag !== "string" ||
        !new RegExp(`^"bid:${bidId}:[a-f0-9]{64}"$`).test(record.etag) ||
        !recordObject(record.body) ||
        typeof record.body.request !== "string" ||
        !record.body.request.trim() ||
        record.body.section_id !== null ||
        !historicalSame(record.body.source_selection, source)
      );
    } catch {
      return true;
    }
  });
  const command = useRecordedCommand(scope, async (reply) => {
    const expected = original.current;
    const draft = reply.data as TaskDraftView;
    const proposal = draft?.interpretation;
    if (
      !expected ||
      !recordObject(draft) ||
      !recordObject(proposal) ||
      !executionId(draft.id) ||
      draft.bid_id !== bidId ||
      draft.created_by !== memberId ||
      draft.revision !== 1 ||
      reply.etag !== `"task-draft:${draft.id}:1"` ||
      draft.saved_template_id !== null ||
      draft.explicitly_edited !== false ||
      proposal.interpreter !== "bounded-zh-task-draft/1" ||
      proposal.raw_request !== expected.request ||
      proposal.section_id !== null ||
      !historicalSame(proposal.source_selection, expected.source_selection) ||
      proposal.template_saved !== false ||
      proposal.run_created !== false ||
      proposal.formal_decisions_allowed !== false ||
      draft.configuration_digest !== (await jsonDigest(proposal))
    )
      throw new Error(
        "草案回执与原成员、请求或确切整包输入不一致，保留原请求。",
      );
  });
  if (command.pending)
    original.current = command.pending.body as TaskDraftRequest;
  const pending = !!command.pending || damaged;
  usePackageScopeGuard(`task-package-draft:${memberId}:${bidId}:${identity}`, {
    busy: command.busy,
    pending,
    dirty: !!text.trim() && !saved,
  });
  function accept(value: TaskDraftView | undefined) {
    if (value) setSaved(value);
  }
  async function create() {
    if (!source || !text.trim() || !basis || pending || command.busy || saved)
      return;
    const body: TaskDraftRequest = {
      request: text.trim(),
      section_id: null,
      source_selection: source,
    };
    original.current = body;
    accept((await command.run<TaskDraftView>(path, body, basis))?.data);
  }
  return (
    <section
      className="exact-package-task-command"
      aria-label="从固定整包输入拟定私有草案"
    >
      <button
        type="button"
        className="text-button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        先用文字拟定私有草案
      </button>
      {(open || pending || saved) && (
        <>
          <p className="small-note">
            沿用上方已核对的原输入。生成草案不保存模板、不运行；解释后仍须在表单明确选择触发方式，默认手动。
          </p>
          {!saved && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void create();
              }}
            >
              <label>
                这份整包想反复核对什么
                <textarea
                  aria-label="这份整包想反复核对什么"
                  rows={3}
                  required
                  maxLength={8000}
                  value={text}
                  disabled={pending || command.busy}
                  onChange={(event) => setText(event.target.value)}
                />
              </label>
              <button
                className="button secondary"
                disabled={
                  !source ||
                  !text.trim() ||
                  !basis ||
                  pending ||
                  command.busy ||
                  !!command.conflict
                }
              >
                生成这份输入的私有草案
              </button>
            </form>
          )}
          <ErrorNotice error={failure ?? command.error} />
          {command.conflict && !pending && (
            <button
              type="button"
              className="text-button"
              onClick={async () => {
                try {
                  const result = await api<Bid>(`/bids/${bidId}`);
                  if (
                    result.data.id !== bidId ||
                    !result.etag ||
                    !new RegExp(`^"bid:${bidId}:[a-f0-9]{64}"$`).test(
                      result.etag,
                    )
                  )
                    throw new Error("项目修订基准身份不一致，固定输入保留。");
                  setBasis(result.etag);
                  command.clearError();
                  setFailure(null);
                } catch (error) {
                  setFailure(error);
                }
              }}
            >
              核对项目修订，保留原整包输入
            </button>
          )}
          {command.pending && !damaged && !command.busy && (
            <button
              type="button"
              className="button secondary"
              onClick={() =>
                void command
                  .retry<TaskDraftView>()
                  .then((value) => accept(value?.data))
              }
            >
              恢复原整包草案请求
            </button>
          )}
          {damaged && (
            <p className="notice error">
              本地草案恢复记录无法核验，原记录保留，暂停新写入。
            </p>
          )}
          {saved && (
            <p className="notice success">
              私有草案已保存，尚未创建模板或运行。
              <a
                className="text-link"
                href={`/bids/${bidId}/tasks?task_draft=${saved.id}`}
              >
                打开草案并明确触发方式
              </a>
            </p>
          )}
        </>
      )}
    </section>
  );
}
