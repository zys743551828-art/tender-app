# 审核结论与原证据绑定

`package_material_scope_findings.py` 校验完整审核声明、具体范围与准确原证据，`package_scope_findings_store.py` 负责私有持久化。前者不读写文件或数据库，后者只接收受控私有存储端口；审核身份、内容权威与正向资格由后续独立端口处理。模式可由指定人员、受控程序或外部回执提供声明，不能仅凭声明格式或引用摘要视为审核通过。

原始 draft 字段闭合为 `version=package-material-scope-findings/1`、`context_digest`、`review_digest`、`reviewed_image_ids`、`findings`。所有固定核验事项必须各有且仅有一项，不能删去排除项、非评分要求或未选章节。`reviewed_image_ids` 只是声明已阅读的准确资产 ID，不证明有人实际打开或理解图片；全部事项声称确认时，必须声明全部整页及裁片，不得漏图。

每项字段为 `check_id`、`outcome`、`scope_relation`、`required_part_ids`、`reason`、`citations`。outcome 为 `confirmed`、`change_required`、`unable_to_verify`；scope_relation 为 null、`in_scope`、`out_of_scope`、`source_reference`、`retained_non_scoring`。理由须非空且不含 NUL；无法判断、缺依据与需要更改范围保持原状态，不补零或转换成确认。

引用字段闭合为 `image_asset_id`、`document_version_id`、`parse_run_id`、`physical_page`、`evidence_id`、`quote`、`rectangle`。文档、准确冻结解析、物理页与资产必须全部匹配 context。文字引用须对应原证据 ID、整页 PNG 摘要及完全逐字的原文子串，不规范化、OCR 订正或推算解析身份。纯图像引用须 evidence_id／quote 同为 null，可以引用完整页或裁片。rectangle 为 null 或 `[left,top,right,bottom]` 四个整数，使用被引用图像左上角像素坐标，零原点允许，布尔／浮点／越界拒绝。矩形只检查范围，不证明引用文字位于该区域或视觉理解正确。

确认结论至少有一份具体证据，且所引图像必须出现在已阅读声明中。文档／章节结论至少引用本主体实际页；全局来源／清单完整性须涉及每份 authority 文档，相关范围与可读性须涉及两包全部文档。规则确认必须引用其全部原始依据 ID，不能只保留首条或以同一依据多个引文冒充多来源。

目标章节确认须与原选择一致，authority 章节为 source_reference。评分要求须保持原纳入／排除声明；待分类不能确认成排除。纳入规则的 required_part_ids 须等于原固定范围并包含原清单声明目标，不能在“确认”中悄悄加入新章节；需要改变时记录 change_required，再建立新范围。非评分要求保留为 retained_non_scoring，不表示相应商务／风险义务已经完成。任何缺失原依据均不能确认。

校验结果 `CheckedScopeFindings` 保存完整 draft、来源摘要、方法、全部事项声称确认／全部图片声称阅读／范围变更状态。`reviewer_identity_verified`、`semantic_completeness_verified`、`necessary_scope_verified`、`native_binding_verified`、`input_authority_granted`、`execution_authorized` 均 false。全部声明一致不证明内容真值；审核主体须另以经过配置的权威身份，对这份准确声明及材料承担审核结论。请求不接收 reviewer_id 或资格布尔。

容量为原 draft 8 MiB 保守编码预检、100000 个节点、64 层 JSON 结构、每事项2000份引用、理由8000字符、逐字引文16000字符；拒绝浮点、非规范类型、重复引用、循环或超量，不截断。复验从原完整清单重建校验，重算摘要不能伪造身份／语义／执行资格。方法固定源码、清单方法及全部容量。

持久化先复验结论，保存规范结果对象并读回核对，最后发布小清单；清单固定 context／review／结论摘要、对象摘要／长度及存储方法，身份与输入／执行位仍 false。读取接收独立固定的清单、结论及方法摘要和所属完整清单，关闭重开后重新校验全部引用和声明。存储对象上限为 draft 预算加4096字节，不存身份秘密、私有定位或模型密钥。保存与读取不授审核者身份或正向原生资格。

范围外：实际人工视觉审核、审核者资格与身份配置、原生权威回执、正向输入登记、UI、费用或发送许可。合成“确认”只验证绑定机制，不代表任何真实项目获批。
