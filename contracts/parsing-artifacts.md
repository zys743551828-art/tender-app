# 解析产物

解析任务的 `parse-v1` JSON 绑定 `file_version_id`、原件 `source_sha256` 与 `parser_version`。`pdfium-1.3` 提供原生文字提取和图片对象检查；启用本地识别时，增加 OCR 和原生表格的待核验候选，不执行图形语义理解。读取对象存储字节后复核原件哈希，不符时任务以 `parse_source_mismatch` 失败。

现有 `page_count`、`coverage`、`gaps`、`chunk_count`、`page_text_chars` 保留。`coverage_scope=native_text_and_raster_presence` 和 `pages` 记录原生检查；`enrichment` 与 `candidate_evidence` 记录识别候选。没有这些字段的旧产物按其原解析版本解释，不能推断相应检查已执行。无需数据库迁移或 API 字段变化。

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

## 本地识别候选

`enrichment` 的 `schema=local-enrichment-1`，包含 `source_sha256`、`selected_pages`、`skipped_pages`、`unfinished_pages`、`failure`、逐页 `pages`、模型文件 SHA-256 和执行耗时。`review=pending`，坐标空间为 `rendered_page_normalized`；原件按 2 倍渲染，`render_sha256` 对 RGB 像素计算，`render_size` 保存像素宽高。

每页保存 OCR 状态 `not_needed/recognized_pending/empty/failed/unavailable/limited`，以及表格状态 `extracted_pending/none_detected/failed/limited`。OCR 行保存原始文字、置信度、归一化范围；表格保存原生单元格数组（空单元格按引擎输出保留 null 或空串）、表范围和引擎版本。未检测到表格不证明原页没有表格，扫描表只可能产生 OCR 行。跨页关系不自动猜测。行、表、渲染像素和消息大小均有限制，超限明确保留状态。

`retrieval_index` 记录本次解析的派生向量状态：`disabled/ready/unavailable`。启用 pgvector 时，本地向量按 32 条一批生成并续租，丢失租约不提交；向量与新证据在同一结果事务写入。`ready` 附模型指纹、块数和截断数；编码不可用保留文字解析，附错误码。此状态不证明识别结果已经核验，不改变证据的 `semantic_review`。

`candidate_evidence` 按实际写入证据的 `seq` 关联，保留 `physical_page`、`quote`、`bbox`、`kind`、`source`、`confidence` 和 `numeric_review_required`。OCR 为 `visual_observation/ocr`，原生表格行为 `table/native_table`，两者的 `semantic_review` 均为 pending。出现数字、百分号或千分号时要求数字核验；置信度不等于正确率。原始行／表数组完整留在 `enrichment.pages`，长候选按 400 字分块，范围仍是整行或整表，不冒充字符级坐标。

待核验候选可从现有项目检索和证据读取接口查看，但规则提取、诊断、评分及按 ID 加载证据只允许原生 text 或已受支持核验的证据。不能因 OCR 内容匹配就自动改成 text 或 supported。原页图片缺口、表格／图意未评价标记继续保留。纯识别候选的输入增加 `recognition_verification_required`，阻止自动评审，可在原件页逐项核验或补交可复制文字的 PDF；候选及其原页引用仍可查询。追加核验、订正与身份映射遵循[候选核验契约](recognition-reviews.md)，不改写本次原解析产物。

识别在子进程中运行，不继承业务凭据。默认按图片存在性、文字稀疏程度与物理页优先选择最多 32 页，剩余页明列跳过。每页 45 秒、整份 180 秒；父进程每 0.25 秒检查租约，超时、无效输出或丢租约即终止子进程，已完成页可以保留；丢租约向运行器抛出，不提交旧结果。进程缺失、依赖／模型不可用和模型哈希不符均有明确原因；网络下载不在运行路径中，模型须预先提供。

开关与限额来自 `Settings.parse_enrichment_*`，默认关闭；`parse_model_dir` 指向已核对的三个 RapidOCR ONNX 文件。本机 `compose.local-oss.yml` 启用并只读挂载研究侧已有 D 盘模型，镜像安装 `parsing` 可选依赖。生产基础编排保持默认关闭，启用前需部署相同模型及资源限额。候选处理不表示实际扫描件、表格或评分质量验收通过。
