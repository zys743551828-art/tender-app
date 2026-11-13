import type {
  AuthoringDocument,
  AuthoringNode,
  AuthoringExactMarkedTextEditCapabilities,
} from "./contracts";
import { exactKeys, recordObject as object } from "./executionInputValidation";

export function markedTextNotBlank(text: string) {
  return !!text.replace(/[\s\u0085]/gu, "");
}
export function validMarkedReason(text: string) {
  return (
    markedTextNotBlank(text) &&
    !Array.from(text).some(
      (c) =>
        (c.charCodeAt(0) < 32 && c !== "\n" && c !== "\t") ||
        c.charCodeAt(0) === 127,
    )
  );
}
export function validMarkedReplacement(text: string) {
  return (
    markedTextNotBlank(text) &&
    !Array.from(text).some(
      (c) => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127,
    )
  );
}
export function editableMarkedTextNodes(content: AuthoringDocument) {
  const found: { id: string; text: string; node: AuthoringNode }[] = [];
  function visit(node: AuthoringNode) {
    if (
      (node.type === "paragraph" || node.type === "heading") &&
      node.content.length === 1
    ) {
      const leaf = node.content[0];
      if (
        leaf.type === "text" &&
        leaf.marks?.length &&
        leaf.marks.every(
          (mark) =>
            exactKeys(mark, ["type"]) &&
            (mark.type === "bold" || mark.type === "italic"),
        ) &&
        new Set(leaf.marks.map((mark) => mark.type)).size === leaf.marks.length
      ) {
        found.push({ id: node.attrs.id, text: leaf.text, node });
      }
    }
    if ("content" in node) node.content.forEach(visit);
  }
  content.content.forEach(visit);
  return found;
}
export function replaceMarkedText(
  content: AuthoringDocument,
  id: string,
  text: string,
) {
  const copy = structuredClone(content);
  const matches = editableMarkedTextNodes(copy).filter((n) => n.id === id);
  const node = matches[0]?.node;
  if (
    matches.length !== 1 ||
    !node ||
    !("content" in node) ||
    node.content[0]?.type !== "text" ||
    !validMarkedReplacement(text)
  )
    throw new Error("格式文字修订无法核对");
  node.content[0].text = text;
  return copy;
}
export function readMarkedTextEditCapabilities(
  value: unknown,
): AuthoringExactMarkedTextEditCapabilities {
  if (
    !object(value) ||
    !exactKeys(value, [
      "protocol",
      "available",
      "supported_content",
      "preserves_source_refs",
      "preserves_rule_ids",
      "preserves_marks",
      "ordinary_edit_available",
      "blocking_reasons",
    ]) ||
    value.protocol !== "authoring-exact-text-edit-capabilities/3" ||
    typeof value.available !== "boolean" ||
    value.supported_content !== "single_marked_text_leaf_preserve_marks" ||
    value.preserves_source_refs !== true ||
    value.preserves_rule_ids !== true ||
    value.preserves_marks !== true ||
    value.ordinary_edit_available !== false ||
    !Array.isArray(value.blocking_reasons) ||
    !value.blocking_reasons.every((r) => typeof r === "string") ||
    value.available === !!value.blocking_reasons.length
  )
    throw new Error("格式文字修订能力无法核对");
  return value as unknown as AuthoringExactMarkedTextEditCapabilities;
}
