# 要求与事实依赖评估

`package-input-dependencies.schema.json`描述只读依赖评估，不代表保存记录、当前事实资格或任务已实现。`package_input_dependencies`只计算准确冻结要求与原准备事实的依赖缺口；`bid_package_input_dependencies.observe`在单一RR／READ ONLY事务读取两个已校验packet、明确事实消费选择及依赖声明，不读对象、不写Command、Outbox或业务记录。

正式接口为 `POST .../{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/dependency-check`，需要Session、Origin及CSRF，返回HTTP200，不要求幂等键。`CheckPackageInputDependencies`只接受准确prepared摘要、prebid_compliance用途、明确fact_ids和逐条dependencies；usage摘要由服务端从私有准确事实构造，拒绝客户端附加或猜测该SHA。接口不持久化草稿，不创建命令或任务；重复核对同一原输入和同一标注结果一致。

每条依赖声明绑定准确要求ID及摘要，明确`unknown`、`not_needed`或`required`，给出理由与原规则的权威原页证据；所选事实仅能来自同一prepared的原事实集。不从名称、确认数量、覆盖状态或空选择推断事实需要。使用`not_needed`或`unknown`时不得夹带事实；`required`的空列表表示已知缺少所需事实，列表含未选项时报告准确缺项，不能自动消费原事实池中的其他值。声明依据必须同时属于原规则的证据ID和冻结权威解析，不能拿本方证据或其他规则的证据替代。

| 评估状态 | 含义 |
| --- | --- |
| `unknown` | 未作逐条声明、声明为未知，或要求来源尚未证明；空要求清单同样未知 |
| `missing` | 已明确需要事实，但没有对应事实，或原事实未被本次选择消费 |
| `selected_unvalidated` | 依赖事实已被选择，当前事实决定、来源效力及适用声明仍须独立核验 |
| `not_used` | 针对准确规则有人工明确的本次无事实依赖声明；不是客观语义或清单完整性认证 |

依赖声明为`human_dependency_annotation`。所有要求已作明确声明时，`dependency_review_status=declared`仅说明声明覆盖，不表示事实真实、要求抽取完整或合规通过；未声明项保留，不被静默丢弃。原覆盖观察单独展示，`verified`／`not_applicable`不豁免事实需求核对。实际提交过全部冻结原页的抽取记录仍标记质量未测，`inventory_complete`、原件字节／事实资格／评审／执行／发布恒false。

输出按要求ID排序，声明内事实和证据ID按集合排序；摘要绑定准确prepared／冻结／清单、实际选择、声明及评估政策源文件。返回副本，不泄露未消费事实值、证据正文或原件定位；当前版本为可重算候选，未追加历史，不把按当前政策重算当作原时点精确记录。保存与正式运行须各自的命令／审计及当前条件复核。

前端显式读取原清单，按原文逐条标注，复用准确prepared事实目录按名称和值选择。声明为所需事实与本轮实际消费分别选择，不自动消费原事实池。未应用编辑时不能计算，输入改动使旧评估失效，换prepared忽略迟到响应，失败保留当前页面草稿供显式重新计算。界面明确草稿只在当前页面、计算不保存不启动；规则长摘要显示截断，全文与原页入口可展开，局部样式随组件宽度适配。
