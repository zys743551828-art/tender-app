# 全后端回归与环境边界

## 结论

完整后端测试已执行。共享编写来源守卫、Worker 新阶段及新接口的本轮回归已修复并定向复核；仍有 6 项旧恢复协议测试因为缺少确切历史归档而失败，不能记为全套通过。真实数据库及运输测试由各自集成记录单独说明，本次全量环境没有提供数据库地址。

## 实际结果

| 验证 | 实际结果 |
| --- | --- |
| 最终完整 `pytest -q --tb=short` | 1,739 通过、1,175 跳过、7 失败、0 error，53.12 秒 |
| 上述失败中的新增报告目录回归 | 当次进程已加载的旧测试夹具含不符合协议的目录值；集成检查随后改用合法的 `[1, 2, 11]`，同名测试定向 1 项通过 |
| 本地实际解析器补充验证 | `test_parsing_local.py` 与 `test_parsing_http.py`：16 项通过，3.75 秒；使用真实 PDFium、pdfplumber、Tesseract 和固定官方字典 |
| 实际报告及编写转换 | 报告、字体及既有正文真实转换共 17 项通过；逐页视觉结果详见 `report-render-acceptance.md` |
| 当前未解决的旧归档依赖 | 6 项失败，见下节；没有将它们改为跳过或通过 |

完整测试期间其他实施工作仍在进行，因此上述完整进程的统计和其后定向复核分别记录，没有把多次执行拼成一次“全绿”结果。

## 本轮检出的回归

1. 要求清单子应用的 OpenAPI 测试仍硬编码旧操作集合。新增核查、人工意见和报告的 11 个操作确实注册在该路由树下；期望集合已扩展，仍使用严格相等检查，相关契约及装配 12 项通过。
2. 实际 PostgreSQL 报告导出发现分册的数字目录路径被直接传给字符串 `join`。报告现在明确将每个合法目录序号转换为文字，保留完整路径；增加了 `test_report_preserves_numeric_heading_paths_from_frozen_package_documents` 回归。其 PG 集成结果由统一集成检查点记录。

## 六项旧恢复协议测试的外部依赖

以下 5 项需要固定归档 `application-recovery-development-checks/protocol-02/baseline-inputs.json`：

- `test_exact_reviewed_308_and_15_inputs`
- `test_preloaded_live_provider_cannot_be_rebound_by_path_order`
- `test_namespace_cannot_append_a_second_search_root`
- `test_missing_frozen_module_never_falls_through_to_live`
- `test_real_fixed_main_knowledge_and_provider_import_in_clean_child`

第 6 项 `test_seed_covers_current_required_columns_and_records_all_keys_before_put` 需要 `historical-input-initialization-checks/candidate02/sql-inputs/packages/contracts/sql/domain.sql`。

这些测试使用 `/workspace/tender-docs/04-验证与测试/` 下的原归档。本地现有 `tender-docs` 检出未包含这些文件。恢复协议还核验固定归档摘要、308 个后端冻结文件及 15 份 SQL；当前源码不能替代该归档。相关恢复实现与这 6 个测试在本轮未改动。需要取得真实归档后再完成对应恢复验证。

## 执行环境与可复核设置

测试子进程使用最小环境，只传入 `PATH`、locale、`WORKBENCH_ENV_FILE=review-readonly`、`PYTHONDONTWRITEBYTECODE=1` 和以下两项明确夹具路径：

- `AUTHORING_GENERATED_BASE_PROFILE_FIXTURE` 指向仓库 `docs/word-mainflow-development-checks/renderer-profile-02.json`。
- `PARSING_TEST_FONT_PATH` 指向已固定摘要的 Noto Sans CJK SC 字体。测试保留原系统字体默认路径，部署在其他环境时可以明确指定合成样本使用的字体。

子进程不继承数据库 DSN、模型密钥或付费执行开关。1,175 项跳过保留其原环境门，不能据此声称数据库、真实模型或生产恢复已经验收。

OCR 资产由仓库现有 `packages.parsing.fetch_assets` 安装程序获取，逐份核对 `packages/parsing/assets.json` 中固定的官方提交、字节长度与 SHA-256。资产没有进入 Git；生产解析身份和完整性校验没有放宽。扫描、图形及不可见文字等用例继续保留实际的部分覆盖限制。

受限执行沙箱曾使最小 FastAPI `TestClient` 在 AnyIO 线程唤醒处停滞：同一个无业务代码、无凭据的小程序在受限沙箱 20 秒超时，允许本地 socket 的隔离执行环境中约 0.2 秒返回预期 404。完整回归在后者执行。单例超时及中断的两次探测不计为完成的全量结果。

本次结果验证软件行为及合成文件处理；没有形成真实标书准确率、正式评分或可提交性证明。
