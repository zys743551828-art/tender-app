# ADR-003：运行配置与连接生命周期职责隔离

状态：已实现并完成本环境回归。基线 `e892e895`。

## 证据与决策

`packages/domain/runtime.py` 同时承担导入时开发配置加载、数据库连接、命令账本及领域校验。复用配置或连接原语会连带触发领域模块初始化；测试连接生命周期还需依赖这个混合模块。本次只提取两个基础设施职责，不批量迁移调用方、不修改事务权威或引入框架。

`packages/platform_runtime/configuration.py` 接受显式环境映射，保留原有优先级、引号、注释和缺失配置错误。导入新模块不读配置。旧 `runtime` 在原时机调用兼容 bootstrap；`WORKBENCH_ENV_FILE` 仍只是既有用途进程的默认文件加载退出标记，不把它扩展成读取任意路径的功能。

`packages/platform_runtime/database.py` 在进入上下文时解析用途 DSN、创建单次拥有的连接并设置事务内 search_path；退出交给原 psycopg 上下文提交/回滚/关闭。连接器与配置查找可构造注入，没有共享 Session、池或全局连接。旧 `runtime.connection` 保留调用签名与延迟查找语义。命令账本、outbox、审计 SQL 和权限检查原样保留；不宣称整个 domain 已经纯化，也不声称解决同步 I/O 性能问题。

## 行为与源码身份

- API/Worker 用途、正常提交、异常和 BaseException 取消、建立事务失败、并发连接独立性均有可执行机制测试。
- 新模块禁止依赖 apps/domain/FastAPI；隔离子进程验证导入不触发业务配置读取。
- 四个材料执行/派发/资格/任务方法摘要与基线逐字一致；actual OpenAPI JSON 结构一致。
- DOCX 导入方法原本以完整源码摘要版本化，旧 runtime 已在身份清单中。本次把三个新依赖明确纳入 DOCX SOURCE_FILES 与 review acceptance REQUIRED_SOURCES；方法身份因源码变化正常变化，运行中依赖漂移仍拒绝并要求重启。未改历史候选、归档清单、协议 schema 或重写断言来绕过冻结规则。旧评审材料不能冒充新实现的完整验收。

## 范围与验收边界

本次两项有限后续重构到此结束：模型登记应用用例与配置/连接职责隔离。FR-002 正式模型业务准入协议仍待决，未实现或暗中批准。未改凭据、部署、权限、数据库 schema、供应商调用；原生 PG17/S3/Word03 组合验收仍受原环境条件限制，不能由模拟连接测试替代。

定向平台/评审/异常隔离 70 passed、1 skipped；DOCX 与两应用切片关联回归 90 passed、1 skipped。跳过项为既有 opt-in 环境测试。

完整后端 4391 passed、2424 skipped、0 failures/errors；前端 192 文件、1944 tests passed；ruff/format（1150 文件）、mypy（711 源文件）、bandit 及前端 format/lint/typecheck 通过。
前端生产构建通过，保留既有 chunk-size 提示；没有部署。
