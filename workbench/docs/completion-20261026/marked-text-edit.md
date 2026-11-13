# B7：固定来源单标记文字叶修订

状态：实现、最终隔离原生验收及本地总门已完成，提交后仍须按精确提交核验远端 CI。此文件不修改或扩大 B5/B6 的冻结定义。

## 范围

只允许当前固定来源章节中已有 paragraph／heading、恰好一个 text 叶、已有非空且无重复的 bold／italic marks。用户只提供新的非空文字与理由；不能提供或新增 marks。替换文字拒绝空白及 C0／DEL 控制符（包括 CR／LF）。服务器从不可变父正文复制，仅改该叶 text；marks 数组及顺序、节点 ID／attrs、其余结构、来源与要求引用原样保持。

普通纯文字仍走 B5/B6。多 run、hardBreak、结构重建、图片和表格不属于 B7 目标；不将此能力称为完整富文本编辑或复杂 Word 保真。来源证明不认证人工文字的业务正确性，也不授模型或正式评分资格。

## 加法协议

- 新请求 `authoring-exact-marked-text-edit/1`；共享已有 exact-text-edits POST，但显式协议必需，不接受客户端格式／来源权威。
- 新 method `authoring-exact-text-edit-policy/3`、manual manifest `/3`、origin `manual_marked_text_edit`、result `authoring-exact-text-edit-result/3`。原 marks 数组摘要 `preserved_marks_digest` 连同完整原节点、原／新章节、命令与 before_action 摘要进入证明。
- 新能力单独由 GET `/authoring/exact-marked-text-edit-capabilities` 暴露；原 GET plain 能力继续只返回原 v1/v2，不以新格式替代旧客户端约定。新能力须旧来源／构建扩展与 B7 SQL 实际安装、权限就绪才 available。
- 新 SQL `authoring-exact-marked-text-edits.sql` 明确在 B6 后安装，并在任何 CREATE 前核对 B6 single／multi／dispatcher 前置函数；缺失则整笔回滚，不覆盖旧校验器。它增加私有独立重建校验器和 `/3,/2,/1` 分派；旧 B5/B6 SQL 文件不改，不增加 API／Worker 直接执行私有函数的权限。
- 仍复用原重放优先、事务外原件读取、最终授权和 CAS。未知回执保留原 body／key／ETag；历史 proof 按捕获时的 policy/source hashes 核验，不要求旧 hash 等于当前源码。根／父链及 snapshot／build 守卫继续成立。

## 跨语言边界

B7 的非空白判断显式统一 Unicode 空白集合加 BOM。理由允许有意义文字中的 TAB／LF，但拒绝其他 C0 和 DEL；替换文字拒绝全部 C0 和 DEL。原文与理由均不因空白判定而被改写。PG17 原生查询证实 POSIX 空白类不会识别部分 NBSP／NEL，独立 SQL 因而使用显式字符集合，不依赖 locale；旧 B5/B6 不追溯修改。

## 当前核对

以 `58eb81f` 为基线逐字节核对旧 B5/B6 SQL 与 `exact_text_edit_contracts.py` 未变；现有 OpenAPI 组件 schema 改动 0，只新增 B7 类型／路径及实际 response union。整合纯逻辑、旧协议与实际 OpenAPI 快照在 Linux 运行时为 133 项通过、1 项因运行时无 Node 跳过；该 Node 生成检查连同 OpenAPI 在主机另行 4 项通过。Windows 主机同一整合组有既有 Unix socket 路径语义断言不兼容，未改写或放宽此断言。B7 前端最终聚焦 80 项、类型与 lint 通过。最终安装保护版本非 owner PG/S3 118 项通过，0 失败、错误或跳过；前后策略与全部 Python／SQL／测试源码摘要一致（b8971eeb…045b）。覆盖 B5-only 错序安装回滚、B6→B7 正确安装、旧链与真实 DOCX 的 bold／italic run；CI 已强制包含两个 B7 原生模块。前端聚焦 80 项及 1440／390px 八组 Chrome 回放通过，普通正文只读、未知回执重试及 GET-only 恢复保持。Chrome 为本地 HTTP 回放，不是实时数据库或真实复杂 DOCX 业务验收。

全量前端 224 文件／2,258 项通过（显式两 worker）；格式、lint、类型与构建通过。默认并发的前一轮曾出现旧保存恢复用例等待超时，该组独立 8 项及两 worker 全量均通过，未改其断言或生产逻辑。

全局 Python Ruff／格式检查及 Linux 平台 mypy 通过（813 个源码文件）；Linux CI／安全门禁测试为 132 项通过；主机为 131 项通过、1 项同上述 Unix socket 路径断言不兼容（100 项安全门禁测试全部通过）。安全门禁纠正旧 Bandit 逗号目标导致的零覆盖，改为逐一绝对目标并验证扫描错误、正覆盖与核心文件锚点；真实扫描 151,218 行／804 文件。两个既有常量 SQL 锁子句误报仅按完整源码 SHA256、文件、规则、位置和严重性／置信度精确复核，不跳过 B608 规则，不改写旧业务源码；新增、变更或失效的例外均失败关闭。

B7 与本轮测试均不需要外部模型、真实 DOCX 或付费调用；原生夹具明确为合成输入。隔离容器及本轮两个必要镜像已在使用完后精确回收（核验剩余镜像、容器均为 0），用户原有数据、卷及 docs 改稿保持。

## 原生夹具表示

保留原始导出 SHA256 `f9aaa2f8b9902a7db00d7a0d1ed88e4e5e01f3532c5d83a201a37337bc4e5ba9`。仓库测试夹具仅按 Prettier 重排 JSON 空白，解析后逐字段完整相同，格式化文件 SHA256 `b962f9bd3deea59e3adb790aaad7e08efbada46de9fb374c088f9226fe425fe4`；没有改写 UUID 操作键、摘要、来源或回执数据。原始文件与对照留本机，不将格式化后的字节冒称原始字节。
