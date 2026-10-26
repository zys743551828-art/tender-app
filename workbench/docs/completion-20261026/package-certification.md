# /3 认证生命周期检查点

## 实际交付

`packages/package_model_certification` 的应用用例、纯策略、短事务适配接入既有 `/3` registry、曝光前冻结协议、原生 final 报告、live 观察与受控回退事件。没有新增平行证据仓库；只新增不可变认证及终态撤销记录。

实际 API 位于 `apps/api/package_model_certification_routes.py`：

- `POST /api/v1/package-model-certification/models/{model_id}/preview`：提交影子/回退事件 ID、明确 `valid_until`、理由；返回当前源摘要和绑定，不签发。
- `POST /api/v1/package-model-certification/models/{model_id}/certificates`：同上加 `expected_source_digest`、`Idempotency-Key`；原生事务再次获取权威来源并核对摘要，原子签发及回读。
- `GET /api/v1/package-model-certification/certificates/{id}`：复验当前权威，返回 active / expired / revoked / stale；不返回原始证据或预测值。
- `POST /api/v1/package-model-certification/certificates/{id}/revoke`：理由及幂等键，追加终态撤销；证据已过期或失效也可撤销。

沿用原生 registry 创建者与 active member 校验、既有 API 角色及写请求认证保护。调用者不能提交指标、来源类别、verified 标志或自选评估结论。没有新增账户角色、凭据或生产权限。

## 资格与时间边界

签发要求显式冻结的所有指标门槛通过；候选和固定回退模型均具有原生 external_evidence 来源；当前业务来源必须为 live 且不处于登记的测试数据库；影子、回退、当前输入、模型 artifact、producer 方法与 /3 冻结绑定一致。synthetic、retrospective、漂移、撤销、过期或缺链均拒绝。原生 final 报告重新计算来源身份，不能只相信已保存 JSON。

冻结必须早于 final 曝光且不同事务，也必须早于可信 capture；capture → 观察 → 回退按顺序发生。新认证方法独立版本化并包含自身源码/SQL、既有 producer 和准入策略摘要，不修改旧冻结执行方法。

有效期必须显式传入，无默认时长，且不能超过现有资格、价格、执行 profile 和历史适配器的最早有效期限。当前输入或源资格变化后读取为 stale，不把历史认证当永久可用。数据库全局生命周期锁、按序 bid/关系锁及源头共享锁用于短事务复验；历史适配器撤销表共享锁阻止签发事务内插入撤销。原生并发行为仍待 PG17 验收。

同一冻结模型仅允许一个不可变认证；相同请求/摘要/幂等键恢复原回执，不延长寿命。不同请求不能覆盖旧认证，撤销后不能以新键重新认证。此阶段不提供续期操作；新的模型版本须走原有完整冻结/验收链。读取/replay 仍检查当前权威状态。

## 安装与验证边界

`deploy/sql/package-model-certification.sql` 为全新安装可选脚本，在 `package-business-shadow.sql` 后、任何观察事件产生之前安装。未安装时 API 返回 503。脚本未在本环境执行，不是生产迁移方案，不修改冻结契约快照。

模拟权威通道构造 live 正例只验证策略/应用机制，测试不能把对象写入原生认证表或赋予生产资格。本轮未运行真实模型、真实影子流量、真实认证签发或部署。原生 PG17 环境缺失，SQL 事务、权限和锁的运行验收未完成。

最终完整后端回归 **4561 passed / 2424 skipped / 0 failures / 0 errors**（730.35 秒）。首轮定向测试 12 通过、1 失败（测试替身异常构造参数缺失），修复后 16 通过，最终全量包含全部新增用例。前端 192 文件 / 1944 测试通过；Ruff check/format（1192 文件）、mypy（746 源文件）、Bandit、前端 format/lint/typecheck/build 均通过。build 保留既有 chunk-size 提示。四个旧执行/派发/资格/任务方法摘要与既有基线一致。2424 skip 不算通过，完整原因已归档。

可审查补丁：`/workspace/scratch/tender-certification.patch`；日志、summary/junit、API 路径及文件清单：`/workspace/scratch/tender-certification-validation/`。本轮没有工具拒绝或结果不确定的生产操作。

## 剩余有限代码

下一项为正式预测消费及持久化/API/UI：在消费边界再次验证本认证，保持固定模型/输入、幂等恢复、隐藏设置和来源追溯。此阶段的 active 认证回执并不产生预测，也没有将研究候选自动发布。FR-002 及 FR-009/011/013 关联消费仍未完成，其余 FR 结论见 `fr-audit.md`。真实成对数据、原生环境和用户验收另列，不能以机制通过冒充质量验收。
