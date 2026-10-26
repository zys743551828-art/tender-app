# /3 内部观察执行检查点

## 本阶段代码

新增 `package_model_observation` 应用用例、受控 CPU 执行器、原生事务适配器与显式 CLI。没有启动任何观察或模型请求。

入口 `deploy/package_model_observation.py` 接收私有请求文件、其 SHA256、已有成员身份和私有 CAS/冻结索引目录。请求 `package-internal-observation-request/1` 只含 `command_id/model_id/admission_id/artifact_digest/method_digest/reference`，不得提交预测数值、verified 或认证结果。`reference` 复用已有 /3 完整引用，无第二套材料格式。执行依赖已有 API_DATABASE_DSN 安全注入，代码不读取 `.env`、不配置凭据；未配置默认失败。该入口是受控内部操作工具，不是终端用户身份认证替代物，也未挂到业务预测 API。

应用先用短事务读取原生来源，释放连接后复验原件/完整响应、六维投影并消费已经登记的 /3 岭模型，第二短事务再次复验来源且比较完整摘要，然后提交不可变事件。既有冻结训练/评价/registry 源码没有改动，新观察方法另行版本化并绑定自身执行源码、SQL、registry 方法与 handoff 方法。

新库可选 SQL `deploy/sql/package-model-observation.sql` 安装在 registry 后、首次注册前；不改曝光 bridge 的冻结函数，不新增角色。来源仅允许活跃创建者同时拥有模型和历史材料准入；取所有候选成员与观察材料的 bid 并集后按已有顺序加锁。候选 cohort 的任何保留关联身份与观察输入重合、或观察输入已被 final 曝光，均拒绝。来源复验包含原生 proof/adapter 时效与撤销；标签只导出待排除的文档身份/文件摘要，不把标签值传入预测。

执行器检查原件集合、长度、摘要、scope/manifest/时间/origin、模型及方法版本，拒绝标签原件混入。结果只有内部数据库事件保存数值；CLI 返回不可变摘要回执，明确 `historical_receipt=true/current_authority_checked=false/formal_eligibility=unavailable/certification_issued=false`。已提交丢 ACK 后可恢复同一回执；撤销后仍能读历史回执，不重新执行、不声称当前资格。相同 command 换正文或跨成员读取被拒绝。CPU 异常/取消、执行期间撤销或身份漂移不会写成功事件。

## 边界与下一阶段

这是 **retrospective_internal** 观察，不是在线/预投标影子监测，更不自动满足正式认证的影子要求。原生材料仍受既有历史准入规则约束；合成原件与模拟 native channel 只证明消费机制。非 owner 受控 API-role 服务是执行信任边界，SQL 不独立重算 Python 模型；不向客户端提供可直接提交 result 的 HTTP 接口。

本次没有实现回退路由动作或回退验收事件，不能把重算一次数值说成回退验收。下一有限阶段应复用已有发布/暂停/回退语义，实现 /3 内部路由 CAS、固定回退模型的实际消费及动作生成的不可变回执；之后才接认证生命周期和正式预测。无新增阈值或政策决策等待。

## 验证

定向测试覆盖实际私有 /3 CAS 消费与现有 registry 推理数值一致、原件/标签隔离/输入和方法漂移、两事务资源释放、取消/失败/并发来源变化不落成功事件、重复/丢 ACK/跨成员回执、CLI 接线与错误脱敏、应用层依赖与 SQL 权威边界。完整回归结果将在阶段交付记录中填写。

PG17 原生环境缺失，新增 SQL 未执行；锁顺序/并发撤销/数据库角色授权只做源码约束检查，不能报告为原生事务通过。没有真实影子、真实模型调用、付费、生产访问、认证签发或部署。

最终后端默认回归：4497 passed、2424 skipped、0 failures/errors（651.03 秒）；观察/registry/准入相关回归 82 passed；观察首轮 27 passed，随后增加请求变更反例，已纳入全量。前端 192 文件、1944 tests 全通过；格式/Lint/typecheck 与后端 Ruff/format（1174 文件）、mypy（731 源文件）、Bandit 全通过。既有 execution/dispatch/qualification/jobs 冻结方法摘要逐项与架构前基线一致。本阶段没有测试失败；运行中的用例未取消。

前端 build 通过（保留既有 chunk-size 提示）；本轮未更改 HTTP 契约或 UI，不需要重新生成 OpenAPI。验证日志、完整 skip 原因与补丁在 `/workspace/scratch/tender-package-observation-validation/` 和 `/workspace/scratch/tender-package-observation.patch`。
