# 冻结清单的原范围与抽取回执

机器协议为 [package-inventory-proof.schema.json](schemas/package-inventory-proof.schema.json)。`package_inventory_proof.assess`只接受准确冻结／prepared值与可选原抽取归档，`bid_package_inventory_proof.observe`在同一RR只读快照加载它们；没有公开HTTP、持久化或任务。选择范围为 `frozen_authority_parse_blocks_only`，不能将本次已选招标包当作外部招标资料已经收齐。

原声明页段按区间并集计数，重叠不重复、缺页不填补，不按页号展开巨量数组。每个成员绑定原文件版本、原精确解析、文件／解析配置摘要及原parts；只统计准确冻结根的招标证据集合，正文块不能补招标范围。旧v1清单没有精确抽取身份时不查询后来完成的抽取，不按规则集／时间／当前头推算或补写旧根。

v2只按清单明确冻结的 `extraction_result_id` 读取原归档，不取latest。核原记录ID／项目／招标修订、input／result SHA、准确原成员／parts／scope／身份、原方法内容SHA及succeeded操作／effect receipt。用原冻结证据集合SHA核原 `read_evidence_ids_digest`；原归档缺失与集合不符分别保持缺口。标注 `source_bound` 不能替代原规则／要求投影摘要与原证据成员核对。读回只含身份、摘要、数量及状态，不返回私有正文／定位符，不读原件或模型。

`all_declared_pages_bound`描述本次冻结成员的原声明页段，`extraction_range_proven`仅表示这些范围及非空证据集合与原抽取输入／回执一致；它不证明模型实际理解每条内容或没有遗漏要求。`extraction_coverage`保留原抽取报告的complete／partial／conflict，`quality_status=not_measured`，`inventory_complete=false`。页段缺口、空证据、空清单、未绑定原文、部分／冲突与语义完整性未测分别列出，不能用依赖标注齐全、覆盖不适用或空事实选择豁免。

当前事实头、当前包头、来源有效性及新用原件字节资格不在此观察中；项目关闭／当前事实变更不会重写原根或这份原身份观察。stored绑定损坏500、请求prepared摘要不符409、范围不存在按原仓储404处理。没有原件IO，`original_bytes_verified`、事实、评审、执行和发布资格全部false。新的执行计划须另外绑定本证明摘要、实际事实消费、当前准入与预算／租约／发布复核；完整性未知不能汇总为整包通过。

职责：纯领域核原绑定与区间／证据集合、输出可重现观察；只读协调器按准确ID取得原归档并控制RR；历史原输入读取和新用资格／原件检查继续分开。后续完整性核验须保留人工补漏／未核验项和质量证据，不能将“所有已知要求都标注了”升级成完整性证明。
