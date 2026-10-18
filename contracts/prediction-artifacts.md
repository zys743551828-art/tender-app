# 评分明细与模型方法契约

评分明细仍使用 `prediction-v1`，接口响应和 SQL 结构不变；JSON 字段为向后兼容的补充。产物通过任务与快照关联到冻结的规则、正文版本及解析证据。

| 字段 | 约束 |
| --- | --- |
| `input_method` | 当前为 `complete-chapters-2`；旧产物缺省解释为 `legacy-truncated` |
| `prompt_version` | 当前 p4，保留实际调用的模型和用量 |
| `mapping.sections[].parent_id` | 父节 ID；根节为空；父节证据包含其全部子节 |
| `items[].effectiveness`、`consistency` | `status` 为 supported／weak／contradicted／unclear，附 note 与 evidence_ids；无有效引用的非 unclear 判断降为 unclear，矛盾须两个不同 ID |
| `items[].context_coverage` | mode 为 full_text 或 section_readings；source 为 mapped_sections 或 whole_document_fallback；记录完整输入的 evidence_ids、chars、valid_judgements |
| `context_coverage.readings[]` | 分节方法的独立重复编号、原文分节状态及整体读取状态；每个部分含编号、证据 ID、字符数、read／failed／unread 与失败原因 |

当前正文按物理页稳定排序，保留同页原顺序。只有原生 text 用于标题及章节映射；已核验 table／visual_observation 不充当标题。存在这些摘录且章节归属未经核实时，所有评分条款跳过章节映射，使用完整冻结正文回退，保留全部原生文字及已核验摘录，不将后追加的候选误挂到末章。`mapping.reason=verified_nontext_section_unknown`、`verified_nontext_evidence_ids` 记录回退原因及冻结证据，context_coverage 继续使用 whole_document_fallback；不拼接跨页结构或读取未核验图片。旧输入方法 complete-chapters-1 的模型不校准当前方法；历史产物和快照保持。

输入超过单次 24000 字时按原顺序分节，单个长块也不截断字符。每次独立判断重新读取全部部分。最多 128 部分，综合记录最多 60000 字；超限或引用校验失败让该次判断不可用，不抽掉内容后继续评分。分节记录不是无损原文；图页、表格结构等未解析内容仍是缺口。有效重复数和局限必须如实显示。

`scoring-model/1` 增加可选字段 `input_method`（缺省 legacy-truncated），以及 `evaluation.acceptance.status`（passed／not_passed／not_evaluable）。字段参与原有规范 JSON 的 model_id 摘要。业务登记和当前方法应用要求同方法、独立时间留出 `mode=holdout`、原有评测 passed 与融合门槛 passed；缺少这些条件的旧模型保留追溯，不校准当前方法。数值特征仍为 pf-1，不能只凭特征键相同认定方法相同。

研究侧协议新增可选 `acceptance`；当前示例明确填写六项量化门槛，旧冻结协议缺省不变更历史判定，但融合验收记不可评价。格式 B 通过 `artifact_extra.input_method` 传递方法，混合方法不通过统一评测；导出模型保留方法与验收结论。正式成绩质量、图页覆盖和新校准输出稳定性仍需真实数据与影子运行验证。
