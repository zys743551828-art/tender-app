import type {
  BidPackageStoredView,
  EvidenceView,
  PackageEvidencePage,
} from "./contracts";
export type EvidenceEntry = PackageEvidencePage["items"][number];
type EvidencePage = PackageEvidencePage;
export const packageCategoryNames: Record<string, string> = {
  technical: "技术",
  business: "商务",
  qualification: "资格",
  price: "报价",
  commercial: "商务",
  attachment: "附件",
  annex: "附件",
};
export const partsOf = (view: BidPackageStoredView) =>
  view.manifest.members.flatMap((member, fileIndex) =>
    member.parts.map((part, partIndex) => ({
      member,
      part,
      fileIndex: fileIndex + 1,
      partIndex: partIndex + 1,
    })),
  );
export function memberships(
  view: BidPackageStoredView,
  value: Pick<
    EvidenceView,
    "document_version_id" | "parse_run_id" | "physical_page"
  >,
) {
  return partsOf(view)
    .filter(
      ({ member, part }) =>
        member.document_version_id === value.document_version_id &&
        member.parse.status === "frozen" &&
        member.parse.parse_run_id === value.parse_run_id &&
        part.first_page <= value.physical_page &&
        value.physical_page <= part.last_page,
    )
    .map((p) => p.part.part_id);
}
export function validateDirectory(
  page: EvidencePage,
  view: BidPackageStoredView,
) {
  if (
    page.revision_id !== view.manifest.revision_id ||
    page.package_digest !== view.digest ||
    !Array.isArray(page.items) ||
    typeof page.has_more !== "boolean" ||
    (page.has_more &&
      (!page.next_cursor || typeof page.next_cursor !== "string"))
  )
    throw new Error("证据目录的包修订或摘要不一致，未采用其他范围。");
  for (const item of page.items) {
    const actual = memberships(view, item).sort();
    if (
      typeof item.id !== "string" ||
      !item.id ||
      !Number.isSafeInteger(item.physical_page) ||
      item.physical_page < 1 ||
      !Array.isArray(item.part_ids) ||
      !item.part_ids.length ||
      [...item.part_ids].sort().join("\0") !== actual.join("\0")
    )
      throw new Error("证据目录的文件、解析或逻辑页范围不一致。");
  }
}
