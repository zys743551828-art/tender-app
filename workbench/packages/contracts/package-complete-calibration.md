# 完整材料历史研究装配 /1

此协议新增本地 `package-complete-calibration-assembly/1` 交接，不改变 `/3` 输入、特征、原生历史资格或已冻结 CPU 协议。只接受 `synthetic_mechanism`；`unqualified_research` 即使内容哈希正确也拒绝。内容身份和调用者声明不能授予历史存在性、最新范围权威、真实标签资格或正式评分资格。

## 入口和冻结内容

现有 `deploy/package_history_worker.py` 隔离子进程新增：

- `--purpose complete-calibration-method`：读取当前装配方法摘要，无材料参数。
- `--purpose complete-calibration-freeze --material-store CAS --artifact-dir FEATURE_INDEX --result-dir RESULT_INDEX --command-id UUID --selection PRIVATE_JSON --labels PRIVATE_JSON --expected-selection-digest SHA --expected-labels-digest SHA --expected-calibration-method-digest SHA`。
- `--purpose complete-calibration-read --material-store CAS --artifact-dir FEATURE_INDEX --result-dir RESULT_INDEX --command-id UUID --expected-artifact-digest SHA`：从保存对象重做完整复验与计算，不只展示旧 JSON。

沿用已有私有 CAS、0700 索引目录、0600 普通文件、无符号链接读取、原子命令索引与清洁环境。不会读取 DSN、`.env`、发起模型请求或连接数据库。stdout 仅回执/摘要；基线结果、选择和标签保存于私有 CAS。输入文件各至多 256 KiB、至多 64 个材料。索引冲突不覆盖；丢 ACK 可重放；对象先写、索引最后发布，发布失败可能遗留未引用对象。

选择文件严格字段：`version, origin, cohort_id, method_digest, timing, members`。`timing` 沿用 CPU 的 `submission_split_at, label_available_as_of, training_frozen_at`。每个 member 严格包含 `id, project_id, group_id, purpose, submitted_at, scope_id, scope_digest, reference`；UUID 使用规范形式。purpose 为 `fit/development/calibration/final_test`。reference 是上一阶段完整交接的 `source_commit, command_id, origin, expected_artifact_digest, expected_input_digest, expected_binding_digest, expected_feature_method_digest, expected_handoff_method_digest`。

标签文件严格字段：`version, origin, selection_digest, rows`；每行只允许 `id, target, label_known_at`，target 为 0–100 有限值（建议十进制字符串；文件拒绝 JSON 浮点数）。必须恰好覆盖非 final-test 成员，重复、缺失、额外和 final-test 标签均拒绝。调用者独立保留两份输入摘要与方法摘要。方法绑定装配源码、既有 handoff 方法、CPU 方法及其固定协议。

## 隔离与计算边界

1. 先复验所有 `/3` 原件、请求、响应及特征，标签对象不传入这些函数。随后才解码独立标签对象。选择中添加 target/features 等旁路字段拒绝。
2. 原生输入里的 bid/scope/digest 必须匹配冻结选择；不同项目不能借相同组跨用途，同项目也不能改组逃逸；重复成员、输入、来源 commit、scope、调用 ID、response ID 拒绝。input_as_of 不得晚于声称提交时间；final-test 和训练侧必须在提交分界两侧。CPU 再检查标签时点和独立拟合组。
3. 这只能证明固定合成声明内部一致，**不证明实时 DB 最新范围、历史时间真实性或原件文本没有标签**。真实材料仍禁止进入此装配；未来必须通过独立原生准入和材料标签排除规则，不能把 origin 改名当资格。
4. 复用 `package_history_cpu.train` 的项目加权 mean/median、独立 development 选择和 calibration 组最大残差区间；没有新拟合框架，没有补零旧特征。`features_used_for_fit=false`。最终测试标签不读取、不评价；不足校准组保持 radius=null。
5. 数值只放在 `mechanism_baseline_result`，用于检查机制；不是效果、精度或预测承诺。`training_eligible/metrics_eligible/formal_prediction_eligible` 等全部保持 false，`formal_prediction=null`、`acceptance_decision=unavailable`。不输出正式结果。

下一阶段仍需实现 `/3` 非数值票到适用数值候选的独立版本化映射和特征感知训练装配，以及原生受控来源选择/分组/标签权威接入；不能因此删除现有正式执行 blockers。此 CLI 不是正式模型发布入口。
