# 获批资格到原生任务接受与预算边界

## 实际实现

- `POST .../technical-scopes/{scope_id}/material-qualified-jobs` 固定资格记录/摘要/审核版本、范围、材料续验引用。复用现有 Command 幂等账本；先提交不可变申请，再进入独立原生事务。`GET .../material-qualified-jobs/{intent_id}` 只读，且仅原申请成员可读。没有新增平行任务、队列或预算账本。
- 新 `material_qualification.intents` 是共享 Command 的固定引用；`acceptances` 是既有原生 job 的提交证明。原生任务事务内的资格触发器复验审核头、成员状态、有效期、原件摘要、模型/profile/完整输入/价格/规则集合；与既有完整材料复验、job/slots/outbox 一起提交或回滚。资格登记和人工批准仍不是原生引用复验本身。
- 既有 `material_job_command.py` 作为唯一调用入口；服务器可选私有配置 `MATERIAL_QUALIFIED_JOB_PROFILE` 指向既有 CLI 的私有 profile。默认未配置。调用环境不继承 API DSN、会话密钥或模型 key；仅写临时 0600 固定命令，45 秒超时视作结果不确定。不相信 stdout 是提交证明，始终重读原生接受记录。
- 新的可选 fresh-only `deploy/sql/material-qualified-execution.sql` 在既有预算预留/一次发送授权事务的 attempt 插入前复验同一资格；失败使该事务内预留和余额变更一同回滚。使用既有预算不足/并发/未知计费/槽位幂等机制，不新造金额算法。既有 `send_until` 必须不晚于资格与价格的有效期；不能满足则拒绝整个授权，不篡改原生返回摘要或暗中缩短租约。
- 原生资格校验锁住审核头，撤销与**新授权**串行化。已经提交的授权不能追溯取消已经开始的网络请求；此时撤销不阻断费用记账/未知费用结算，但后续新授权被阻断。现有发送前租约检查和重复请求 `new_send=false` 保留。
- 申请额外固定资格守卫 SQL 方法摘要；API 和原生触发器均拒绝在守卫变化后重解释旧申请，不影响原接受记录的只读恢复。API 在独立原生调用前核对资格函数固定源码、owner、触发器事件/启用状态和表所有者；缺失或改变即拒绝。没有给原生用途角色添加表权限或额外 RPC，也未修改原有 RPC 的签名和方法摘要。
- UI 从已读取的获批资格版本固定申请，提交前持久化原请求/key/ETag；丢 ACK 后只恢复原申请。区分 `accepted_preparation` 与 `pending`，`send_authorized=false`；费用为 `not_observed`，不能把准备任务回执说成未扣费或发送许可。跨成员/范围迟到响应隔离，未知结果不自动换 key 或重发另一任务。

## 安装与验证边界

此 SQL 是全新隔离安装扩展，先安装资格登记、原生材料/job/preparation/execution 模块，再安装它；本任务没有执行安装。安装扩展后新 native job 必须具有固定资格申请，新 attempt 必须绑定接受证明。没有迁移或追认旧任务的公开入口；原有已提交任务仍可原 key 读回，结算不受新资格阻断。

原生测试中的资格、价格、能力测量与账号都是明确合成 fixture，不能当真实供应商证据。执行边界测试显式种入已准备任务的接受 fixture；另有真实 `jobs.start`/outbox 的隔离测试验证新任务接受。环境门控跳过不算通过。

## 本轮未完成的产品代码

现有 execution accounts/profiles 仍限定 `synthetic_mechanism`，生产 `execute_attempt` 仍默认拒绝。本轮接通了真实的原生**准备任务**调用路径和既有机制预算/授权的资格保护，尚未提供可启用的真实账户发送适配器。下一最小阶段是版本化账户/profile 与真实 sender 适配（默认 off），复用本轮资格/预算/结算边界和严格恢复；不能直接删除旧拒绝或把机制 origin 改名冒充 live 资格。该编码不再等待用户政策确认。

独立 PG17/S3、真实供应商能力/价格证明、真实付费运行及准确性评估仍未验收。没有使用生产数据库、真实模型、付费、部署、PR/合并或新增运行凭据/外部权限。

## 验证

- 最终后端默认全量：**4301 passed、0 failed/errors、2422 skipped**。首轮全量 4300 passed；补齐守卫摘要固定后，完整复跑至上述结果。
- 最终后端相关专项：**83 passed、9 skipped**。9 项新原生用例（含参数化反例）因隔离 PG17 环境未就绪跳过：并发原 key 接受/outbox、撤销后历史恢复、预算回滚、撤销/授权竞争、未知计费结算，以及期限/输入/价格/证据/守卫漂移。它们没有实际执行，不能算原生验收。
- 前端全量：**1931 passed / 191 files**；新旧界面专项 **19 passed**，覆盖原 key 恢复、未知接受状态、存储失败、错误发送权限回执与成员切换迟到响应。
- ruff、format（1128 文件）、mypy（697 文件）、bandit、前端 format/lint/typecheck、build 通过；build 仍有既有大包体积提示。`git diff --check` 通过。
- 证据：`/workspace/scratch/tender-qualified-acceptance-validation/`；补丁：`/workspace/scratch/tender-qualified-acceptance.patch`。

本轮没有安装/执行新 SQL、配置私有 native profile、启动真实队列消费者或发起模型调用；原生组合环境、真实账户及付费效果均未验证。
