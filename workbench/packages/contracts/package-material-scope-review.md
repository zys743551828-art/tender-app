# 材料必要范围核验清单

`package_material_scope_review.py` 是无数据库、环境或模型副作用的私有清单构建器。输入为完整 `/3` context 及独立固定的摘要；先重建核验 context，再列出两包全部成员、全部已声明章节与清单内全部要求。它不代替独立内容核验，不产生审核决定或输入资格。

输出 `ScopeReviewPacket` 保存独立拥有的 context 与私有 metadata。metadata 的固定字段为 `version=package-material-scope-review/1`、`method_digest`、`context_digest`、`scope_digest`、`documents`、`parts`、`requirements`、`check_items`、`frozen_scope_coverage`、`state=requires_independent_review`、`cross_reference_semantic_closure=unproven`、`inventory_exhaustiveness=unproven`、五项 false（`visual_readability_verified`、`necessary_scope_verified`、`input_authority_granted`、`native_binding_verified`、`execution_authorized`）及规范 metadata 摘要 `digest`。

成员核对精确原件／解析／parser／config／物理页身份。每项保留原完整 member、全部物理页与页图资产 ID，解析质量和 gap 不被抹去。target 与 authority 的成员身份分别保留，即使引用相同字节，也不合并角色。全部原生文档必须与成员集合对应。

章节核对成员原声明、范围、全部页／证据 ID 与冻结 scope 投影，不接受重复章节、布尔长度、0 冒充 false、少页或少证据。目标章节无论选中与否都保留，非技术类别与 authority 章节同样进入清单。`declared_heading_descendant_ids` 只是同成员内原声明路径前缀关系，`unselected_declared_descendant_ids` 明确显示未选后代；不宣称等于实际标题完整闭包，不推断跨文件关系。解析声明路径不沿用人工编辑树六层限制，深层声明照实保留。

要求核对完整 inventory 中原规则与检查计划摘要、原文档绑定及已声明目标章节。评分要求集合必须与冻结技术范围规则集合完全对应；评分规则原文、档位、条件／例外、原选择与映射逐项一致。非评分要求也保留原始 binding、类别与适用性，不能在技术范围入口静默丢弃。找不到的非评分依据以 `missing_source_evidence_ids` 保留，不转换为无需检查。原排除、未知状态、缺口及覆盖声明不修改。

四类全局必核事项为：来源及补遗完整性、需求清单穷尽性、完整相关章节／附件／跨节引用闭包、原页可读性与表格。每个文档、声明章节和原要求另有必核事项。`check_id` 固定 context 摘要、事项种类与准确主体后取摘要；所有事项状态固定 `unreviewed`。页图字节齐全不表示实际可读，完整已声明清单不表示全部真实义务已被提取。

`verify` 从所属完整 context 重建全部清单后比对规范字节。即使重算摘要，删排除项、删核验事项、伪造已审核状态或 false→0 均拒绝。独立审核流程应引用这份固定清单，再由经授权的核验主体提供具体来源和决定；本模块没有“确认全部通过”开关。

容量为两包合计 4000 声明章节、2000 清单要求、100000 声明后代关系、16 MiB 私有 metadata。超过容量明确拒绝，不截断或省略分母。方法摘要固定构建器源码、context 方法及所有容量与全局必核事项。原 context／源观察／范围和旧方法不变。

范围外：公开 HTTP、UI、持久核验决定、审核者权威配置、正向原生 binding、可执行资格、发送租约、费用、模型效果及视觉验收。私有 metadata 包含完整条款与声明，不可当公开状态响应使用。
