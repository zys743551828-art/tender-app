# 全后端回归与环境边界

## 结论

最终后端源树已完成一次完整测试：**1,747 项通过、1,181 项跳过、0 失败、0 error**。共享编写来源守卫、Worker 新阶段、新接口及本轮解析兼容修复均包含在此次执行中。此前 6 项恢复协议失败所需的真实历史归档已找到，全部原始摘要核验通过；这 6 项既单独通过，也包含在最终完整执行中。

本次全量环境没有提供数据库地址、模型密钥或付费执行开关。真实数据库、解析 HTTP 到 PostgreSQL 及运输测试由各自集成记录单独说明；环境门控的跳过项保留其验收边界。

## 实际结果

| 验证                                                | 实际结果                                                                                                                              |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| 最终完整 `pytest -q --tb=short -p no:cacheprovider` | **1,747 通过、1,181 跳过、0 失败、0 error，50.13 秒**；进程退出码 0                                                                   |
| 最终执行的源码稳定性                                | 执行前后 3,874 个选定的 Python、SQL、TOML 及契约文件摘要相同，工作区源码未在测试中途变化                                              |
| 六项恢复协议及初始化回归                            | 原摘要核验后单独执行 **6 项通过，1.55 秒**；之后纳入上述完整执行                                                                      |
| 此前完整执行，保留历史结果                          | 1,739 通过、1,175 跳过、7 失败、0 error，53.12 秒；当时含 6 项归档缺失及 1 项报告测试旧夹具失败                                       |
| 此前报告目录回归的定向复核                          | 夹具改用合法的 `[1, 2, 11]` 后，同名测试定向 1 项通过；最终完整执行再次覆盖                                                           |
| 本地实际解析器补充验证                              | `test_parsing_local.py` 与 `test_parsing_http.py`：16 项通过，3.75 秒；使用真实 PDFium、pdfplumber、Tesseract 和固定官方字典          |
| 解析证据类型修复后的定向复核                        | 35 项通过、6 项因真实 PG 显式门未开启而跳过，3.62 秒；真实 HTTP 到 PG 的 6 项另行实际通过，见 `configured-local-parser-acceptance.md` |
| 实际报告及编写转换                                  | 报告、字体及既有正文真实转换共 17 项通过；逐页视觉结果详见 `report-render-acceptance.md`                                              |

最终完整执行是在解析实施方明确冻结源码和测试之后启动的单次进程。起始 Git HEAD 为 `5838089ba1922ba815a65396b2035c11194c3abb`，工作区同时包含最终的解析证据类型修复和新增回归测试；执行前后选定文件的路径到 SHA-256 映射摘要均为 `a87c3b9aa281e2f8d34c385f0df6cbbd7257171a0a6105dde2c5169ab8af22ed`。因此上表首行是同一份稳定源码的一次完整结果，历史执行和定向复核仍分别记录。

## 本轮检出的回归

1. 要求清单子应用的 OpenAPI 测试仍硬编码旧操作集合。新增核查、人工意见和报告的 11 个操作确实注册在该路由树下；期望集合已扩展，仍使用严格相等检查，相关契约及装配 12 项通过。
2. 实际 PostgreSQL 报告导出发现分册的数字目录路径被直接传给字符串 `join`。报告现在明确将每个合法目录序号转换为文字，保留完整路径；增加了 `test_report_preserves_numeric_heading_paths_from_frozen_package_documents` 回归。其 PG 集成结果由统一集成检查点记录。
3. 配置本地解析服务的真实 HTTP 到 PostgreSQL 检查发现，启发式章节识别把证据块改成 `heading`，与已有 `text/table/visual_observation` 协议不一致。解析器现在保留原证据类型，并将推断章节留在 `chapter_path` 和 `inferred` 元数据中；新增回归同时检查普通标题文字与带编号表格，真实 HTTP 集成及最终完整后端执行均通过。

## 六项旧恢复协议测试：真实归档已恢复并通过

以下 5 项需要固定归档 `application-recovery-development-checks/protocol-02/baseline-inputs.json`：

- `test_exact_reviewed_308_and_15_inputs`
- `test_preloaded_live_provider_cannot_be_rebound_by_path_order`
- `test_namespace_cannot_append_a_second_search_root`
- `test_missing_frozen_module_never_falls_through_to_live`
- `test_real_fixed_main_knowledge_and_provider_import_in_clean_child`

第 6 项 `test_seed_covers_current_required_columns_and_records_all_keys_before_put` 需要 `historical-input-initialization-checks/candidate02/sql-inputs/packages/contracts/sql/domain.sql`。

