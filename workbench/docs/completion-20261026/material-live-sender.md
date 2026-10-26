# 默认关闭的获批 sender：阶段一

## 实际实现

复用已有完整输入 preflight、原生账户预算预留、slot 唯一发送、结算和 Worker consumer。没有新任务系统、凭据文件或外部账户权限。

- fresh-only execution SQL 增加 `current_prebid` account/profile；原 synthetic `/1` 独立保留。获批模式使用 attempt/reservation/outcome `/2`，不接受模式与版本混用。数据库/LOGIN/profile/input/quote 绑定和预算锁保持既有机制。
- current_prebid 原生新授权必须存在既有资格 BEFORE INSERT 守卫。事务中的守卫仍检查固定资格、审核版本、材料、模型、价格和有效期；缺守卫不预留预算。
- 执行方法描述升级为 `/2`，摘要同时覆盖 sender 与资格审计源码；实际源码漂移使既有 profile 方法绑定失效。旧 synthetic 数据回执继续使用 `/1`，不把旧模式自动升级为真实调用。
- 新 `material_live_sender.Sender` 是进程所有的显式注入对象，`enabled=False`。账户/profile/digest 固定；凭据仅通过宿主回调传入既有 DeepSeek 客户端构造器，不从 Kafka、HTTP 请求或 ambient environment 读取。模型/endpoint 沿用既有 `/3` 配置，并不证明外部型号或能力真实可用。
- 发送前重新读取原生 `send_current`，检查资格头、有效期、撤销、证据引用、guard 摘要和既有 current_context。客户端复核同一 attempt、原始请求和发送期限；检查失败不发送，保守进入未知费用结算。
- `new_send=false` 不解析凭据、不调用 HTTP。未知费用、进程取消、丢结算 ACK 均沿用 durable slot 一次发送语义；不自动重试模型。撤销不阻断已发送结果结算。
- `QualifiedPorts` 接入现有 `deliver/consume_once`，恢复固定材料后调用实际 sender；已有未知/in-flight 财务状态在恢复和发送前停止。默认无 ports，旧 production_admission 仍关闭。

数据库授权/复读与外部 HTTP 无法构成跨系统原子事务。复读后已授予的在途发送不能因后续撤销被追溯取消；后续 slot 必须重新取得授权和复读。不能把这里描述成撤销能取消已经发出的请求。

## 验证与边界

新增测试只使用合成原生回执、模拟连接和 HTTP MockTransport，实际复用完整序列化和 DeepSeek 响应解析器。覆盖正常消费、配置关闭/漂移、撤销/期限/账户/凭据失败、混用版本、未知费用、丢 ACK、取消、发送后撤销结算、Worker 未知状态停止。没有实际网络模型请求。

原生 SQL 未安装/执行：既有 PG17/S3 临时环境缺失，数据库权限、并发/回滚和 `/2` 原生联合验收不能用模拟结果替代。初始化文件是全新库封存前的源码，不是已部署升级脚本；方法摘要随源码改变，旧 profile 不会自动获准。

## 下一段必需代码

1. 部署启动器的安全宿主注入装配：本阶段已有可调用 `consume_once(..., qualified_ports=...)` 消费入口，但现有命令行启动器仍只提供旧默认关闭路径。尚未提供真实运行配置，未读取任何真实 secret。
2. 权威执行/费用状态 API/UI：现有准备接受回执仍明确 `fee_state=not_observed`，不是执行结果。需从现有账本提供成员限定的脱敏观察入口，未知费用不能显示为零，总费用与已知估算必须分开。

人工证据批准不等于准确性验收；formal_prediction_eligible 仍为 false。未启动长期 Worker、配置凭据、修改权限、部署、付费、操作生产或创建 PR。

## 最终本地结果

- 完整后端：4322 passed / 2422 skipped / 0 failed / 0 errors（`deploy/ci_checks.py --suite unit`）。首轮 4320 passed 后补齐源码摘要绑定，再完整复验；不是仅依赖定向测试。
- 最终定向 sender/attempt/dispatch/guard：104 passed。
- 前端：191 文件 / 1931 tests passed；format、lint、typecheck、生产 build 通过。
- 后端 ruff、format（1130 文件）、mypy（698 源文件）、bandit 通过。
- 跳过项不是通过：包含原生 execution 16、dispatch 11、qualification/job/budget 9 项显式隔离 fixture；本机 Docker 无镜像，未安装或运行 SQL，也未请求新权限。
- 新 sender 的真实账户、模型能力、外部计费、原生并发与撤销联合验收未运行。当前验证为合成机制证据。
