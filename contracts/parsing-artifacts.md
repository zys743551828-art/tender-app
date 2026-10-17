# 解析产物

解析任务的 `parse-v1` JSON 绑定 `file_version_id`、原件 `source_sha256` 与 `parser_version`。`pdfium-1.2` 提供原生文字提取和图片对象检查，不包含 OCR、表格结构或图形语义识别。

现有 `page_count`、`coverage`、`gaps`、`chunk_count`、`page_text_chars` 保留。增加 `coverage_scope=native_text_and_raster_presence` 和 `pages`；没有这些字段的旧产物按其原解析版本解释，不能推断为新的覆盖检查已执行。无需数据库迁移或 API 字段变化。

`pages` 按物理页排序，每页一项：

| 字段 | 含义 |
| --- | --- |
| `physical_page` | 原件中从 1 起的物理页 |
| `text_layer` | `extracted`、`empty` 或 `failed`；只描述文字层读取 |
| `text_chars` | 去掉页首尾空白后的字符数，保留页码字符，不作为业务完整性证据 |
| `raster_images` | 检查到的图片对象数，尚未检查时为 null；Form 对象递归检查深度为 15 |
| `issues` | 本页机器可读的未覆盖原因 |
| `table_structure` | 当前固定 `not_evaluated` |
| `figure_semantics` | 当前固定 `not_evaluated` |

原因包括 `raster_images_unread`、`no_text_layer`、`rotated_no_bbox` 和 `page_read_failed`，文档 `gaps` 对每项附加 `page_N:` 前缀。图片对象即使伴有标题或长段文字也保留未覆盖标记，不推断它是正文、照片还是装饰背景，因此装饰背景可能使覆盖为 partial。矢量图、表格关系和深层 Form 的完整检查范围外；零张图片不证明没有图表。旋转页保留文字，证据坐标为 null。

单页 PDFium 读取错误保留失败页并继续其余页。无证据时文档为 failed，处理器仍返回已有 `parse_unreadable` 任务失败；有证据且任一页有缺口时为 partial。complete 只表示本解析版本的文字层和图片存在性检查没有发现缺口，不代表表格或图意已理解。

页级清单随不可变的解析产物保存。数据库缺口、快照的 `coverage_gaps` 继续使用相同原因；原有租约、原件校验、证据所属版本和物理页身份不变。旧解析与快照保持原记录，重新解析生成新记录，不追写历史覆盖结论。
