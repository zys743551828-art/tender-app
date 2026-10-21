import { lazy, Suspense, useState } from "react";
import type { PackageTechnicalScopePreview } from "./contracts";
import {
  technicalCategories as categories,
  technicalPartLabel,
} from "./packageTechnicalScopeLabels";

const OriginalEvidence = lazy(() => import("./PackageReviewEvidence"));
type Manifest = PackageTechnicalScopePreview["manifest"];
type Document = Manifest["documents"][number];
export function TechnicalPager({
  page,
  total,
  onPage,
  label,
}: {
  page: number;
  total: number;
  onPage: (value: number) => void;
  label: string;
}) {
  const pages = Math.max(1, Math.ceil(total / 20));
  return (
    <nav className="technical-scope__pager" aria-label={`${label}分页`}>
      <button
        type="button"
        disabled={page === 0}
        onClick={() => onPage(page - 1)}
      >
        上一页{label}
      </button>
      <span>
        {page + 1} / {pages} 页 · 共 {total} 项
      </span>
      <button
        type="button"
        disabled={page + 1 >= pages}
        onClick={() => onPage(page + 1)}
      >
        下一页{label}
      </button>
    </nav>
  );
}

function DocumentPages({
  document: d,
  bidId,
}: {
  document: Document;
  bidId: string;
}) {
  const [page, setPage] = useState(1),
    [blockPage, setBlockPage] = useState(0);
  const blocks = d.blocks.filter((block) => block.physical_page === page);
  const observation = d.pages.find((value) => value.physical_page === page);
  function selectPage(value: number) {
    if (!Number.isSafeInteger(value) || value < 1 || value > d.pages.length)
      return;
    setPage(value);
    setBlockPage(0);
  }
  if (d.parse.status !== "frozen")
    return <p>此文件尚未选定完整解析：{d.parse.reason}。</p>;
  return (
    <div className="technical-scope__pages">
      <p>
        完整记录 {d.pages.length} 个物理页、{d.blocks.length}{" "}
        个证据块。逐页展示原文与结构，图像完整性仍未证明。
      </p>
      <div className="technical-scope__pager">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => selectPage(page - 1)}
        >
          上一物理页
        </button>
        <label>
          物理页{" "}
          <input
            type="number"
            min={1}
            max={d.pages.length}
            value={page}
            onChange={(event) => selectPage(Number(event.target.value))}
          />
        </label>
        <span>共 {d.pages.length} 页</span>
        <button
          type="button"
          disabled={page >= d.pages.length}
          onClick={() => selectPage(page + 1)}
        >
          下一物理页
        </button>
      </div>
      {observation && (
        <p>
          本页读取状态：
          {observation.quality === "usable"
            ? "可用"
            : observation.quality === "partial"
              ? "有缺口"
              : "失败"}
          ；{observation.gaps.join("；") || "本页未记录解析缺口"}。
        </p>
      )}
      {!blocks.length && <p>本页没有已记录证据块，不能认定页面无内容。</p>}
      {blocks.slice(blockPage * 20, (blockPage + 1) * 20).map((block) => (
        <article key={block.id} className="technical-scope__block">
          <h6>
            {block.kind === "text"
              ? "原文"
              : block.kind === "table"
                ? "表格"
                : "图像观察"}{" "}
            · 物理页 {page}
          </h6>
          <p className="technical-scope__quote">
            {block.text_content || "本块没有文字记录"}
          </p>
          {block.structure_json && (
            <details>
              <summary>查看完整表格／图像结构</summary>
              <pre>{block.structure_json}</pre>
            </details>
          )}
          {d.parse.parse_run_id && (
            <Suspense fallback={<p role="status">正在加载原页入口…</p>}>
              <OriginalEvidence
                bidId={bidId}
                document={{
                  package_role: d.package_role,
                  member_id: d.member_id,
                  document_version_id: d.document_version_id,
                  parse_run_id: d.parse.parse_run_id,
                  file_digest: d.file_digest,
                  page_count: d.page_count ?? d.pages.length,
                  parts: [],
                  evidence_count: d.blocks.length,
                }}
                quote={{
                  member_id: d.member_id,
                  evidence_id: block.id,
                  quote: block.text_content,
                  package_role: d.package_role,
                  document_version_id: d.document_version_id,
                  parse_run_id: d.parse.parse_run_id,
                  physical_page: block.physical_page,
                  part_ids: [],
                  evidence_digest: block.digest,
                }}
              />
            </Suspense>
          )}
        </article>
      ))}
      {blocks.length > 20 && (
        <TechnicalPager
          page={blockPage}
          total={blocks.length}
          onPage={setBlockPage}
          label="证据块"
        />
      )}
    </div>
  );
}

