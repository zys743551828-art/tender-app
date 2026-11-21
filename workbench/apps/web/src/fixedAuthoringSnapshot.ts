import { captureFailure } from "./authoringInputCatalogProtocol";
import { jsonDigest } from "./editorSchema";
import { executionSha, recordObject } from "./executionInputValidation";
import type { FixedAuthoringChapter } from "./packageAuthoringInputProtocol";
import { validateAuthoringWorkContext } from "./workContextAuthoringProtocol";

type DraftObservation = Pick<
  FixedAuthoringChapter,
  "draft_id" | "snapshot_id" | "base_draft_revision"
>;

export async function validateCurrentDraftSnapshot(
  value: unknown,
  bidId: string,
  target: DraftObservation,
  identityError = "已读正文不属于当前保存的草稿版本，未展示其他正文。",
) {
  if (!recordObject(value) || !executionSha(value.selection_digest))
    captureFailure("已保存正文的身份摘要无法核对。");
  // Use the independently known exact route identity, not a list item picked
  // implicitly. The shared verifier hashes the returned selection and content.
  const view = await validateAuthoringWorkContext(value, bidId, {
    kind: "draft_snapshot",
    id: target.snapshot_id,
    selectionDigest: value.selection_digest,
  });
  const selected = view.selection;
  if (
    selected.kind !== "draft_snapshot" ||
    selected.draft_id !== target.draft_id ||
    selected.draft_revision !== target.base_draft_revision ||
    !view.document
  )
    captureFailure(identityError);
  const expectedHead = await jsonDigest({
    revision: target.base_draft_revision,
    snapshot_id: target.snapshot_id,
    snapshot_digest: selected.snapshot_digest,
  });
  const head = view.current_observation.draft_head;
  if (
    head.status !== "matched" ||
    head.selected_digest !== expectedHead ||
    head.observed_digest !== expectedHead
  )
    captureFailure(
      "已保存的草稿不是当前版本，请返回章节重新核对，不会自动改用新正文。",
    );
  return { ...view, selection: selected, document: view.document };
}

export async function validateFixedAuthoringSnapshot(
  value: unknown,
  bidId: string,
  chapter: FixedAuthoringChapter,
) {
  const mismatch = "本章入口只接受当前草稿及当前章节修订，未替换其他正文。";
  const view = await validateCurrentDraftSnapshot(
    value,
    bidId,
    chapter,
    mismatch,
  );
  if (
    !view.document.sections.some(
      (section) =>
        section.section_id === chapter.section_id &&
        section.section_revision === chapter.base_section_revision,
    )
  )
    captureFailure(mismatch);
  return view;
}
