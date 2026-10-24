# 准确解析与完整当前材料投影

`package_current_parse_material.observe`复用已有独立来源角色及八表／限列权限，不新增授权。调用者给定项目及确切文档、原件摘要／长度、解析ID／证据摘要、parser／config摘要和页数；未冻结解析不得用latest或时间推算补齐。每次拥有独立repeatable-read／read-only事务，先复用来源权限审计、容量与完整祖先核验，再返回全部原生物理页和证据块，重算实际返回记录的证据摘要。

原生pages保留物理页、印刷页标、宽高、旋转、质量、gaps；blocks保留ID、物理页、顺序、类型、全文、摘要、bbox及structure。几何和结构使用PostgreSQL原文本，避免浮点重写。parser／config必须与准确冻结身份相等，不能只凭原件摘要或证据摘要确认解析身份。容量沿用来源端口的32文档、256页、20000块、2MiB文字、8MiB元数据及20000节点／边／64层；每条SQL限5秒。正文放在不参与repr的私有`documents`字段，metadata只有身份摘要、计数、来源图和观察时间。

`package_current_material.collect`依次执行原生scope→准确解析／来源→全部原件完整GET→逐件原页派生→末尾准确解析／来源、scope及定位复核。scope、定位、解析使用三个独立LOGIN连接；网络及渲染前均为空闲，无数据库事务跨外部操作。完整字节读取复用现有集合端口，最多32原件、每件32MiB／合计64MiB。所有冻结成员必须有准确解析；同一文档的多个包角色保留，同文档不同解析身份目前明确拒绝，不猜选一份。

冻结scope的每页质量／gaps及每块文本／摘要／几何／表结构必须与原生记录逐项相等；派生原页的准确文档／原件摘要／长度／页数、宽高及旋转也须对应。跨版本、文本替换、错误页几何、撤回、项目关闭、方法或定位改变与超限拒绝整批结果。全量派生最多256页、64MiB资产、128M像素，材料投影最多8MiB；不截断或省略未选材料。

私有`package-current-material-projection/1`包含完整scope、目标包、依据包、清单、当前身份、原生解析记录及全部页图manifest；原件字节和PNG另放私有字段。规则的全部source_evidence、档位、条件、例外，人工纳入／排除、全部章节和覆盖缺口原样保留。metadata只有材料／观察摘要、计数及原生初末来源观察，不含文字、对象key或签名URL。

现有图文`/2`规则字段只容纳一个`source_evidence_id/source_quote`，无法完整表达这里的多来源及全部结构化档位。这个完整材料投影不擅自压缩成`/2`、不选首条依据、不截断正文，不直接交给模型；后续需要独立支持完整多来源的模型材料协议。旧`/2`、旧方法和历史记录不改写。

原页派生是受控依赖，由可信宿主注入固定渲染器。可选`deploy.fusion_current_material.FusionMaterialPages`接收明确固定的`FusionAssetRuntime`，使用现有`tender-fusion`命名服务逐份新建／停止受限渲染环境，只产整页，容器边界回执单独保存；API／Worker没有Docker入口。纯材料端不因回调或回执JSON自行授予隔离资格。

`native_parse_and_original_material_observed`与`complete_frozen_declarations_retained`仅说明本次观察／保留流程完成。renderer边界、必要范围、可读性、输入权威、执行及历史存在性均false，不注册正式binding。最终观察后仍可能变化，正式发送另需CAS／lease。正常业务库不安装可选权限，检查仅在现有Compose全新独立库初始化已有能力后清理。
