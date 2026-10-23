# 核查报告与受控字体渲染验收

## 本批实现

- 核查报告使用独立、确定性的 OOXML 写入器，不受可编辑正文的章节数量上限影响。报告保留全部已列条款、双侧原页引用、人工意见快照和版本摘要。
- 报告固定标注部分覆盖、效果未测量、导出时未重新核验当前来源；人工意见和机器判断分别呈现，副本用途为 `review_report`。
- 报告的分册、适用范围及已知限制以中文说明呈现，保留分册标识和原页信息，不输出 Python 对象表示。
- PDF 转换从已冻结字体文件复制确切字节到私有目录，以独立 Fontconfig 配置供转换进程使用。字体摘要在读取后再次核对，不依赖宿主机的默认字体目录。
- 真实转换发现的封装兼容缺陷已修复：OPC 内容类型与关系元数据改用默认命名空间；不修改 ElementTree 全局命名空间注册表。

## 实际验证

| 层次 | 结果 |
| --- | --- |
| 报告及字体回归 | `test_package_review_reports.py` 和 `test_authoring_font_profile.py` 开启真实转换：16 项通过 |
| 既有正文实际转换 | `test_real_libreoffice_pdf_has_expected_physical_text_and_chain`：1 项通过，验证中文、英文、物理页和转换摘要链 |
| 完整性容量 | 400 条要求、每条两侧各 20 个引用的 OOXML 测试通过；检查全部 16,000 个引用及最后一项，没有截断或按界面筛选省略 |
| 实际报告样本 | 五种机器状态、人工复查意见、三份受检文档的显式合成报告生成 6 页 PDF；逐页渲染并目检中文、长摘要换行、页码、引用与章节，没有缺字、重叠或裁切 |
| 静态门 | 报告 writer、reporter 与 authoring renderer 的 Ruff、格式、mypy、Bandit 通过；XML 标准库仅用于序列化，未解析外部 XML |

实际渲染使用 LibreOfficeDev `26.8.0.0.alpha0`（版本标识 `2c87e51eeaa2b413ff4ae097b2705eea1995d8e5`）及 Noto Sans CJK SC 字体文件，字体 SHA256 为 `2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b`。执行命令：

```bash
WORKBENCH_ENV_FILE=review-readonly \
RUN_AUTHORING_RENDER=1 \
AUTHORING_FONT_PATH=/absolute/path/to/NotoSansCJKsc-Regular.otf \
python -m pytest tests/test_package_review_reports.py tests/test_authoring_font_profile.py -q
```

真实转换回归在缺少显式 `RUN_AUTHORING_RENDER=1` 时跳过；跳过不代表转换能力已经验收。

## 验收边界

- 测试文件全部为合成数据，实际模型调用为 0。此处验证文件生成、排版和来源身份机制，不验证真实标书的判断准确率。
- 本地转换诚实保留 `RENDER_SANDBOX_NOT_ATTESTED`；生产环境仍须提供无网络、非 root、只读根目录、资源受限的转换封装并验证该运行配置。
- 400 条极限测试验证的是完整 DOCX 内容写出，不表示所有极端报告都已在 PDF 转换时限和输出大小限制内完成；转换失败不能伪造 PDF 成功，Word 能力与 PDF 结果独立。
- 新用途仍要求当前生成物资格有效；历史报告和历史文件下载不重新解释为可再次用于编写、核查或投递。