export function PackageTechnicalScopeSnapshot({
  value,
  title,
}: {
  value: PackageTechnicalScopePreview;
  title: string;
}) {
  const m = value.manifest;
  const [partsPage, setPartsPage] = useState(0),
    [rulesPage, setRulesPage] = useState(0),
    [documentsPage, setDocumentsPage] = useState(0);
  const selectionNames = {
    include: "纳入本次范围",
    exclude: "明确排除",
    unclassified: "尚未归类",
  };
  return (
    <section className="technical-scope__snapshot" aria-label={title}>
      <h4>{title}</h4>
      <p>
        已选 {m.coverage.selected_part_count} / {m.coverage.all_part_count}{" "}
        个页段，纳入 {m.coverage.included_rule_count} /{" "}
        {m.coverage.all_scoring_rule_count} 项评分条款。
      </p>
      <p className="notice">
        当前覆盖：{m.coverage.state === "partial" ? "部分" : "未知"}
        。本记录用于核对评分输入，尚不能生成正式评分或用于训练。
      </p>
      <h5>本次缺口</h5>
      <ul>
        {m.coverage.gaps.map((gap) => (
          <li key={gap.id}>{gap.message}</li>
        ))}
      </ul>
      <details>
        <summary>查看全部页段及选择（{m.parts.length}）</summary>
        {m.parts.slice(partsPage * 20, (partsPage + 1) * 20).map((entry) => (
          <p key={entry.part.part_id}>
            {entry.selected ? "已选" : "未选"} ·{" "}
            {technicalPartLabel(
              entry.part,
              m.documents
                .filter((d) => d.package_role === "target")
                .findIndex((d) => d.member_id === entry.member_id),
            )}{" "}
            · 读到 {entry.read_physical_pages.length} 页、
            {entry.block_ids.length} 个证据块
          </p>
        ))}
        <TechnicalPager
          page={partsPage}
          total={m.parts.length}
          onPage={setPartsPage}
          label="范围"
        />
      </details>
      <details>
        <summary>查看全部评分条款选择（{m.rules.length}）</summary>
        {m.rules
          .slice(rulesPage * 20, (rulesPage + 1) * 20)
          .map((rule, index) => (
            <article key={rule.rule_id} className="technical-scope__block">
              <h5>
                条款 {rulesPage * 20 + index + 1} ·{" "}
                {selectionNames[rule.selection]}
              </h5>
              <p>
                {typeof rule.rule_snapshot.statement === "string"
                  ? rule.rule_snapshot.statement
                  : "原条款文字未记录"}
              </p>
              <p>选择理由：{rule.reason}</p>
              <p>
                关联页段：
                {rule.part_ids
                  .map((id) => {
                    const entry = m.parts.find((p) => p.part.part_id === id);
                    return entry
                      ? `${categories[entry.part.category] ?? entry.part.category} · ${entry.part.first_page}—${entry.part.last_page} 页`
                      : id;
                  })
                  .join("；") || "未关联"}
              </p>
              {rule.source_evidence.map((ref) => (
                <blockquote key={ref.evidence_id}>
                  原页 {ref.physical_page}：{ref.text_content}
                </blockquote>
              ))}
            </article>
          ))}
        <TechnicalPager
          page={rulesPage}
          total={m.rules.length}
          onPage={setRulesPage}
          label="条款"
        />
      </details>
      <details>
        <summary>
          逐页查阅完整记录的原文、表格和图像观察（{m.documents.length} 个文件）
        </summary>
        {m.documents
          .slice(documentsPage * 20, (documentsPage + 1) * 20)
          .map((document, index) => (
            <details key={`${document.package_role}:${document.member_id}`}>
              <summary>
                {document.package_role === "target" ? "投标资料" : "招标依据"} ·
                文件 {documentsPage * 20 + index + 1} ·{" "}
                {document.page_count ?? "未知"} 页
              </summary>
              <DocumentPages document={document} bidId={m.scope.bid_id} />
            </details>
          ))}
        <TechnicalPager
          page={documentsPage}
          total={m.documents.length}
          onPage={setDocumentsPage}
          label="文件"
        />
      </details>
      <details>
        <summary>范围版本与完整输入摘要</summary>
        <p>包修订：{m.scope.revision_id}</p>
        <p>要求清单：{m.scope.inventory_id}</p>
        <p>预览摘要：{value.digest}</p>
        <p>方法摘要：{m.method.digest}</p>
      </details>
    </section>
  );
}
