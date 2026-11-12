import type { EvidenceView } from "./contracts";

// Only remove whitespace between Han characters for navigation. Never rewrite
// evidence, join blocks, or normalize digits/punctuation that may change meaning.
export function normalizeEvidenceQuery(text: string) {
  return text
    .trim()
    .replace(/(?<=\p{Script=Han})\s+(?=\p{Script=Han})/gu, "")
    .toLowerCase();
}

export function searchEvidence(items: EvidenceView[], query: string) {
  const needle = normalizeEvidenceQuery(query);
  if (!needle) return { total: 0, items: [] as EvidenceView[] };
  const matches = items.filter(
    (item) =>
      item.source_status !== "withdrawn" &&
      normalizeEvidenceQuery(item.quote).includes(needle),
  );
  return { total: matches.length, items: matches.slice(0, 30) };
}
