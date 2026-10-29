# 完整材料特征交接封套 /2

这是 [既有私有交接](package-feature-handoff.md) 的显式版本扩展，消费既有 [完整材料及三槽 /3](package-technical-complete-material.md)，不改变 `/2` 旧投影、`/3` 输入／请求／判断／特征或原材料归档身份。

`package-history-feature-source/2` 引用原 `package-private-material-archive/1` manifest，另附 observation、原 `MaterialInput.metadata`、全部原始文档、请求字节／receipt、响应字节／解析元数据的 CAS 引用。原 `CompleteJudgmentAttempt` 的 rule_id、slot、attempt、call_id、state 原样保留；response 元数据由原 codec 重解原字节逐项核对，不能用另造的判断摘要替代原响应。

CAS 引用固定为 `{sha256, byte_size}`；原件条目另带 document_version_id。源封套字段固定为 version、method_digest、input_digest、binding_digest、feature_method_digest、material_archive、observation、input_metadata、originals、attempts 及资格标志。资格标志 `native_binding_verified/current_native_facts_rechecked/input_authority_granted/execution_authorized/training_eligible/metrics_eligible/formal_prediction_eligible` 恒 false。原材料归档声明仍描述其自身：原件由交接封套另行保存，绝不改写旧归档协议。

`package-history-feature-handoff/2` 命令记录固定绑定 command_id、origin、source_commit、input_digest、binding_digest、两种 method_digest、features_object、rule_count 及上述 false 标志。origin 沿用 synthetic_mechanism/unqualified_research，不证明真实性。features_object 含原 `/3` 逐规则结果和 false 标志；没有预测分、训练资格或 metrics。

消费必须提供独立预期 source/input/binding/method/命令记录摘要；不是从收到的任意 JSON 自算预期值后获取原生资格。对象和 manifest 由现有 private CAS 保存，source commit 发布前所有对象已读回复验；命令记录原子发布并保持幂等。重读重建原 `/3` 模型、原请求和响应，重算特征并比较确切字节。

受控生产者接口 `save_source` 只接既有 typed 输入和尝试；`load` 返回复验的 typed 材料／尝试／特征供研究消费者使用。CLI 见 [交付与验收](../../docs/completion-20261026/complete-feature-handoff.md)。原生注册、在线最新事实、真实调用账本、标签准入、训练／评分装配不由此封套授予。