这些测试使用 `/workspace/tender-docs/04-验证与测试/` 下的原归档。最初的 `fusion/bid-workbench` 检出未包含它们；继续核查用户公开仓库的完整历史和其他分支后，在 `handoff/2026-10-17` 分支找到真实归档引入提交 [b0425e8a10ae8e08b099556b6f1183062562ce75](https://github.com/zys743551828-art/tender-docs/commit/b0425e8a10ae8e08b099556b6f1183062562ce75)，提交说明为 `chore: archive complete project handoff checkpoint 2026-10-17`。

恢复核验共覆盖 **327 项**：308 个后端冻结文件、15 份 SQL，以及 baseline、runtime manifest、SQL 计划和前序冻结交接记录。**326 项从上述真实 Git 提交提取，全部匹配原 SHA-256**。唯一没有进入 Git 树的文件是 `apps/web/node_modules/flatted/python/flatted.py`。该第三方依赖从 [npm 官方发布的 flatted 3.4.4 tarball](https://registry.npmjs.org/flatted/-/flatted-3.4.4.tgz) 获取，先核对锁文件的 SHA-512 SRI，再核对冻结 manifest 的 SHA-256；3,773 字节逐字节匹配。

| 固定输入                                                   | 已核验 SHA-256                                                     |
| ---------------------------------------------------------- | ------------------------------------------------------------------ |
| `protocol-02/baseline-inputs.json`                         | `76dc6abed9ae344dbf755a3c0d237e68f3a420b042fac6193debe2e16116f38f` |
| `backend07-independent-checks/runtime-manifest.json`       | `71fe0fb2c9dbde7d85e62d20bef2da8e188e59ac00e9eb056cc021a1bd75274e` |
| `candidate02/sql-inputs/packages/contracts/sql/domain.sql` | `b279c9b1c3477feeb28eaa5f6a45adb4493585a1d112d7d7a637cefac1404d96` |
| `flatted/python/flatted.py`                                | `f784c254de76a25435ebaa61c72942072733ae4b42619b943bf37b09fa45e644` |

flatted tarball 的 SHA-512 SRI 为 `sha512-5+ybhBZANEJxaH3X5evAFatUxLfEHSr7n6kYJ+1Qd0mUqr4eu9gIf6GDbWHf8RJijHrjjO8G+la14SlL2SeS1Q==`。

核验后的归档保存在独立临时目录，通过临时挂载命名空间只读提供给 `/workspace/tender-docs`。执行前确认宿主不存在该路径，执行后再次确认；归档未放入应用源码树。恢复实现、6 项测试和它们的固定摘要均保持原样。单独 6 项及之后完整后端均实际执行成功；这证明冻结输入校验和相关模块绑定行为通过，不等于已对生产数据库执行恢复。

## 执行环境与可复核设置

测试子进程使用最小环境，只传入 `PATH`、locale、`WORKBENCH_ENV_FILE=review-readonly`、`PYTHONDONTWRITEBYTECODE=1` 和以下两项明确夹具路径：

- `AUTHORING_GENERATED_BASE_PROFILE_FIXTURE` 指向仓库 `docs/word-mainflow-development-checks/renderer-profile-02.json`。
- `PARSING_TEST_FONT_PATH` 指向已固定摘要的 Noto Sans CJK SC 字体。测试保留原系统字体默认路径，部署在其他环境时可以明确指定合成样本使用的字体。

子进程不继承数据库 DSN、模型密钥或付费执行开关。最终 1,181 项跳过保留其原环境门，不能据此声称数据库、真实模型或生产恢复已经验收。新增的 6 项解析 HTTP 到 PostgreSQL 测试也由显式环境开关控制；其真实执行结果另列在解析集成记录中。

OCR 资产由仓库现有 `packages.parsing.fetch_assets` 安装程序获取，逐份核对 `packages/parsing/assets.json` 中固定的官方提交、字节长度与 SHA-256。资产没有进入 Git；生产解析身份和完整性校验没有放宽。扫描、图形及不可见文字等用例继续保留实际的部分覆盖限制。

受限执行沙箱曾使最小 FastAPI `TestClient` 在 AnyIO 线程唤醒处停滞：同一个无业务代码、无凭据的小程序在受限沙箱 20 秒超时，允许本地 socket 的隔离执行环境中约 0.2 秒返回预期 404。完整回归在后者执行。单例超时及中断的两次探测不计为完成的全量结果。

本次执行证据保存在临时运行目录：`full-backend-final.log`、`full-backend-final-result.json`、`recovery-archive-six.log` 及 `recovery-archive-discovery/verification.json`。完整日志和结果 JSON 记录了退出码 0、真实统计和前后源码摘要；逐文件归档记录提供全部 327 项的期望摘要、实际摘要及来源。最终测试完成后，读取日志的执行服务短暂断连；恢复后读取到完整落盘结果，未据中断的日志读取推断测试状态。

本次结果验证软件行为及合成文件处理；没有形成真实标书准确率、正式评分或可提交性证明。
