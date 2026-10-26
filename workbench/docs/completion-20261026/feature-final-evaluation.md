# 冻结特征候选的独立最终评价

已接通原生冻结预测的曝光绑定、独立评价计算、既有结果持久化和闭合 API/UI。它是研究机制实现，不是原生事务环境、真实评分效果或正式模型资格验收。

## 业务入口与顺序

沿用既有 CLI。先使用 `--purpose evaluate --freeze-final-feature-predictions` 完成本阶段之前的预测冻结，再以同一 job/generation 执行 `--purpose evaluate`。后者不接受新模型、变换、校准半径、final 标签或调用者 exposed 布尔参数。

1. `claim_job` 在当前来源、关联组、角色和租约约束下读取已冻结输入/预测。运行器在访问标签前复核候选、方法、投影摘要、预测算术、原生 proof/context、项目/组隔离及完整分母。
2. `open_final` 必须找到有效的冻结输入/预测，且绑定原训练候选。它在原有曝光事务内追加 `feature_final_exposures`，绑定 exposure ID、input/predictions/candidate 摘要。旧跨研究组/跨通道曝光约束继续生效。重复请求只返回相同曝光，不生成第二次资格。
3. 曝光事务提交后才在独立连接调用 `read_final`。返回的版本化附加输入绑定上述记录；在同事务内读取标签、无预测曝光、失效租约、身份漂移均保持拒绝。
4. 新消费者只复核已冻结向量并调用固定模型，不重投影、不重选、不拟合、不重新校准。已有 group metrics 负责保持 failed/rejected/unlabeled 分母、项目权重、区间和基线比较；旧常数基线仍由原 CPU 独立计算。
5. `finish_job` 保存同一不可变研究结果中的 `feature_final_evaluation` 附加记录。原生曝光存在则必须提交匹配的新评价，不能只交旧基线绕过；没有绑定曝光不能注入附加记录。完成回执沿用 job/result digest，丢 ACK 后读原成功结果摘要；曝光 ACK 丢失则复用原绑定继续评价。

旧冻结预测模块/SQL、训练模型及基线方法源文件没有改写，原方法摘要继续有效。新评价模块与 SQL 使用独立方法摘要。新候选不会将旧记录中的 `final_test_consumption=not_implemented` 原地改为完成；独立最终评价以新结果记录表达。

## 原生扩展与公开契约

`deploy/sql/package-history-feature-evaluation.sql` 只能用于全新评审安装：在 `package-history-feature-final.sql` 之后、exposure bridge 封存之前。它校验四个前置函数体，保持原签名、OID、ACL，不增加角色或 grants，不接默认 BASE，不绕过既有 guard。已安装数据库的迁移仍是独立待编码/评审事项；本次没有执行 SQL 或部署。

公开结果仅增加闭合字段 `feature_final_evaluation`：方法/模型/输入/预测/标签/候选摘要、曝光 ID、完整研究指标和固定不可用资格。没有原件、原始请求响应、target 列表或本地 CAS 路径。实际 OpenAPI、生成的 TS 类型和前端运行时校验同步更新。UI 分开显示特征候选与常数基线，保留真实精度未验证提示；切换任务后迟到结果不替换当前选择。

## 验证与边界

合成 `/3` 材料和模拟原生连接覆盖固定模型评价、失败分母、模型/方法/候选版本混用、预测/向量/源证明篡改、跨任务与分组泄漏、授权拒绝、过期租约、曝光/结果丢 ACK 恢复、封闭 API、UI 身份校验及迟到响应。它们不证明真实数据独立性或精度。

可选 PG 测试新增 fresh-only 安装/guard/权限、无冻结预测拒绝曝光和旧常数基线兼容。缺显式一次性 PG17 环境，未执行；完整新路径的原生并发/回滚/一次性曝光联合验收仍需该环境，模拟结果不能替代。Compose 缺 `.env` 沿用环境未验收记录，不创建真实凭据。

## 下一实际代码

- 后续已完成自动调度器的固定 references/CAS、方法 pin 和恢复消费，见 [固定材料调度](feature-dispatch.md)；UI 登记任务仍不会自动构造私有材料引用。
- 已安装部署的评审迁移与方法版本兼容，不能重封存旧 guard 或就地解释旧预测。
- 正式整包评分的完整范围/视觉输入权威、真实端口和方法认证装配仍缺，不能删除 readiness blockers 或把研究结果升格。
- 复杂输出剩余格式仍按清单拒绝。原生 PG、指定 Word03 转换、真实配对质量分别属于环境/数据验收，不能冒充待编码功能，也不阻断上述独立编码。

## 最终检查结果

- 默认完整后端：4151 passed、0 failures、0 errors、2407 skipped，477.36 秒，5 个既有依赖警告。跳过是未验证覆盖。
- 新消费者 focused：23 passed、3 skipped；前端相关 130 passed（含新 UI 11 项）。这些与全量重叠，不累计。
- 前端最终全量：187 个文件、1895 passed，无失败/跳过，90.64 秒。format/lint/typecheck 通过。
- 后端 ruff check、ruff format（1106 文件）、mypy（687 文件）、bandit 与 git diff --check 通过。
- 首轮后端全量 4150 passed、1 failed、2407 skipped。失败是新公开契约测试复用精简计算夹具，缺原生 timing 固定字段；修正夹具后重新完成全量，未放宽契约，初始失败日志保留。
- 原生 PG 的 3 项新增 opt-in 测试未运行；新曝光/冻结 SQL 的真实并发与回滚联合验收仍缺环境。Compose 因已知缺 `.env` 未重跑，不创建凭据。真实数据效果和正式资格未验证。

本阶段起点 `52efbdfdcb89f2a56d97d024845a190f81025689`；复核远端 fusion 仍为 `462ec226013b011a40c204fe1c65541c4dbfbc25`。不创建 PR/合并/部署，不连接生产或执行付费调用。

前端最终 build 通过（既有大 chunk 警告）；训练页已明确引导查看独立评估任务，不再显示整个最终消费“尚未接通”的过期提示。最终 UI 文案对应的全量与 build 均已复验。
