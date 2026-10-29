# Final `/3` 预测冻结检查点

此冻结模块实现新特征候选的无标签 final 输入、完整材料复验和原生不可变预测冻结，本身不提供独立评价。后续的单独版本化扩展已接通[独立最终评价](feature-final-evaluation.md)；它不修改此冻结方法的源文件或旧记录。下文保留仅安装冻结扩展时的支持边界和阶段验证证据。

## 实际入口与持久化

- `deploy/package_history_worker.py --purpose final-feature-method` 无凭据输出本阶段方法摘要。
- 已有独立 evaluate LOGIN 通过 `--purpose evaluate --freeze-final-feature-predictions` 运行。传入现有五个完整材料参数：`--complete-references`、`--complete-material-store`、`--complete-artifact-dir`、`--expected-complete-reference-digest`、`--expected-complete-method-digest`；最后一个是本阶段方法摘要，不能混用训练方法摘要。仍需既有 `--profile`、`--job-id`、`--generation`。本机没有执行原生命令或提供新凭据。
- references 是 owner-only 600 文件，版本 `package-history-feature-final-references/1`，严格字段为 `version/cohort_id/membership_digest/candidate_digest/rows`。每行 `admission_id/reference`；成功成员引用既有 `/3` 全部固定键，排除/无标签成员 reference 必须为 null，保留分母、不读取它们的原件。
- 数据库输入仅由原生 `claim_job` 返回；CLI 不接受调用者上传的原生权威包、final labels、exposed 布尔值或更换模型。原生包含已封存候选、final manifest、原件/范围身份、训练成员/材料回执及仅用于反泄漏的官方标签来源 ID/摘要，不含 final target。
- 复验 `/3` 原件、原始请求/响应、完整范围、时间和来源；复开原训练 reference CAS 与 `/3`，拒绝复用 input/call/response 和项目/组跨分区。严格重算既有六维投影，只调用 `predict`，不调用拟合、development 选择或校准。缺明确数值档位记录 failed；缺源或身份漂移拒绝整个阶段，不静默删成员。
- 可选 SQL 在同一既有租约下保存 `feature_final_inputs` 和 `feature_final_predictions`，分别 append-only、无直接角色 grants。冻结时再次核对候选/模型/分母/原生绑定，检查投影摘要，并按冻结模型的变换和系数复算预测（只容许 1e-8 数值误差）。调用角色仍受原有权限、当前来源检查及代际 fence 控制。
- 成功返回 `state=predictions_frozen`、预测/候选/模型摘要、replayed 和 `evaluation_status=not_implemented`；评估 job 回到 queued，未伪称 succeeded。重复或丢 ACK 后立即可重新 claim，重算一致则幂等；不同预测或不同来源冲突，不覆盖。

## 部署与兼容边界

`deploy/sql/package-history-feature-final.sql` 是 **fresh-only、未执行**的可选扩展，在历史 research（及可选 complete reader）之后、exposure bridge 封存之前安装。校验原函数体、owner、SECURITY DEFINER 和 search_path，保留 claim/finish/open 的签名、OID、ACL，不加角色或授权，不接默认 BASE，不重封存既有 guard。已有部署迁移尚未编码；本阶段不部署任何数据库。

旧常数基线训练、预测表、结果及 CPU 方法不变，纯旧基线任务仍走原曝光/评价路径。包含 `complete_feature_training` 的任务，在此扩展中 **一律拒绝 `open_final`**，包括候选 unavailable 的任务；不能把旧基线评价冒称新候选评价，也不能先曝光标签再补预测。本阶段不提供新候选最终指标 API/UI，旧 UI 不会显示新指标。新方法描述独立，旧训练候选 `final_test_consumption=not_implemented` 不被篡改。

## 验证与限制

默认完整后端、前端、静态检查和构建结果在阶段结束时记录于下方。测试使用明确合成材料与模拟的原生连接；不是独立项目统计证明或真实精度验证。新增 PG 测试仅在显式一次性 PG17 配置下运行，覆盖 fresh 安装/ACL/guard 及旧基线兼容；原生冻结/并发/曝光事务的完整联合验收仍未执行，不以 Python 模拟替代。

初次 focused 测试有两处测试断言失败：误把正文内 `target` 单词当字段泄漏，以及误认为保留的旧基线 SQL 不应出现 `created_xact`。已分别改为字段检查和新候选拒绝曝光的控制流顺序检查。补充训练侧 call/response 重读后，另出现模块名被局部变量遮蔽及修复中遗漏导入的问题，导致 11 项 focused 失败；已修正，保留所有失败日志。最终结果另列，不隐去失败。

## 下一实际代码

1. 在现有曝光权威下，绑定本阶段不可变预测摘要后允许新候选唯一曝光；不得由调用方布尔声明代替原生提交事务与跨通道曝光限制。
2. 曝光后独立读取标签，校验冻结候选/预测/分母，调用既有 metrics，持久化独立、版本化结果及幂等回执。不可重新拟合、选择模型/变换/校准；旧常数基线结果保持独立。
3. 扩展闭合 API/UI 方法标识及 final 结果展示；补齐原生副作用回滚、丢 ACK、并发曝光、源撤销反例。完成后才能通过单独版本化扩展将本阶段拒绝门替换为受控消费，而非简单删门。后续不得修改已冻结预测方法绑定的本模块/SQL 来重解释旧预测；已有安装仍需独立评审的迁移，不得重封存 guard。

环境缺口另计：PG17/S3 原生临时环境、指定 Word03 转换镜像。真实成对数据和真实质量另计；它们不阻断以上编码，也不赋予正式预测资格。

## 最终检查结果

- 最终默认后端：4128 passed、0 failures、0 errors、2404 skipped，434.82 秒；5 个既有依赖警告。跳过不是验收通过。
- 本阶段 focused：22 passed、2 skipped（包含在全量内，不另加）；2 项是 fresh disposable PG17 显式 opt-in，环境未配置。
- 前端：186 个文件、1884 tests passed，无失败/跳过；format/lint/typecheck/build 通过，build 保留既有大 chunk 警告。本阶段无前端源码改动。
- 后端 ruff check、ruff format（1103 文件）、mypy（686 文件）、bandit 通过；git diff --check 通过。
- `deploy/check_compose.py` 执行失败：本工作树不存在默认 `.env`，其 Docker Compose config 子命令退出 1。没有生成凭据、启动容器、连接生产或更改权限。
- 新 SQL 未部署/执行，原生通道仅模拟。真实数据精度、完整 Word 转换和曝光后特征评价均未验收。

复核远端时 fusion 为 `462ec226013b011a40c204fe1c65541c4dbfbc25`，本阶段起点为 `0c0d53b8945371d59da1cf39b90acb236b0ac6ce`；未覆盖并行分支。独立分支无匹配 push CI 触发，本阶段证据是此环境回归。
