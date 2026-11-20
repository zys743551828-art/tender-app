import type { AuthoringTreeView, AuthoringWorkContext } from "./contracts";
import { recordObject } from "./executionInputValidation";
import { validateCurrentDraftSnapshot } from "./fixedAuthoringSnapshot";

type SavedDocument = NonNullable<AuthoringWorkContext["document"]>;
type SectionContent = SavedDocument["sections"][number]["content"];

const readable = (text: string) => /[^\p{White_Space}\p{Cf}]/u.test(text);

function hasText(node: unknown): boolean {
  if (!recordObject(node)) return false;
  return node.type === "text"
    ? typeof node.text === "string" && readable(node.text)
    : Array.isArray(node.content) && node.content.some(hasText);
}

export function chapterBodyState(content: SectionContent) {
  if (
    content.content.some(
      (node) => node.type === "table" || node.type === "image",
    )
  )
    return "objects_to_review" as const;
  if (content.content.some((node) => node.type !== "heading" && hasText(node)))
    return "body_text" as const;
  if (content.content.some((node) => node.type === "heading" && hasText(node)))
    return "headings_only" as const;
  return "no_readable_body" as const;
}

export const isWritingGap = (state: ReturnType<typeof chapterBodyState>) =>
  state === "headings_only" || state === "no_readable_body";

export async function readTechnicalDraftProgress(
  value: unknown,
  bidId: string,
  tree: AuthoringTreeView,
) {
  const view = await validateCurrentDraftSnapshot(value, bidId, {
    draft_id: tree.draft_id,
    snapshot_id: tree.snapshot_id,
    base_draft_revision: tree.draft_revision,
  });
  const nodes = tree.nodes.filter((node) => !node.deleted);
  const outline = view.document.outline;
  const byId = new Map(nodes.map((node) => [node.section_id, node]));
  if (
    byId.size !== nodes.length ||
    byId.size !== view.document.sections.length ||
    (tree.structure_version_id === null) !== (outline === null) ||
    outline?.some((node) => {
      const expected = byId.get(node.section_id);
      return (
        !expected ||
        node.parent_id !== expected.parent_id ||
        node.ordinal !== expected.ordinal ||
        node.node_type !== expected.node_type
      );
    }) ||
    view.document.sections.some((section) => {
      const expected = byId.get(section.section_id);
      return (
        !expected ||
        section.section_revision !== expected.section_revision ||
        section.title !== expected.title
      );
    })
  )
    throw new Error("当前目录与已保存正文的章节身份不一致，未显示旧进度。");

  return view.document.sections.map((section) => ({
    id: section.section_id,
    title: section.title,
    revision: section.section_revision,
    state: chapterBodyState(section.content),
  }));
}
