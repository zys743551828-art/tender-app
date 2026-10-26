# ADR-001：按材料任务业务切片隔离应用编排

状态：已实现，行为保持；不涉及正式模型准入决策。基线 `7fe86b6`，参考用户提供的 Python 后端架构建议摘要。没有更换语言、SQL/Kafka 或框架。

## 有限审查结论

1. `apps/api/package_technical_execution.py` 的获批材料申请/恢复/读取/费用观察直接操作事务、资格守卫和原生提交。事务与 HTTP 绑定，测试靠替换模块全局连接与提交函数，正确的“提交后外部 I/O”顺序缺少独立应用端口约束。本轮处理此项。
2. `apps/api/model_registry_routes.py` 的模型登记/read/change route 也直接编排“短 SQL → 对象 I/O → 短 SQL”。现有代码已把 I/O 放在连接外，但编排仍位于 HTTP 层。后续可沿用本切片方法逐个迁移，保持原准入拒绝，不能夹带 FR-002 政策变化。
3. `packages/domain/runtime.py` 同时提供领域辅助、协议校验、配置加载、psycopg 连接及命令事务，并在导入时读取本地配置。后续应先统计调用者/冻结摘要，再以兼容适配逐步外置配置与数据库职责。本轮未修改该模块，不能通过移动它悄悄改变权限、摘要或启动行为。

API main 的 1254 行体量不是本次重构依据；只选择有实际事务/外部调用边界的切片。未新增无限的微服务、IoC、ORM、队列或追踪改造任务。

## 决策与结构

按业务域新增 `packages/material_jobs`，其应用层依赖语言设施、纯 DomainError 和 Protocol 端口。既有资格校验、Command/outbox/预算/原生 RPC 留在原权威模块，由基础设施适配器委托；不复制 SQL 或创建新账本。

```text
HTTP 路由（认证、请求头、响应码）
  → apps/api/material_jobs_composition.py（构造器注入）
  → material_jobs/application.py（Target DTO、用例、事务/提交 Protocol）
  ← material_jobs/infrastructure.py（既有连接上下文、资格与账本适配）
  → 既有 model_governance 原生权威/提交通道
```

`Target` 是应用请求身份 DTO，不是持久化实体；Pydantic/FastAPI 不进入应用层，数据库 row 仅在事务适配器内部。已有版本化请求/回执 JSON 保持原验证和字段，不为重构复制一套 schema。

`Transactions` 明确拥有单次连接上下文。每次事务创建独立适配器和仅限该事务的 intent 缓存；service 本身不持有连接/Session。上下文退出负责原有 commit/rollback，退出失败时不得调用原生通道。费用观察仍为 read-only repeatable-read，历史读取不会因重构升级为发送。

申请仍按：提交 intent/Command → 资格观察/校验事务结束 → 独立 native submit → 新事务观察实际接受结果。丢 ACK 读原生结果恢复；并发撤销异常后在原事务再观察接受记录；未知基础设施异常继续抛出，不伪装成领域拒绝。

## 前后对比与代价

| 项目 | 之前 | 本轮之后 |
|---|---|---|
| HTTP 文件 | 277 行，内含事务和 native submit 编排 | 230 行，迁移的三个入口仅认证/映射/调用用例 |
| 应用测试 | 通过 HTTP 模块的全局替换间接测编排 | 可用纯内存事务/提交端口直接测，无 HTTP/DB/provider 初始化 |
| 资源所有权 | 路由内多个 with，规则靠约定 | 事务工厂每次独立连接/缓存；并发与异常退出有测试 |
| 依赖方向 | 编排直接依赖具体模块 | AST 测试阻止应用层导入框架/SQL/传输，也阻止迁移路由回填 SQL/native 操作 |
| 权威与外部契约 | 原实现 | SQL、权限、资格/预算/幂等/outbox、原生流程及 HTTP 契约保持 |

增加了应用/适配/组合文件和少量接口代码；这是为隔离真实生命周期规则付出的局部复杂度，不声称减少总代码量或改善未测量的性能。原 `_qualified_resume` 保留薄兼容门面，已有集成测试仍验证同一入口。

## 可执行验证

- 新应用测试覆盖 commit 失败不提交、事务外 native 调用、丢 ACK、终态重放、撤销与接受竞争、历史费用只读、异常不吞。
- HTTP 测试覆盖会话身份/CSRF 检查、幂等键/ETag 原样交接、200/202/private-no-store 和认证失败不创建资源。
- AST 架构测试覆盖纯应用导入、基础设施不反向依赖 HTTP、路由不直接执行 SQL/native；并发工厂测试验证连接/缓存独立及全部关闭。
- 既有资格/费用测试不改断言；最终定向 39 passed。
- 冻结摘要：execution `24c5d787…`、dispatch `2d17330c…`、guard `43fc9b0a…`、jobs `46c8e071…` 重构前后完全相同。所有原生 SQL/方法源文件未改，因此没有冒用旧版本的新执行语义。
- 重新导出 actual OpenAPI 并与已提交 JSON 做结构相等比较，通过；无需修改契约快照或前端生成文件。

完整后端回归：4369 passed、2424 skipped、0 failed/errors；前端 192 文件/1944 tests passed。后端 ruff/format（1141 文件）/mypy（704 源文件）/bandit 和前端 format/lint/typecheck/生产 build 通过。原生 PG/S3 缺环境、真实调用/效果未验收的边界不因重构改变。FR-002 协议仍待决，未实现或批准任何新模型资格。
