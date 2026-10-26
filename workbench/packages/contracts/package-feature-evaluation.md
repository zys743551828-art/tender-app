# 特征独立最终评价契约

研究用途，正式输出不可用。与旧常数基线结果并列，不修改旧模型/预测/训练记录。完整实施与未验收边界见[阶段记录](../../docs/completion-20261026/feature-final-evaluation.md)。

原生输入 `package-history-feature-evaluation-input/1` 仅能由曝光提交后的独立 `read_final` 返回：`version, exposure_id, input, input_digest, predictions, predictions_digest, candidate_digest`。input 和 predictions 是已有不可变 final 冻结记录，标签仍来自既有权威 final export，不接受本地上传或暴露状态布尔值。

公开结果 `feature_final_evaluation` 是 `package-history-independent-evaluation/1` 的可选闭合字段，版本 `package-history-feature-evaluation/1`。严格字段为：

- `version, cohort_id, origin, membership_digest`。
- `method_digest, freeze_method_digest, candidate_digest, model_digest, predictions_digest, labels_digest, input_digest, exposure_id`。
- `report` 复用既有完整分母研究指标契约，failed/rejected/unlabeled 不删减，校准组不足不伪造区间。
- 固定 `research_only=true, formal_prediction=null, acceptance_decision=unavailable, provider_requests=0, paid_calls=0`。

原生结果库验证摘要与曝光绑定；公开 API 不接收客户端构造的评价结果。前端进一步校验结果摘要、研究组/来源/标签身份、分母和排除计数，并分开呈现特征候选及旧基线。新增 SQL 仍是 fresh-only 可选文件，不新增授权，也不改变已封存部署。
