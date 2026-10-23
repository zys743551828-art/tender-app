export const technicalCategories: Record<string, string> = {
  "technical-body": "施组正文",
  "technical-attachment": "技术附件",
  "business-body": "商务正文",
  technical: "技术",
  qualification: "资格材料",
  business: "商务",
  commercial: "商务",
  pricing: "报价材料",
  price: "报价",
  attachment: "附件",
  annex: "附件",
  unclassified: "未分类",
};
export const technicalPartLabel = (
  part: { category: string; first_page: number; last_page: number },
  member: number,
) =>
  `文件 ${member + 1} · ${technicalCategories[part.category] ?? part.category} · 物理页 ${part.first_page}—${part.last_page}`;
