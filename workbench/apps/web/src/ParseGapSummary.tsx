import { Fragment } from "react";

const explanations: Record<string, string> = {
  TEXT_VISUAL_COMPOSITION_UNVERIFIED:
    "文字的颜色、描边或叠放关系尚未验证；已改用原页渲染识别，请对照原页核查。",
  SCAN_LAYOUT_TABLES_AND_VISUALS_UNVERIFIED:
    "OCR 已尝试识别文字，但表格结构、图示和版式含义尚未验证。",
  OCR_LOW_CONFIDENCE:
    "部分 OCR 文字置信度偏低，请逐项核对数字、单位和关键术语。",
  DOCUMENT_PARSE_TIME_LIMIT:
    "达到本次解析时限，此页尚未读取，不能据此判断内容缺失。",
  PAGE_PARSE_FAILED: "此页解析失败，尚无可靠解析结果，请查看原页。",
  OCR_NO_TEXT_NONBLANK_PAGE:
    "页面并非空白，但 OCR 未提取到文字，请查看原页；不能视为没有内容。",
};

export function ParseGapSummary({
  pages,
}: {
  pages: { physical_page: number; gaps: string[] }[];
}) {
  const byCode = new Map<string, Set<number>>();
  for (const page of pages)
    for (const code of page.gaps) {
      if (!byCode.has(code)) byCode.set(code, new Set());
      byCode.get(code)!.add(page.physical_page);
    }
  if (!byCode.size) return null;
  return (
    <details>
      <summary>查看缺口原因与核查建议</summary>
      <p>
        缺口不等于整页未读，也不等于原件缺少内容。以下说明不改变部分覆盖或正式资格。
      </p>
      <dl>
        {[...byCode].map(([code, numbers]) => (
          <Fragment key={code}>
            <dt>
              {explanations[code] ?? "尚未验证的解析缺口，请对照原页核查。"}
            </dt>
            <dd>
              物理页 {[...numbers].sort((a, b) => a - b).join("、")}；代码{" "}
              <code>{code}</code>
            </dd>
          </Fragment>
        ))}
      </dl>
    </details>
  );
}
