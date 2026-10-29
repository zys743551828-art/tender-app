import { useCallback, useEffect, useState } from "react";
import type {
  PackageAuthoringInputCapabilities,
  PackageAuthoringInputRequest,
  WorkContextChoicePage,
} from "./contracts";
import { ErrorNotice } from "./components";
import { exactKeys, recordObject } from "./executionInputValidation";
import { historicalSame } from "./historicalImportProtocol";
import { knowledgeStorageKey, useKnowledgeInput } from "./knowledgeStorage";
import { AuthoringInputSummary } from "./PackageAuthoringInput";
import type { VerifiedAuthoringInput } from "./packageAuthoringInputProtocol";
import { usePackageScopeGuard } from "./packageScopeGuard";
import type { PackageNavigationState } from "./packageNavigation";
import { validateWorkContextChoices } from "./workContextDirectoryProtocol";
import { validateAuthoringWorkContext } from "./workContextAuthoringProtocol";
import { AuthoringCapturePackagePicker } from "./AuthoringCapturePackagePicker";
import {
  AuthoringCaptureBlockers,
  AuthoringCaptureFacts,
} from "./AuthoringCaptureFacts";
import {
  captureInventoryDirectory,
  captureInventoryView,
  capturePackageView,
} from "./authoringCaptureDirectoryProtocol";
import {
  buildCaptureRequest,
  emptyCaptureDraft,
  readCaptureDraft,
  type CaptureDraft,
} from "./authoringCaptureForm";
import {
  captureFactsPath,
  captureFailure,
  captureIdentityNames,
  captureNodePath,
  validateCaptureFacts,
  validateCaptureFactSets,
  validateCaptureNodes,
  type CaptureFactSelection,
} from "./authoringInputCatalogProtocol";
import {
  useAuthoringCaptureDirectory,
  useAuthoringCaptureRead,
} from "./useAuthoringCaptureRead";
import { useAuthoringCaptureCommand } from "./useAuthoringCaptureCommand";
import "./AuthoringPackageCapture.css";

export type AuthoringPackageCaptureProps = {
  bidId: string;
  memberId: string;
  disabled?: boolean;
  onSaved?: (input: VerifiedAuthoringInput) => void;
  onStateChange?: (state: PackageNavigationState) => void;
};
function capabilities(v: unknown): PackageAuthoringInputCapabilities {
  if (
    !recordObject(v) ||
    !exactKeys(v, [
      "protocol",
      "capture_available",
      "generation_available",
      "publication_available",
      "apply_available",
      "build_available",
      "automatic_input_selection",
      "supported_target",
      "target_relation",
      "context_limit_bytes",
      "blocking_reasons",
    ]) ||
    v.protocol !== "package-authoring-input-capabilities/1" ||
    typeof v.capture_available !== "boolean" ||
    v.automatic_input_selection !== false ||
    [
      v.generation_available,
      v.publication_available,
      v.apply_available,
      v.build_available,
    ].some((x) => x !== false) ||
    v.supported_target !== "plain_text_stable_node" ||
    v.target_relation !== "draft_using_package_context" ||
    v.context_limit_bytes !== 32 * 1024 * 1024 ||
    !Array.isArray(v.blocking_reasons) ||
    !v.blocking_reasons.every((x) => typeof x === "string") ||
    !historicalSame(
      v.blocking_reasons,
      v.capture_available
        ? ["AUTHORING_PACKAGE_EXECUTOR_NOT_READY"]
        : ["AUTHORING_PACKAGE_INPUT_NOT_CONFIGURED"],
    )
  )
    captureFailure("采集保存能力尚不能核验。");
  return v as PackageAuthoringInputCapabilities;
}
function Feedback({ state }: { state: { error: unknown; busy: boolean } }) {
  return (
    <>
      <ErrorNotice error={state.error} />
      {state.busy && <p role="status">正在读取并核对明确选择…</p>}
    </>
  );
}

