# 图表图注锚点协议：阶段一

继续开发前已核对所有远程 heads：独立分支为 `9d6df22`，原 PR #2 源为 `90444507`，fusion 目标为 `462ec226`，无新增远程并行提交。本轮仍不创建 PR、不合并、不部署、不调用付费模型或生产库。

## 实现与兼容

- 新增 `rich_captions.entries`，以冻结结构的节身份和图表节点 ID 生成 `cap_`＋32 位摘要书签名。相同图注文字、相同素材重复使用仍有独立身份；编辑文字不改变节点锚点，manifest 的完整图注条目摘要随文字改变。
- 书签 ID 使用 501–1500，章节继续使用 1–500，最多 1000 个图注。冲突或超限拒绝；原任意节点字符串不直接写入书签名称。
- 生成器把书签包围在紧随图／表的独立图注段落内。验证器要求严格的命名空间、ID 范围、起止配对及段落位置；图注不能作为任意内部超链接目标。最终仍精确重生成整个 DOCX，不能换名字并重算 manifest 来绑定其他对象。
- 生成协议 `authoring-generated-rich/3` → `/4`；RICH sandbox `/4` → `/5`。源、生成器、验证器、图注 manifest 与 profile 摘要均绑定。旧协议/旧字节不会被重新解释为新资格，需明确重新生成及新受审 profile。外部 Word03 和 PAGE 路径不放宽。
- 本阶段只完成源文档协议。存在图注时保留 `AUTHORING_CAPTION_PDF_UNVERIFIED`，不凭 DOCX 书签宣称 PDF 位置已通过；实际 PDF 检查为下一阶段。

## 实际验证

相关九文件回归 **168 passed / 0 failed / 0 skipped，3.43s**。新增八项覆盖重复文字、锚点稳定、非法名称/ID、缺少结束、嵌套/错位，以及重算 manifest 后提交旧字节/旧协议的拒绝。

完整默认回归 `python deploy/ci_checks.py --suite unit --report-dir .local/ci/caption-anchors`：**3838 passed / 0 failed / 0 errors / 2389 skipped，187.36s**。专项与全量重叠，不相加。完整 ruff、format（1075 文件）、mypy（672 源文件）、bandit 通过。开发中 ruff 的 fixture 导入冲突和 mypy 的列表类型提示已修正，保留最终通过结果而非省略质量检查。

跳过项仍是显式隔离原生/历史档案/转换或模型环境依赖，不能计为通过。未运行新的真实 DOCX→PDF、原生 PG/Kafka/S3、前端单测或远端 CI；没有修改前端和基础服务。完整转换、新 profile 受审、跨页复杂表格及 M1 全稿仍未验收。
