# 输入快照的解析与证据身份

`input-v2` 清单包含 `parse_inputs`：以文件版本 ID 为键，每项明确保存 `parse_id`（未解析为 null）、`page_count` 和按文档顺序排列的 `evidence_ids`。`coverage_gaps` 与这些解析在同一数据库语句的可见范围内读取。上述字段与规则包、事实集、Word 来源一起参与清单 SHA-256；数据库的 `parse_inputs_json`、`coverage_gaps_json` 为同一次冻结的副本，由既有只追加触发器保护。迁移见 [snapshot-parse-identity.sql](snapshot-parse-identity.sql)。

检索、诊断、评分、改稿只读取所选文件版本中已冻结的证据 ID，继续应用原有非文字证据核验条件。相同文件的新解析、甚至同一解析后来追加的证据，都不进入旧输入；原证据不改写。评分页数和成绩配对导出的解析统计也按冻结解析读取。当前资料检索只读每个文件版本的最新解析，排序为 `created_at DESC, id DESC`。

新快照响应 `parse_identity=frozen`，`parse_ids` 提供文件版本与解析 ID 的映射。流水线复用快照时比对当前解析、页数与完整证据集合；变化后显示 `parse_identity_changed`，用户发起新版评审时生成新快照。登记新的提交要求解析身份仍为当前值。

`input-v1` 的原行、清单字节、SHA-256、报告、证据和既有提交／成绩保持。迁移不按时间回填解析身份：旧行两列均为 null，响应 `parse_identity=legacy_unfrozen`、`parse_ids={}`。读取覆盖缺口时从校验过的原清单读取，并附加 `legacy_parse_identity_unfrozen`，不把最新解析的缺口冒充历史值。报告显示历史身份说明。

旧快照不能进行按完整输入重放的检索、新诊断或新改稿，接口返回 409 `snapshot_parse_identity_unknown`；遗留评分／诊断／改稿任务执行时返回同名失败码。旧快照不能登记新的提交，返回 `snapshot_parse_stale`。历史成绩配对仍能导出文件和既有结果；无法证明精确解析身份的格式 B 标记失败，页数与字数不从新解析补入。需重新评审时，沿用实际材料建立新的 `input-v2` 快照，原报告仍可读取。

规则提取与规则包的来源约束见[规则解析身份契约](rule-parse-identity.md)。此契约是候选核验的前置保护；候选采用／订正尚未开放，后续接入追加核验记录、过期检查、审计和界面，再验证新核验不会改变历史输入。扫描表格结构、跨页关联与图形语义质量另行验收。
