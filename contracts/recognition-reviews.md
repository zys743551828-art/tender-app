# OCR／表格候选的人工核验

入口为资料列表的“核验候选”，或原件查看中的“核验识别候选”。核验只对当前采用的文件版本、当前解析和非 text 候选生效。官方结果资料、旧稿、旧解析和仍有解析任务的资料不能修改；历史证据和历史报告仍可读取。

`GET /files/{version_id}/recognition?offset=0` 返回当前解析身份、可核验状态、缺口、候选总数／待核验数、每页 20 条候选及最近 20 条核验记录。原件页码、坐标、文件 SHA 与摘录沿用 EvidenceRef。无候选不表示扫描识别成功，应按缺口补交可复制文字的 PDF。

`POST /files/{version_id}/recognition:review` 沿用会话、CSRF 与幂等，要求 `expected_parse_id`、`evidence_id`、`decision`（accept／correct／reject）、说明、已核对原页和数字确认标记。只有 correct 可提交 `corrected_quote`（1—2000 字且不同于当前摘录），不能包含无效控制字符；原页必须核对，确认／订正涉及数字、中文数词、百分号或千分号时另须数字、符号与单位确认。排除候选仍须原页核对与说明。表单改动订正内容会清除之前的核对勾选。

项目锁内重新检查资料、解析和候选身份。每个决定追加 `recognition_reviews`，并产生新解析和整组新证据 ID，保留原件页码、坐标、类型、顺序与未改条目的内容。确认／订正的结果标 supported，排除标 unsupported；从未更新原 evidence。记录包含父／结果解析、源／结果证据、全组 ID 映射、操作者、说明与时间；派生产物也保存父解析和映射，原产物字节先核验 SHA。表与来源外键、授权及只追加触发器见 [recognition-reviews.sql](recognition-reviews.sql)。

相同幂等键重放原响应；新键提交旧解析返回 409 `recognition_parse_stale`。当前资料变化返回 `recognition_source_stale`，解析进行中返回 `recognition_parse_running`；错误证据或 text 条目返回 404。未核对原页／数字、无效订正等返回 422。单次派生上限 20,000 条证据，超过则明确拒绝；这不是生产容量验收。

核验结果继续使用 [快照身份](snapshot-parse-identity.md)和[规则来源](rule-parse-identity.md)约束。旧 manifest、证据、报告保持，当前规则来源变化需重新提取；若订正／排除改变已确认事实的证据，冻结新输入前返回 `recognition_facts_stale`，要求核对并登记新的事实集。相同文字的普通证据复制不使事实失效。核验只更新状态与审计，不自动发起模型或新评审，用户完成核对后走正式评审入口。

派生解析始终 partial，保留原生文字、图片与识别失败缺口，不宣称整页／表格关系／图形语义完整。纯识别资料须完成所有候选核验且每个物理页至少有可用证据，才解除 `recognition_verification_required`；排除唯一可用候选会恢复阻断。原生文字字数统计不改成 OCR 全文字数。新 ID 的可选向量索引需重建，索引不完整时沿用已有关键词回退；默认 keyword。

晚到的旧解析任务在项目锁内检查核验时间：任务创建后已有人工核验时，保留任务产物但不覆盖当前解析。并发核验同一父解析只有一次能生效，另一请求必须刷新重新核对。[表格结构与可能续表](table-structures.md)可只读预览，仍属待核对候选；真实表格关系、图形语义、OCR 准确率及浏览器整轮视觉另行验收。
