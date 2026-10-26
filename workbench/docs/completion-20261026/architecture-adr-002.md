# ADR-002：模型登记事务编排

状态：第一项有限后续重构已实现；正式模型准入仍待决。基线 `4b689e4`。

## 证据与范围

`apps/api/model_registry_routes.py` 的登记入口直接串联 preview、Command 查询、对象 stage、第二次 preview、Command 发布和 ETag 比较；读取入口直接串联 blob 查询、对象字节验证和当前视图查询。外部 I/O 原本已经位于事务外，这次保持其正确顺序，把规则从 HTTP 中抽离并建立可执行约束。

新增业务域 `packages/model_registration`：application 只依赖标准库，定义 Register/Plan/Outcome DTO 和 Transactions/Objects Protocol；infrastructure 复用原 `registry`、`Command` 与 `match`，SQL语句、参数和锁序不变；HTTP composition root 注入连接工厂和对象适配器。登记与读取路由保留认证、CSRF、请求头和响应映射。

路由控制 publish/rollback/suspend 和其正式资格拒绝保持原实现，没有借登记重构实现 FR-002。未新增持久实体、权限、资格、ORM 或 IoC 框架。

## 保持的事务顺序

1. 第一短事务先重验来源，再查询幂等命令；重放不进行对象写入。
2. 事务退出后执行已有有界 artifact stage；失败/取消时无数据库连接占用。
3. 第二短事务先重验 preview，再创建 Command；并发重放直接返回原结果。
4. publish 继续检查原始对象/来源，随后比较两轮 ETag；漂移导致事务回滚，不执行 Command.finish。
5. 模型读取依次为短事务读 blob 引用、连接外验证真实字节、短事务读取当前视图。

阶段间对象写入成功但数据库拒绝时，保持原来的幂等对象写入语义；没有新增删除清理或把残留对象当已登记模型。

## 约束与证据

- 应用模块禁止框架、数据库、存储导入；迁移的两个路由禁止 connection/SQL/registry 直调。
- 行为测试覆盖初始重放、对象写入后并发重放、来源漂移回滚、对象失败/取消释放、真实字节验证位于事务之间。
- 定向结果 19 passed、4 native opt-in skipped。Starlette/anyio 有一条既有第三方 deprecation warning，不是业务失败。
- actual OpenAPI 结构比较完全相同；原 `registry.py`、原生 SQL、统计/训练/方法源码未改。历史候选清单不重写。
- HTTP 文件从 210 行减为 187 行；代价是增加局部 DTO/端口/适配文件，收益为可独立验证的事务生命周期，不声称性能提升。

完整后端 4377 passed、2424 skipped、0 failed/errors；前端 192 文件/1944 tests passed；ruff/format（1146 文件）/mypy（708 源文件）/bandit 及前端 format/lint/typecheck/build 通过。下一项仅为 `domain.runtime` 配置/数据库职责提取及兼容/摘要边界；不扩展本次架构范围。
