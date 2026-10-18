# 证据检索与派生索引

`POST /projects/{project_id}/search` 为只读请求。先确认项目存在，再选当前已提交文件版本或冻结快照的版本。当前资料排除 `official_result`；冻结快照沿用创建时允许的文件范围。候选 OCR／表格可供人工查询，但检索不改变核验状态，业务模型仍排除未核验非 text 证据。

默认 `keyword`：中文二元组与完整英数词 BM25，按输入顺序稳定处理同分。可选 `pgvector`：对同一允许范围计算 BM25、编号数字精确匹配、向量余弦三路排序，每路取 50，RRF offset=60，重复证据每路只计一次，同分按输入顺序。精确通道执行 NFKC，完整比较编号、数值及 `%/‰`，保留小数精度；它不证明数值正确。

向量模型固定 BAAI/bge-small-zh-v1.5，512 维、CLS、L2 归一化、最大 512 词元，查询前缀“为这个句子生成表示以用于检索相关文章：”，正文无前缀。ONNX 和 tokenizer SHA-256 在 `bidwb/embeddings.py` 固定；指纹包含两文件摘要、模型名、维数、长度、前缀、池化和归一化方式。运行时只读本地文件，拒绝摘要不符和非有限／非单位向量，不加载远程代码。

向量表见 [evidence-embeddings.sql](evidence-embeddings.sql)，是迁移 0002 的增量契约；[schema.sql](schema.sql) 对应初始迁移 0001。`REAL[]` 保存可重建向量，纯 PostgreSQL 可以迁移并使用关键词；启用通道后用 pgvector `vector(512)` 转换与 `<=>` 距离。SQL 先物化项目、模型指纹和允许证据 ID，再精确计算距离，当前无 ANN／HNSW 索引。不以小集结果推断大库性能。

新解析启用 pgvector 时逐批编码，续租检查之间每批至多 32 条；向量与证据在同一最终事务写入。编码失败不丢弃文字解析；丢失租约不提交。已有证据通过具备 worker 凭据的 `bidwb-admin rebuild-vectors --project <ID>` 回填；分批提交可重跑。索引保存逐块文字摘要、截断标记、模型指纹和项目 ID，复合外键阻止跨项目挂接。API 只读索引。

请求指定 hybrid 且通道配置 pgvector 时，只有允许范围的全部证据都具备匹配指纹及文字摘要才使用混合通道。模型／扩展缺失、索引缺块、旧模型、文字摘要不符、SQL 或推理失败，返回 `mode_used=keyword,index_state=unavailable` 及明确缺口。索引 SQL 置于 savepoint，错误不破坏外层只读事务。成功返回 `mode_used=hybrid,index_state=ready,channel=fused`；查询或证据向量截断时在 gaps 声明。分数是排序融合分数，不能解释为准确率、置信度或工程事实。

默认启用须同时验证检索质量、项目／版本范围、降级恢复和目标规模性能。开发参考结果见研究仓库 `results/hybrid-retrieval-1/`；这组已知答案回归存在页码召回退化，当前不切换默认，也不移除 Milvus 部署定义。
