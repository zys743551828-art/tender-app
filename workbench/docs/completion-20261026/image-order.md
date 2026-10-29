# 本地增量：冻结图片顺序与 PDF 几何验收

日期：2026-10-26。基于 PR #2 head `9044450711f0b32323821ccd7b6ef8ea246119e3`，在独立 worktree `/workspace/tender-render`、分支 `render-acceptance-20261026` 完成。仅本地成果，未推送、发布、部署或合并。

## 状态核对

- 初始 `/workspace/tender-app` 是干净的 `work` 分支、`88d35bb`，不是当前 PR head；保留该 checkout，在 fetch 后从已核对的 head 创建独立 worktree。
- GitHub API 确认 PR #2 仍开放，源分支 `work/completion-20261025`、目标 `fusion/bid-workbench`。开始与结束时远程源 head 均为 `90444507`，目标 head 均为 `462ec226`。这些只证明核对时的公开状态，不能证明没有未推送的其他会话工作。
- 实际读取 run `40251959558` 的八个 job，均为 completed/success。这是原 head 的 CI，不是本地增量的 CI。
- 已读 `workbench/AGENTS.md`、仓库 README/交接、当前阶段说明。检索未发现适用的 `.agents/skills` 或 SKILL.md，工作区根 `.agents` 为空。AGENTS 引用的文档仓库 `00-项目管理/实施任务板.md`、`团队协作与质量准则.md` 本地不存在，远端 `fusion/bid-workbench` 对应路径也返回 404；没有改写冻结主记录或推断其已同步。

## 具体问题与修复

旧图片检查逐个验证实际像素、尺寸、版心与可见性，但采用 PDF 对象绘制顺序匹配，没有核对冻结稿的图片阅读顺序。因此，两张不同图片即使在同页或跨页互换，仍可获得图片 `complete`；两张并排图片、完全重叠的相同图片也可通过。

现在每页最多收集 501 个图片对象（第 501 个用于触发原有 500 上限），按实际矩形从上到下排序后匹配冻结图像。逐页结果必须与冻结图片节点顺序一致；同页相邻图片矩形必须在纵向不重叠。并排、重叠或交换位置返回 `AUTHORING_IMAGE_ORDER_UNVERIFIED`，保持 `partial`。相同素材的多次使用按实际阅读顺序分配，PDF 内部反向绘制不会误报顺序失败。现有像素、可见性、总数与预算检查继续生效。

该接受域依据现有生成器的单栏独立 inline 图片段落；没有把并排图猜成某一种阅读顺序。图片证据协议升为 `authoring-PDF-raster-correspondence/2`。RICH profile 新增明确图片布局策略，既有 adapter/raster 源码摘要同时改变。重新散列的错误策略或旧检查器摘要在 Docker 前拒绝，需另行审核生成匹配的新 profile；不修改既定 Word03 基础身份。

## 可重复验证

使用 `requirements-fusion-checks.txt` 安装的隔离 `.venv`，真实 PDFium/Pillow 处理合成 PDF 字节。没有以模拟转换结果冒充 LibreOffice 转换。

修改生产代码之前新增图片测试：**5 failed / 7 passed**。四个反例因旧检查错误报告 complete 而失败；另一个反向绘制顺序例暴露证据列表不是几何顺序。该失败是修复前证据，不是当前遗留失败。

最终执行：

```bash
cd workbench
.venv/bin/python -m pytest -q \
  tests/test_authoring_rich_image_order.py \
  tests/test_authoring_rich_visibility.py \
  tests/test_authoring_rich_renderer.py \
  tests/test_authoring_rich_table_pdf.py \
  tests/test_authoring_rich.py \
  tests/test_authoring_page_navigation.py \
  tests/test_authoring_generated.py
# 139 passed in 2.77s; 0 failed, 0 skipped

.venv/bin/ruff check packages/authoring/rich_pdf.py packages/authoring/rich_renderer.py \
  tests/test_authoring_rich_image_order.py tests/test_authoring_rich_renderer.py
.venv/bin/ruff format --check packages/authoring/rich_pdf.py packages/authoring/rich_renderer.py \
  tests/test_authoring_rich_image_order.py tests/test_authoring_rich_renderer.py
.venv/bin/mypy packages/authoring/rich_pdf.py packages/authoring/rich_renderer.py
.venv/bin/bandit -q -ll packages/authoring/rich_pdf.py packages/authoring/rich_renderer.py
# 均通过
```

139 包含新增 15 项：12 个实际图片几何用例、两个 profile 拒绝用例、一个实际组合检查入口用例。组合用例验证图片顺序缺口向 RICH 顶层传播，同时保留合成图片 PDF 缺少正文、目录的其他缺口；不将各组重复累加。最终 JUnit 存于本地 `/tmp/tender-image-order-tests.xml`，修复前输出在 `/tmp/tender-image-order-before.log`，临时路径不作为长期档案依赖。

## 仍未验收／未运行

- 此检查仅证明图片间顺序，不能证明图片在正确章节、标题或图注旁，也不证明表图混合相对顺序、任意复杂 Form XObject 或业务语义。
- 完整 DOCX→PDF、固定 Word03 镜像来源、新受审运行 profile、复杂跨页表格、目录/页码联合闭环及 M1 全稿验收仍未完成。本轮未运行 Docker/LibreOffice 转换。
- 未运行全量后端、前端、原生 PG/S3/Kafka 或新的远程 CI；本轮未修改前端、数据库、消息链路或部署配置。已有 CI 不能替代本次变更后的检查。
- 未使用付费模型、生产数据库、真实成对评分数据；未新增凭据或权限。正式评分、整包正向提交、生产恢复与完整用户验收不因本次修复获得资格。
- 文档仓库同步仍未完成核实；仅更新应用仓库本地阶段记录。无待确认的远程写操作。

## 交付前追加复验

后续已执行完整默认回归，补齐数值边缘和图片所属节定位；本页“未运行”与图片章节边界描述仅代表首轮状态。最新事实、原失败与图注剩余条件以[交付前完整复验](image-order-followup.md)为准。
