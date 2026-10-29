# 统一应用固定候选

执行入口是 `runtime-preview-01`。`recipe-01.json` 列明七个受审输入、每个文件的唯一选择及顺序；`source-preview-01.json` 固定最终399份运行源码。不得从移动工作目录补文件，不能把运行缓存或私有配置加入运行源清单。

挂载包括 Word 主流程、TaskDraft05、生命周期、模型训练评估 StageA、历史依据与主体 HIST02、HistoricalInput01、模型登记 release01、完整评分软件 Score01。Word 基线的 API/Worker/生命周期与任务输入守卫保留。七个模型治理公共文件采用各模块共同认可的 Score01 固定引用。新 A2、TechnicalScale、RICH 不在本次范围。

实际契约为 `actual-01.openapi.json`：209路径、239操作、375 Schema。47个新增操作均有具体JSON成功响应定义。原Word基线315个Schema完整保留；17个声明response_model的操作按序列化展开后与最终定义一致。222个未声明response_model的操作逐条列于 `contract-registration-check-01.json`：这些由独立人工契约投影描述，本次仅对选定真实ASGI返回对象校验，不能称每个输出都受自动响应模型校验。

## 验证

使用新17SQL数据库，SQL路径、完整SHA与初始化顺序见recipe的 `ordered_fresh_sql`。实际初始化由项目经理完成，凭据仅在私有profile；本片没有执行DDL、启动消费者、请求云模型或对象服务，也没有改动运行中的API。

200项相关纯机制/契约回归通过，包含6项组合静态检查；另4项真实非owner PG/全应用ASGI检查通过：

- 五组能力的登录、真实配置与输出Schema，付费/正式资格始终不可用；
- 任务草案与编辑器草稿分离、旧ACK重放、终止/归档的普通新写拒绝；未完成批次须显式保留暂存结束；
- 归档后的历史待核验主体及历史输入上下文允许专用访问，身份保持未知，不重新打开项目；
- StageA协议登记、读取、幂等重放和客户端资格注入拒绝，不启动训练或模型执行。

ruff、format、生产mypy、测试mypy（follow-imports=silent，未外推既有测试文件类型质量）及生产bandit通过。测试后数据库model_calls/operations/outbox均为0。首次PG命令漏显式启用测试，仅3skip，保留integration-01.xml；有效结果为integration-02、integration-03及pure-regression-01。现有模块独立评审证据仍只覆盖各自范围，不能推定本片完成业务精度、全链Kafka或正式评分验收。

在固定运行根执行测试，使用工程的独立venv及项目经理提供的 `.local/app_composition01-runtime.env`。通过 `deploy/run.py --env-file` 加载，只设置 `RUN_APPLICATION_COMPOSITION=1`；不要加载初始化owner profile。Python stdin或外部脚本入口应显式设置PYTHONPATH为固定根，避免回退到移动目录。纯机制回归与完整命令在JUnit结果和候选记录中留证。

## 后续集成

本片不新增普通Worker处理器，也不提供付费执行入口。完整评分保持独立用途端口；关闭项目的当前评审评分仍由领域守卫约束，历史输入必须通过独立资格链。未来新运行环境须按精确SQL和隔离Kafka重新部署，由项目经理集中组织，不对现有运行库补丁或共用消费者。