function CaptureWorkspace({
  bidId,
  memberId,
  disabled = false,
  onSaved,
  onStateChange,
}: AuthoringPackageCaptureProps) {
  const formKey =
    knowledgeStorageKey(memberId, bidId) + "authoring-package-capture:draft";
  const [stored, store] = useKnowledgeInput<CaptureDraft>(
    formKey,
    emptyCaptureDraft(),
  );
  const [saved, setSaved] = useState<VerifiedAuthoringInput | null>(null),
    [failure, setFailure] = useState<unknown>(null);
  let draft: CaptureDraft,
    draftError: unknown = null;
  try {
    draft = readCaptureDraft(stored, bidId);
  } catch (error) {
    draft = emptyCaptureDraft();
    draftError = error;
  }
  const command = useAuthoringCaptureCommand({ memberId, bidId });
  const locked =
    disabled ||
    !!saved ||
    command.busy ||
    !!command.pending ||
    command.blocked ||
    !!draftError;
  const dirty = !saved && !historicalSame(stored, emptyCaptureDraft());
  usePackageScopeGuard(`authoring-package-capture:${memberId}:${bidId}`, {
    busy: command.busy,
    pending: !!command.pending || command.blocked,
    dirty,
  });
  useEffect(() => {
    onStateChange?.({
      busy: command.busy,
      pending: !!command.pending || command.blocked,
      dirty,
    });
  }, [onStateChange, command.busy, command.pending, command.blocked, dirty]);
  useEffect(
    () => () => onStateChange?.({ busy: false, pending: false, dirty: false }),
    [onStateChange],
  );
  function change(value: CaptureDraft) {
    if (!locked) {
      setFailure(null);
      store(value);
    }
  }

  const capability = useAuthoringCaptureRead(
    "/authoring/package-input-capabilities",
    capabilities,
  );
  const verifyTarget = useCallback(
    (v: unknown) =>
      draft.target
        ? capturePackageView(v, bidId, "target", draft.target)
        : captureFailure(),
    [bidId, draft.target],
  );
  const verifyAuthority = useCallback(
    (v: unknown) =>
      draft.authority
        ? capturePackageView(v, bidId, "authority", draft.authority)
        : captureFailure(),
    [bidId, draft.authority],
  );
  const target = useAuthoringCaptureRead(
    draft.target
      ? `/bids/${bidId}/packages/${draft.target.package_id}/revisions/${draft.target.revision_id}`
      : null,
    verifyTarget,
  );
  const authority = useAuthoringCaptureRead(
    draft.authority
      ? `/bids/${bidId}/packages/${draft.authority.package_id}/revisions/${draft.authority.revision_id}`
      : null,
    verifyAuthority,
  );
  const inventoryBase = draft.target
    ? `/bids/${bidId}/packages/${draft.target.package_id}/revisions/${draft.target.revision_id}/requirement-inventories`
    : null;
  const inventories = useAuthoringCaptureDirectory(
    inventoryBase ? inventoryBase + "?limit=20" : null,
    captureInventoryDirectory,
  );
  const verifyInventory = useCallback(
    (v: unknown) =>
      target.value && authority.value && draft.inventory
        ? captureInventoryView(
            v,
            target.value,
            authority.value,
            draft.inventory,
          )
        : captureFailure(),
    [target.value, authority.value, draft.inventory],
  );
  const inventory = useAuthoringCaptureRead(
    inventoryBase && draft.inventory && target.ready && authority.ready
      ? `${inventoryBase}/${draft.inventory.id}`
      : null,
    verifyInventory,
  );

  const verifySnapshots = useCallback(
    (v: unknown) =>
      validateWorkContextChoices(v, bidId, "draft_snapshot").then((page) => ({
        ...page,
        total_items: page.total,
      })),
    [bidId],
  );
  const snapshots = useAuthoringCaptureDirectory(
    `/bids/${bidId}/work-contexts/choices?kind=draft_snapshot&limit=20`,
    verifySnapshots,
  );
  const verifySnapshot = useCallback(
    (v: unknown) =>
      draft.snapshot
        ? validateAuthoringWorkContext(v, bidId, {
            kind: "draft_snapshot",
            id: draft.snapshot.id,
            selectionDigest: draft.snapshot.selection_digest,
          })
        : captureFailure(),
    [bidId, draft.snapshot],
  );
  const snapshot = useAuthoringCaptureRead(
    draft.snapshot
      ? `/bids/${bidId}/work-contexts/draft_snapshot/${draft.snapshot.id}?expected_selection_digest=${draft.snapshot.selection_digest}`
      : null,
    verifySnapshot,
  );
  const verifyNodes = useCallback(
    (v: unknown) =>
      draft.snapshot && draft.section
        ? validateCaptureNodes(v, bidId, {
            snapshot_id: draft.snapshot.id,
            snapshot_digest: draft.snapshot.selection.snapshot_digest,
            section_id: draft.section.id,
            section_digest: draft.section.digest,
          })
        : captureFailure(),
    [bidId, draft.snapshot, draft.section],
  );
  const nodes = useAuthoringCaptureRead(
    draft.snapshot && draft.section
      ? captureNodePath(
          bidId,
          draft.snapshot.id,
          draft.section.id,
          draft.snapshot.selection.snapshot_digest,
          draft.section.digest,
        )
      : null,
    verifyNodes,
  );

  const verifySets = useCallback(
    (v: unknown) => {
      const page = validateCaptureFactSets(v, bidId);
      return {
        ...page,
        items: page.items.map((item) => ({ ...item, id: item.fact_set_id })),
      };
    },
    [bidId],
  );
  const sets = useAuthoringCaptureDirectory(
    `/bids/${bidId}/authoring/input-catalog/fact-sets?limit=20`,
    verifySets,
  );
  const factSelection: CaptureFactSelection | null =
    draft.factSet && draft.target && draft.authority
      ? {
          fact_set_id: draft.factSet.id,
          fact_set_digest: draft.factSet.digest,
          fact_head_revision: draft.factSet.head_revision,
          target: draft.target,
          authority: draft.authority,
        }
      : null;
  const factSelectionKey = JSON.stringify(factSelection);
  const verifyFacts = useCallback(
    (v: unknown) => {
      const selected: CaptureFactSelection | null =
        JSON.parse(factSelectionKey);
      if (!selected) captureFailure();
      const page = validateCaptureFacts(v, bidId, selected);
      return {
        ...page,
        items: page.items.map((item) => ({ ...item, id: item.fact_id })),
      };
    },
    [bidId, factSelectionKey],
  );
  const facts = useAuthoringCaptureDirectory(
    factSelection ? captureFactsPath(bidId, factSelection) : null,
    verifyFacts,
  );

  const ready =
    capability.ready &&
    capability.value?.capture_available &&
    target.ready &&
    authority.ready &&
    inventories.ready &&
    inventories.page?.current_inventory_id === draft.inventory?.id &&
    inventory.ready &&
    snapshot.ready &&
    nodes.ready &&
    facts.ready;
  let request: PackageAuthoringInputRequest | null = null,
    missing = "请依次选择包、清单、已保存快照和节点，再核对事实身份与用途。";
  if (
    ready &&
    target.value &&
    authority.value &&
    inventory.value &&
    snapshot.value &&
    nodes.value &&
    facts.page
  ) {
    try {
      request = buildCaptureRequest(draft, {
        target: target.value,
        authority: authority.value,
        inventory: inventory.value,
        snapshot: snapshot.value,
        nodes: nodes.value,
        facts: facts.page,
        items: facts.items,
      });
    } catch (error) {
      missing = error instanceof Error ? error.message : missing;
    }
  }
  async function accepted(value: VerifiedAuthoringInput | null) {
    if (!value) return;
    setSaved(value);
    store(emptyCaptureDraft());
    setFailure(null);
    try {
      onSaved?.(value);
    } catch {
      setFailure(
        new Error(
          "固定输入已保存；后续工作面未能打开，可从已保存输入目录找到这份记录。",
        ),
      );
    }
  }
  function chooseSnapshot(item: WorkContextChoicePage["items"][number]) {
    if (item.selection.kind !== "draft_snapshot") return;
    change({
      ...draft,
      snapshot: {
        id: item.id,
        label: item.label,
        selection_digest: item.selection_digest,
        selection: item.selection,
      },
      section: null,
      node: null,
    });
  }
  function refreshSelected() {
    if (command.busy || command.blocked) return;
    if (command.rejected && !command.acknowledgeRejection()) return;
    void target.reload();
    void authority.reload();
    void inventories.load();
    void inventory.reload();
    void snapshot.reload();
    void nodes.reload();
    void sets.load();
    void facts.load();
  }
  const selectedNode = nodes.value?.nodes.find(
    (n) =>
      n.node_id === draft.node?.id &&
      n.before_node_digest === draft.node.digest,
  );
  return (
    <section
      className="authoring-package-capture"
      aria-label="采集固定整包编写输入"
    >
      <header>
        <h2>采集一份固定整包编写输入</h2>
        <p>
          选择明确的两包、需求清单、正文节点与事实依据，保存为可核对的固定输入。保存后可在章节建议任务中选用；运行和采纳仍需各自核验。
        </p>
      </header>
      <ErrorNotice error={draftError ?? failure ?? command.error} />
      <Feedback state={capability} />
      {capability.value && !capability.value.capture_available && (
        <p className="notice warning">
          当前服务尚未开放固定输入保存。选择和本机草稿保留，可在服务就绪后重新核对。
        </p>
      )}
      {!!draftError && !command.pending && !command.blocked && (
        <button
          type="button"
          className="button secondary"
          onClick={() => store(emptyCaptureDraft())}
        >
          明确放弃损坏的本机采集草稿
        </button>
      )}
      {command.pending && (
        <section className="notice warning" aria-label="采集保存请求恢复">
          <p>
            {command.rejected
              ? "服务明确拒绝了已过期的基准。原选择和用途保留，请重新核对后编辑。"
              : "上次保存尚未取得可核验回执。完整原请求与幂等键保留，新的保存已暂停。"}
          </p>
          <details>
            <summary>核对完整原保存请求</summary>
            <pre className="preserve-text">
              {JSON.stringify(command.pending.request.body, null, 2)}
            </pre>
          </details>
          <button
            type="button"
            className="button secondary"
            disabled={command.busy || command.blocked}
            onClick={() =>
              command.rejected
                ? refreshSelected()
                : void command.retry().then(accepted)
            }
          >
            {command.rejected ? "保留草稿并重新核对" : "恢复原保存请求"}
          </button>
        </section>
      )}
      {saved ? (
        <section aria-label="已保存的固定编写输入">
          <p className="notice success" role="status">
            这份固定编写输入已保存。没有自动启动模型、发布内容或修改正文。
          </p>
          <AuthoringInputSummary input={saved} />
          <button
            type="button"
            className="button secondary"
            onClick={() => {
              setSaved(null);
              setFailure(null);
            }}
          >
            继续采集另一份
          </button>
        </section>
      ) : (
        <>
          <section className="panel capture-step">
            <h3>1. 包与需求清单</h3>
            <div className="capture-two-columns">
              <AuthoringCapturePackagePicker
                bidId={bidId}
                kind="bid"
                selected={draft.target}
                disabled={locked}
                onSelect={(target) =>
                  change({
                    ...draft,
                    target,
                    inventory: null,
                    factSet: null,
                    identities: emptyCaptureDraft().identities,
                    uses: [],
                  })
                }
              />
              <AuthoringCapturePackagePicker
                bidId={bidId}
                kind="authority"
                selected={draft.authority}
                disabled={locked}
                onSelect={(authority) =>
                  change({
                    ...draft,
                    authority,
                    inventory: null,
                    factSet: null,
                    identities: emptyCaptureDraft().identities,
                    uses: [],
                  })
                }
              />
            </div>
            <Feedback state={target} />
            <Feedback state={authority} />
            <Feedback state={inventories} />
            <Feedback state={inventory} />
            {draft.target && (
              <fieldset disabled={locked || !inventories.ready}>
                <legend>明确选择需求清单</legend>
                <select
                  aria-label="需求清单"
                  value={draft.inventory?.id ?? ""}
                  onChange={(e) => {
                    const value = inventories.items.find(
                      (i) => i.id === e.target.value,
                    );
                    change({
                      ...draft,
                      inventory: value
                        ? { id: value.id, digest: value.digest }
                        : null,
                    });
                  }}
                >
                  <option value="">选择绑定这份投标包修订的清单</option>
                  {draft.inventory &&
                    !inventories.items.some(
                      (i) => i.id === draft.inventory!.id,
                    ) && (
                      <option value={draft.inventory.id}>
                        保留已选清单 {draft.inventory.id.slice(0, 8)}
                        （未在本页列出）
                      </option>
                    )}
                  {inventories.items.map((i) => (
                    <option key={i.id} value={i.id}>
                      {new Date(i.created_at).toLocaleString("zh-CN")} ·{" "}
                      {i.id.slice(0, 8)}
                      {inventories.page?.current_inventory_id === i.id
                        ? " · 当前清单"
                        : " · 历史清单"}
                    </option>
                  ))}
                </select>
              </fieldset>
            )}
            {inventories.page?.has_more && (
              <button
                type="button"
                className="text-button"
                disabled={locked || inventories.busy || !inventories.ready}
                onClick={() => void inventories.load(true)}
              >
                加载更多需求清单
              </button>
            )}
            {inventories.ready && !inventories.items.length && draft.target && (
              <p className="small-empty">
                这份包修订尚无需求清单。请先完成需求抽取并核对，再回来选择。
              </p>
            )}
            {draft.inventory &&
              inventories.ready &&
              inventories.page?.current_inventory_id !== draft.inventory.id && (
                <p className="notice warning">
                  已选历史清单保留；当前清单已不同，新保存需要明确重新选择。
                </p>
              )}
            {inventory.value && (
              <p className="small-note">
                已核对清单与所选两包的固定摘要，共{" "}
                {inventory.value.manifest.requirements.length}{" "}
                项要求；清单存在不表示语义完整性已测定。
              </p>
            )}
          </section>
          <section className="panel capture-step">
            <h3>2. 已保存的正文快照与稳定节点</h3>
            <p className="small-note">
              这里选择保存过的原稿。未保存的编辑内容需要先在正文编辑器中保存。
            </p>
            <Feedback state={snapshots} />
            <Feedback state={snapshot} />
            <Feedback state={nodes} />
            <label>
              正文快照
              <select
                disabled={locked || !snapshots.ready}
                value={draft.snapshot?.id ?? ""}
                onChange={(e) => {
                  const item = snapshots.items.find(
                    (i) => i.id === e.target.value,
                  );
                  if (item) chooseSnapshot(item);
                  else
                    change({
                      ...draft,
                      snapshot: null,
                      section: null,
                      node: null,
                    });
                }}
              >
                <option value="">明确选择已保存快照</option>
                {draft.snapshot &&
                  !snapshots.items.some((i) => i.id === draft.snapshot!.id) && (
                    <option value={draft.snapshot.id}>
                      保留：{draft.snapshot.label}
                    </option>
                  )}
                {snapshots.items.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.label} · {i.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
            {snapshots.page?.has_more && (
              <button
                className="text-button"
                type="button"
                disabled={locked || snapshots.busy || !snapshots.ready}
                onClick={() => void snapshots.load(true)}
              >
                加载更多正文快照
              </button>
            )}
            {snapshots.ready && !snapshots.items.length && (
              <p className="small-empty">
                尚无已保存正文快照。请先创建并保存一份稿件。
              </p>
            )}
            {snapshot.value?.document && (
              <label>
                快照中的章节
                <select
                  disabled={locked || !snapshot.ready}
                  value={draft.section?.id ?? ""}
                  onChange={(e) => {
                    const section = snapshot.value?.document?.sections.find(
                      (s) => s.section_id === e.target.value,
                    );
                    change({
                      ...draft,
                      section: section
                        ? { id: section.section_id, digest: section.digest }
                        : null,
                      node: null,
                    });
                  }}
                >
                  <option value="">明确选择章节</option>
                  {snapshot.value.document.sections.map((s) => (
                    <option key={s.section_id} value={s.section_id}>
                      {s.title} · 原修订 {s.section_revision}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {nodes.value && (
              <>
                <AuthoringCaptureBlockers
                  reasons={nodes.value.blocking_reasons}
                />
                <label>
                  稳定文字节点
                  <select
                    disabled={locked || !nodes.ready}
                    value={draft.node?.id ?? ""}
                    onChange={(e) => {
                      const node = nodes.value?.nodes.find(
                        (n) => n.node_id === e.target.value,
                      );
                      change({
                        ...draft,
                        node: node
                          ? {
                              id: node.node_id,
                              digest: node.before_node_digest,
                            }
                          : null,
                      });
                    }}
                  >
                    <option value="">明确选择一个段落或标题</option>
                    {nodes.value.nodes.map((n, i) => (
                      <option key={n.node_id} value={n.node_id}>
                        {n.node_type === "heading" ? "标题" : "段落"} {i + 1} ·{" "}
                        {n.text
                          ? n.text.slice(0, 60) +
                            (n.text.length > 60 ? "…" : "")
                          : "空白文字节点"}
                      </option>
                    ))}
                  </select>
                </label>
                {selectedNode && (
                  <section
                    className="capture-node-preview"
                    aria-label="所选节点完整原文"
                  >
                    <h4>所选节点的完整原文</h4>
                    <p className="preserve-text">
                      {selectedNode.text || "（空白文字节点）"}
                    </p>
                    <details>
                      <summary>节点与快照固定身份</summary>
                      <p className="digest">{selectedNode.node_id}</p>
                      <p className="digest">
                        {selectedNode.before_node_digest}
                      </p>
                    </details>
                  </section>
                )}
              </>
            )}
          </section>
          <section className="panel capture-step">
            <h3>3. 事实身份与本次用途</h3>
            <Feedback state={sets} />
            <Feedback state={facts} />
            <label>
              事实集
              <select
                disabled={
                  locked || !sets.ready || !draft.target || !draft.authority
                }
                value={draft.factSet?.id ?? ""}
                onChange={(e) => {
                  const item = sets.items.find(
                      (i) => i.fact_set_id === e.target.value,
                    ),
                    head = sets.page?.current_head;
                  change({
                    ...draft,
                    factSet:
                      item && head
                        ? {
                            id: item.fact_set_id,
                            digest: item.fact_set_digest,
                            head_revision: head.revision,
                          }
                        : null,
                    identities: emptyCaptureDraft().identities,
                    uses: [],
                  });
                }}
              >
                <option value="">明确选择事实集</option>
                {draft.factSet &&
                  !sets.items.some(
                    (i) => i.fact_set_id === draft.factSet!.id,
                  ) && (
                    <option value={draft.factSet.id}>
                      保留已选事实集 {draft.factSet.id.slice(0, 8)}
                    </option>
                  )}
                {sets.items.map((i) => (
                  <option key={i.fact_set_id} value={i.fact_set_id}>
                    {i.is_current
                      ? `当前事实集 · 头修订 ${sets.page?.current_head?.revision}`
                      : "历史事实集"}{" "}
                    · {i.fact_count} 项 · {i.fact_set_id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
            <p className="small-note">
              请核对事实集及其具体内容，再明确选择本次编写要使用的事实。
            </p>
            {sets.page?.has_more && (
              <button
                className="text-button"
                type="button"
                disabled={locked || sets.busy || !sets.ready}
                onClick={() => void sets.load(true)}
              >
                加载更多事实集
              </button>
            )}
            {sets.page && (
              <AuthoringCaptureBlockers reasons={sets.page.blocking_reasons} />
            )}
            {facts.page && (
              <>
                <p className="small-note">
                  本次已列出 {facts.items.length} / {facts.page.total_items}{" "}
                  项事实，尚未选择的事实不会自动加入保存请求。
                </p>
                <AuthoringCaptureFacts
                  page={facts.page}
                  items={facts.items}
                  draft={draft}
                  disabled={locked || !facts.ready}
                  onChange={change}
                />
                {facts.page.has_more && (
                  <button
                    type="button"
                    className="text-button"
                    disabled={locked || facts.busy || !facts.ready}
                    onClick={() => void facts.load(true)}
                  >
                    加载更多事实
                  </button>
                )}
              </>
            )}
          </section>
          <section className="panel capture-step">
            <h3>4. 核对并明确保存</h3>
            <p>
              已选择{" "}
              {captureIdentityNames.filter((n) => !!draft.identities[n]).length}{" "}
              / 5 个业务编号、{draft.uses.length}{" "}
              项用途声明。保存时会核验全部原件字节、完整包、清单、事实与正文当前基准。
            </p>
            {request ? (
              <details>
                <summary>核对完整固定输入身份与用途声明</summary>
                <pre className="preserve-text">
                  {JSON.stringify(request, null, 2)}
                </pre>
              </details>
            ) : (
              <p className="small-note">{missing}</p>
            )}
            <div className="capture-actions">
              <button
                type="button"
                className="button secondary"
                disabled={command.busy || !!command.pending || command.blocked}
                onClick={refreshSelected}
              >
                重新核对已选依据
              </button>
              <button
                type="button"
                className="button primary"
                disabled={locked || !request || !ready}
                onClick={() => {
                  if (request && ready && !locked)
                    void command.run(request).then(accepted);
                }}
              >
                {command.busy ? "正在保存固定输入…" : "保存这份固定编写输入"}
              </button>
            </div>
          </section>
        </>
      )}
    </section>
  );
}
export function AuthoringPackageCapture(props: AuthoringPackageCaptureProps) {
  return (
    <CaptureWorkspace key={`${props.memberId}:${props.bidId}`} {...props} />
  );
}
