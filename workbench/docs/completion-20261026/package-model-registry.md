# FR-002 阶段二：/3 ridge 独立登记 artifact 与实际消费

基线 `83f047a`。这是注册及研究推断闭环，**不是正式资格、真实质量验收或正式预测业务入口**。

## 已实现

独立协议 `registered-package-score-artifact/1`，包含稳定 model UUID、原生训练 job/cohort/成员/训练协议/result 摘要、完整候选及其摘要、适配方法摘要、明确六维特征名称顺序、单位区间输入尺度和归一化 0–100 输出尺度。UUID 由训练 job 与新版本名派生。旧 `registered-score-artifact/1`、旧模型统计/登记/路由全部保持独立，新 artifact 不进入旧表或旧 infer。

原生源只从已有 `package_historical_research.results` 的 `complete_feature_training` 读取。`external_evidence` 只是来源类别，不是准确性证明。应用在一个短事务中复验来源、构造/校验 artifact、比较调用者保留的 preview 摘要、登记不可变文档；没有跨事务对象 PUT 或网络调用。可选新库 SQL 复用既有 API 角色、cohort 创建者、有效成员、曝光桥 readiness 和 current_cohort，不创建 LOGIN。数据库保存 JSONB 与既有 canonical digest，唯一训练 job 登记及 key/body/reason 一致重放；不同请求拒绝，陈旧来源也拒绝重放新使用。

实际 API：
- GET `/api/v1/package-model-registry/training-jobs/{job_id}/preview`
- POST `/api/v1/package-model-registry/training-jobs/{job_id}/registration`，body 为 `expected_artifact_digest`、`reason`，并使用稳定 `Idempotency-Key`、既有认证/CSRF。
- GET `/api/v1/package-model-registry/models/{model_id}`，重新核对原生来源和 artifact 方法版本。

消费者 `deploy/package_registered_prediction.py` 可接登记 API 的私有回执文件，核对请求中独立保存的 artifact digest 后放入既有 PrivateContentStore；也可使用先前已核验的 CAS 字节。加载 `/3` 原件/原始响应/固定绑定，重新投影六维特征并调用已有 ridge predict。拒绝调用者直接传特征向量；输出研究点分/区间、input/projection/artifact/method 摘要，写入 CAS 和既有原子命令索引，可重复恢复。`research_only=true`、`formal_eligibility=unavailable` 和全部原 handoff 资格 flags=false。本地文件身份不证明原生认证或真实材料真实性。

CLI 使用 `--store`、`--artifact-dir`、`--result-dir`、`--request`、`--expected-request-digest`，首次可加 `--registry-receipt`。request 的封闭字段为 `version=registered-package-research-request/1`、UUID `command_id`、`artifact_digest`、原 `/3` `reference`、`expected_input_digest`。目录/文件沿用 0700/0600 与禁止符号链接边界。它没有 DSN、供应商配置、付费或网络入口，不自动创建根目录。回执包含 `result_digest` 和 `replayed`；同 key 不同请求不能覆盖。

## 拒绝与版本规则

检查候选封闭形状、feature schema/顺序、训练方法、model 参数/alpha、fit-only 选择标识、development 选择次序、最小组数、校准区间/秩、摘要和所有不可升级 flags。模型/特征/输入/适配方法变化必须用新身份重新登记，不能改旧冻结文档或替换方法摘要。

保留前一阶段业务门槛协议的封闭规则和无默认阈值约束。**没有**把旧 `score-business-admission-protocol/1` 的 artifact family 字段改成新版本，也没有从研究选择超参数推导准入门槛。本阶段新增 artifact 尚不能取得准入，下一阶段须对原生 `/3` cohort 接入明确版本的门槛冻结和证据认证权威；不能将此遗漏称为已经复用完成。对后续证据绑定已提供稳定 source/model/artifact/method 身份，不先造一份没有消费者的认证协议。

## 验证边界

初版定向 27 passed（新 registry/CLI 19 项与旧登记应用 8 项）；复查后将布尔/整数封闭形状改为规范字节比较，新增反例后的新 registry/CLI 20 passed，包括重算外层摘要后的畸形候选、顺序/尺度/方法漂移、旧新混用、preview 漂移、实际 CAS 原件重载、错误输入/绑定、真实本地 subprocess CLI 与结果恢复、符号链接拒绝。仅合成机制。数据库 SQL 的角色/锁/重放目前只有静态约束检查，未运行原生事务/并发验收；既有 PG17/S3/镜像环境缺口没有消失。没有真实模型、证据签发或部署。

## 剩余有限代码

1. 原生 `/3` 的业务门槛冻结与独立真实报告/影子/回退证据绑定；认证有效期、撤销及执行时重验，复用前一阶段无默认门槛原则。
2. 获准模型的正式业务预测持久化、幂等/API/UI/报告隐藏与 metrics 配对。当前研究推断不是正式预测。

FR001–013 对照仍以 `fr-audit.md` 为准；FR002 及 FR009/011/013 的相关正向消费未完整，其他 FR 的既有实现与外部验收状态不因本次新增 registry 改变。

最终版本完整后端 4435 passed、2424 skipped、0 failures/errors（修正前一轮 4434 passed/2424 skipped，日志另存）；前端 192 文件、1944 tests passed。ruff/format（1162 文件）、mypy（721 源文件）、bandit 及前端 format/lint/typecheck 通过。四个材料执行方法摘要与基线一致，旧训练/final/registry 源码未修改。
前端构建通过，仅有既有 chunk-size 提示；未部署。
