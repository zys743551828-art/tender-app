# 表格结构与可能续表候选

`pdfium-1.4` 的识别产物在启用本地识别时包含 `table_structures`，schema 为 `table-candidates-1`，固定 `review=pending`。没有此字段的旧解析返回未执行，不推断历史上已检查结构。

原生表保留引擎的单元格数组、表范围及行列边界。扫描表只对已选 OCR 页中近水平／垂直、至少两行两列的清晰网格生成候选，使用已有 OpenCV 提取长横／竖线；不引入远程模型或新下载。每页至多 20 表、1,000 行、100 列，仍受原有页数、像素、消息大小、超时与租约限制。无候选不证明无表，斜表、无线表、合并格和图形语义未验收。

表项绑定 `table_id=table_<物理页>_<页内索引>`、`physical_page`、归一化 `bbox`、`source=native_table/raster_grid` 和原始 `rows`。扫描网格另存完整 `column_boundaries`、`row_boundaries`、逐格 `cell_line_indices` 及 `unassigned_line_indices`，行编号从该页原始 `lines` 的 0 开始。OCR 行只有完整落在一个单元格时才填入；跨格或边界歧义不拆字、不猜位置，记录问题并保留原 OCR 候选。空格表示未识别，不证明原件为空。格内多行依原坐标排序，以换行连接；结构归属不产生新识别置信度。

网格行作为 `kind=table,source=raster_grid` 的待核验摘录，仍保留逐行 OCR 证据；全空行不产生只有分隔符的伪证据。未核验非 text 继续排除在业务模型之外，核验仅确认所选摘录，不确认整张结构。文档保留 `table_structure_not_verified`，可能续表保留 `cross_page_tables_not_verified`，人工摘录确认不清除这些缺口。

`cross_page_candidates` 只列同文件相邻物理页的候选对：前表靠近页底（底边至少 0.75）、后表靠近页首（顶边至多 0.25），两侧表头去空白后逐格相同且至少两格非空，左右范围及所有列边界差异至多 0.02。任一列边界未知、列数或表头不同则不产生提示。每对保存两个 table ID、页码、明确触发原因及 pending；不拼接行、不去重复表头、不生成跨页事实或修改证据原页。相邻重复表头也可能是两个独立表，必须对照原件判断。

`GET /files/{version_id}/table-structures?table_index=0&row_offset=0&expected_parse_id=<ID>` 沿用会话与原件访问校验，先核对当前解析产物 SHA。返回当前 `parse_id`、`state=not_evaluated/candidate_preview`、表数、单表原页／来源／边界、总行数、每次最多 20 行、对应行引用及相关可能续表。超出表／行索引返回空预览，负数返回 422；预期解析变化返回 409 `recognition_parse_stale`，产物校验失败返回 409 `recognition_artifact_corrupt`。

原件页“核验候选”内可按需打开结构预览，逐表／逐组行查看并链接两侧原页。此接口不执行 OCR 或写入审核，未确认的结构始终标候选。摘录核验后新解析保留原始结构内容，界面明确说明它不会随摘录订正改写；原产物、原证据、旧快照与旧报告均保持。当前结构预览只读当前解析，不用于历史报告重放。
