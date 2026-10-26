# 阶段三：图表混排顺序与所属节

承接远端 `88e3e4c21619df45f34f92f73ee565b32a0d3531`。此前图片和表格各自核对顺序，即使两类对象相互交换仍可能分别通过；原图片所属节检查也没有覆盖表格。新增 `rich_layout.inspect_layout`，直接组合同一次实际 PDF 的原生对象与导航测量，不接受外部自报成功记录。

## 实际改动

- 按冻结源码的节与块顺序交错展开图片和表格，通过各类型的准确序号绑定原测量记录；不假定节点字符串跨节全局唯一。
- 任一原始对象检查不完整时整体布局保持 partial。联合序列必须按物理页递增，同页对象纵向不重叠，保留 0.001 pt 数值容差。并排对象不凭左右位置猜成单栏源顺序。
- 图片和表格都必须在当前节实际标题之后、下一先序节之前。导航不完整或连续分页时保留归属缺口，不借用父章节包含子章的页范围。
- 证据只输出对象类型/身份、节身份、物理页与矩形。顶层合并布局缺口，`layout_inspector_digest` 绑定新源码；当前生成协议 `/4`、sandbox `/5` 不变，旧 profile 仍需重新审核生成。

新增十项实际 PDF 混排用例和一项 profile 摘要拒绝用例。正例覆盖图→表、表→图；负例保持原图、表、图注、章节导航分别完整，单独制造混排互换、并排、移入目录，验证新联合门确实拒绝。另覆盖连续分页、像素失配原对象及组合入口缺口传播。

## 检查结果

相关十一文件 **203 passed /0 failed /0 skipped，4.58s**。完整后端 ruff、format（1079文件）、mypy（674源文件）、bandit 通过。最终完整默认回归 **3873 passed /0 failed /0 errors /2389 skipped，188.80s**，退出码0；包括阶段二最后的组合预算强化，专项与全量不相加。报告位于 `.local/ci/rich-layout/`。跳过项保持原生依赖及历史档案边界，不计为通过。

复现：

```bash
cd workbench
.venv/bin/python deploy/ci_checks.py --suite unit --report-dir .local/ci/rich-layout
.venv/bin/python -m pytest -q tests/test_authoring_rich_layout.py \
  tests/test_authoring_rich_caption_pdf.py tests/test_authoring_rich_captions.py \
  tests/test_authoring_rich_renderer.py tests/test_authoring_rich_table_pdf.py \
  tests/test_authoring_rich.py tests/test_authoring_rich_visibility.py \
  tests/test_authoring_rich_image_order.py tests/test_authoring_rich_image_sections.py \
  tests/test_authoring_page_navigation.py tests/test_authoring_generated.py
```

## 实测外部条件与下一项

本阶段实际执行只读命令：

```text
docker image inspect sha256:327daa8fae7178d61f93142f146b098467b345e10997b9eb79f63bd58e5c8f3c --format '{{.Id}}'
Error response from daemon: No such image: sha256:327daa8fae7178d61f93142f146b098467b345e10997b9eb79f63bd58e5c8f3c
```

结果明确为缺镜像（退出码1），不是权限拒绝或运行结果不确定。没有尝试启动替代镜像、重打同名标签、扩权或伪造原基础身份。完整新协议 DOCX→PDF 联合验收仍需获得该固定受控镜像的可复现来源，或另行审核新的转换基线及 profile；本轮不自行更换已冻结安全根。

下一可继续编码范围为跨页图注/跨页表格的明确接受域与反例、分页收敛及运行时装配；这些不能由本次同页检查自动获得完成资格。尤其需实际转换样本确认图注 named destination 的保留、重复表头、行拆分、纵向合并跨页与目录页码行为。新图注协议、检查器及混排已可审查，但没有声称整个项目代码、真实效果或 M1 完成。

原生 PG/Kafka/S3、生产恢复、真实评分和正式整包提交仍未验收；默认跳过保持原因。没有创建 PR、合并、部署、调用付费模型、连接生产库或新增运行权限。本记录截止本阶段检查点，后续任务保留。
