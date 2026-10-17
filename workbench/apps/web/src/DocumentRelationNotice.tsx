import type { DocumentView } from "./contracts";
export function DocumentRelationNotice({
  document,
}: {
  document: Pick<DocumentView, "bid_id" | "source_relation">;
}) {
  const relation = document.source_relation;
  if (!relation) return null;
  return (
    <div className="notice warning">
      <p>
        {relation.kind === "controlled_render"
          ? "此PDF由指定Word原件受控转换。"
          : "此PDF由用户声明对应指定Word修改稿，与Word分别保存。"}
        {relation.verification === "verified"
          ? "对应关系已核验；这不代表Word对应检查或评审已通过。"
          : relation.verification === "rejected"
            ? "对应关系核验未通过，不能承接原件检查资格。"
            : "对应关系尚未核验，不能承接Word检查资格。"}
      </p>
      <a
        href={`/bids/${document.bid_id}/materials#word-original-${relation.source_document_version_id}`}
      >
        查看对应Word原件与转换状态
      </a>
    </div>
  );
}
