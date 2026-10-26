# 安全启动注入与权威费用状态

## 本阶段已实现

- `deploy/material_execution_worker.py --qualified-config` 提供明确的有界启动入口。只有可信宿主调用 `main(injected_host=Host(...))`，且配置 `enabled=true`，才装配现有 consumer；普通 CLI 没有注入宿主时拒绝。没有动态加载调用者提供的模块、环境凭据回退或创建访问权限。
- `material_worker_host` 的版本化配置只接受 account/profile UUID、固定方法摘要、已有原件读取 profile 和 1–1000 条消息上限。`--once` 要求上限为 1。配置文件读取有大小边界、拒绝重复键/符号链接/非普通文件。配置不能携带 DSN、key 或自称批准标记。
- 宿主显式提供七个用途独立的连接 context manager、consumer factory、凭据回调和原件 URL 回调。启动器检查连接独立且 IDLE，关闭全部资源；凭据只由原 sender 在取得原生授权之后按 account ID 获取。所有异常只返回固定错误码，不输出异常文本、DSN、key、私有 URL 或 send token。
- 调度方法摘要同时固定新 host 源码，漂移需重新封存 profile。逐消息仍复用原生材料恢复、资格/期限/撤销/profile/输入复验、预算预留和唯一 slot 发送；注入配置本身不等于授权。
- 在既有 qualification fresh-only SQL 中增加只读脱敏视图，从 acceptances、reservations、job_balances、attempts、outcomes 直接投影。API 仅有 view SELECT；没有直接暴露账本底表、原始响应或发送能力。SQL 仅编辑，未执行任何 GRANT 或安装操作。
- 新 GET `.../material-qualified-jobs/{intent_id}/execution-state` 在只读 repeatable-read 快照内先核对登录成员、确切范围和原申请，再读取视图。资格撤销/过期不隐藏历史账本；视图未安装时明确 unavailable，不制造零费用。
- 原任务 UI 接入刷新入口，独立显示任务接受、执行通道（隔离机制/获批发送）、执行状态、资格状态、预算预留/占用/释放、已知用量估算、未知费用及最近结算。最终账单始终未核对；估算不冒充发票，完成不冒充准确性。可重新读取在途请求迟到结算，不修改既有不可变 unknown outcome。
- 回执绑定成员、范围、申请、请求摘要与原生 job；选择切换/卸载后的迟到响应被丢弃。固定任务原幂等键与 ACK 恢复保持原机制。

## 运行边界

本次只编写配置/注入接口和模拟测试，不提供实际 Host 凭据实现，不读取/保存/配置真实 secret，不创建持久访问，不启动真实 consumer 或模型请求。真实宿主的连接与密钥来源由既有受控运行环境注入；这属于部署配置，当前任务不执行。模型名称沿用原配置，外部账户/能力/计费真实性仍未验收。

新增两个原生 opt-in 用例验证 view 的真实结算/撤销与 SELECT 边界；没有可用 PG17/S3 镜像，跳过不得记为通过。合成测试验证程序分支，不证明原生并发、真实质量或最终发票。

## 原需求核对

参照本地 tender-docs《一期方案与验证计划》4.1 的 FR-001–013、DEC-010/015/016，以及本分支 `remaining-code.md`：本轮登记的两项代码已接通。风险/复核、规则事实、报价、提交、结果/度量和研究消费者已有路由及历史阶段记录，不能据此宣称全用户流程验收。

发现须保留的一项原需求差异：FR-002 正式预测业务消费仍有硬关闭路径。`apps/api/review_views.py` 的 prediction.mode、`apps/api/scoring_routes.py` 的 numeric_prediction_available、`packages/model_governance/registry_contracts.py` 的 formal_eligibility 均保留 unavailable/false；`package_scoring_readiness.py` 的正式 `/executions` 仍始终拒绝。新增获批材料执行不是合格校准模型的业务预测发布。下一步应核对这些旧/新入口职责并接通已有权威准入后的模型/预测消费，不能只归类为缺真实数据，也不能删除拒绝或自创精度阈值。本轮不扩展该项。

主文档仍含旧 project 路径，与当前 bid/package 实现需协调；引用的实施任务板在本地文档 checkout 中不存在，未冒称已经完成全项目清单签收。

## 最终验证

- 后端完整默认回归：4355 passed、2424 skipped、0 failed/errors。新增原生 view 两项包含在 skip 中；没有当作通过。
- 新增后端定向：33 passed；此前联动 sender/dispatch/qualification 回归 105 passed、11 skipped。
- 前端最终全量：192 文件、1944 tests passed；format、lint（0 警告）、typecheck 与生产 build 通过。首轮卸载 ref 提示已修复，并新增切换离开后返回同一选择的迟到响应反例。
- 后端 ruff、format（1134 文件）、mypy（700 源文件）、bandit 通过。实际 OpenAPI 与前端路由契约已重新生成。
- 未运行：原生 PG17/S3/Kafka/真实账户模型组合验收、真实费用/准确性验收、生产部署。没有配置凭据、创建 PR、合并或修改运行权限。
