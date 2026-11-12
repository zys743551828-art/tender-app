import type { EvidenceView } from "./contracts";

// Navigation hints only: a keyword is not evidence of the document's role,
// completeness, or a permission to use the entire file in a review.
const clues = [
  { label: "招标要求", terms: ["招标文件", "评标办法", "技术标准和要求"] },
  {
    label: "施工组织或施工方案",
    terms: ["施工组织设计", "施工方案"],
  },
  {
    // Maintenance content is not proof of a complete construction submission.
    // A page can contain both clues; neither clue implies compliance.
    label: "维护服务方案",
    terms: ["维护和服务", "维保方案"],
  },
  { label: "商务或资格材料", terms: ["商务文件", "资格审查", "营业执照"] },
] as const;

export function contentClues(items: EvidenceView[]) {
  return clues.flatMap(({ label, terms }) => {
    const pages = new Set<number>();
    for (const item of items) {
      if (item.kind !== "text" || item.source_status === "withdrawn") continue;
      // OCR commonly inserts spaces between Chinese characters. This is used
      // only to find navigation clues, never to alter an evidence quotation.
      const text = item.quote.replace(/\s+/gu, "");
      if (terms.some((term) => text.includes(term)))
        pages.add(item.physical_page);
    }
    return pages.size
      ? [{ label, pages: [...pages].sort((a, b) => a - b) }]
      : [];
  });
}
