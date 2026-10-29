# Final 特征预测冻结协议

此协议的范围是无标签 final 输入与预测冻结，研究用途。独立评价由[单独协议](package-feature-evaluation.md)消费，正式预测仍不可用。实施与验证边界见[阶段记录](../../docs/completion-20261026/feature-final-freeze.md)。这里不修改冻结 SQL/OpenAPI 主快照。

## 输入与引用

`package-history-feature-final-input/1` 只由独立 evaluate LOGIN 的原生租约返回。字段严格为：`schema, cohort_id, membership_digest, origin, candidate, candidate_digest, manifest, manifest_digest, material_bindings, bindings_digest, training_inputs, training_members, forbidden_label_sources`。不含 final target。`forbidden_label_sources` 仅含 ID/文件摘要，用于拒绝官方标签混入模型原件，不授予读取标签权限。

私有 references 文件使用 `package-history-feature-final-references/1`：`version, cohort_id, membership_digest, candidate_digest, rows`。rows 每行 `admission_id, reference`，必须覆盖原生 final manifest 全部分母；已排除/无标签成员的 reference 为 null。其余 reference 严格复用已有 `/3` 固定源引用，无模型覆盖参数。

## 冻结结果

`package-history-feature-final-predictions/1` 的字段严格为：`schema, cohort_id, membership_digest, candidate_digest, model_digest, method_digest, reference_digest, bindings_digest, manifest_digest, rows, research_only, formal_prediction, evaluation_status`。

- `research_only=true, formal_prediction=null, evaluation_status=not_implemented`。
- rows 按 ID 排序，每行 `id, status, prediction, projection, receipt`。
- 成功行保存既有 `package-complete-numeric-features/1` 投影和固定岭回归预测；receipt 绑定 `proof_id, context_digest, input_digest, artifact_digest, source_commit`。
- 不支持明确数值档位记 failed，prediction/projection 为 null；原生 rejected/unlabeled 不升格，也不消失。
- 原生方法摘要绑定实现、可选 SQL 与现有训练方法。旧训练方法摘要和候选记录不修改。

## 权威与恢复

可选 fresh-only SQL 保持既有函数 OID、ACL、独立非 owner 角色和曝光 guard。输入、预测分别 append-only。相同 job 只能冻结一次；精确重算允许恢复丢 ACK，结果不同则冲突。冻结事务释放阶段租约，job 为 queued 而非 succeeded。原生权威控制来源有效性、代际、所有者和曝光状态；本协议没有调用方 exposed/verified 开关。

包含特征候选的 job 在本阶段扩展下禁止 `open_final`；纯常数基线 job 保留既有行为。预测冻结不授予训练、正式评分、独立评价或真实精度资格。
