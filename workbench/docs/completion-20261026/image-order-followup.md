# 图片顺序复查、章节归属与完整默认回归

本地分支 `render-acceptance-20261026`，承接 `d644442`。本记录更新[首轮图片顺序验收](image-order.md)中的未运行范围，保留首轮结果，不把旧 CI 记为本次 CI。

## 复查后的实际代码增量

1. **浮点共享边缘。** PDFium 矩形使用 float32；受检页最高 1500 pt，共享边缘可能因矩阵运算有数个 ULP 的差异。图片顺序比较加入 **0.001 pt** 数值容差，并纳入 RICH profile。实际 PDF 用例覆盖 10 pt 间隙、零间隙、0.0001/0.0005 pt 微差与 0.01/0.1 pt 重叠：前四者通过，后两者保留顺序缺口。该容差不改变既有逐像素可见性检查。
2. **同素材复用。** 用同一个真实 asset/version 在两个不同节点重复放置，验证同页、跨页及逆向绘制都不会误杀。已有并排、全重叠、不同图片交换、重复像素与资源预算回归继续执行。
3. **图片所属节定位。** 新增 `inspect_image_sections`，只使用同一次 `rich_renderer.inspect_pdf` 从同一实际 PDF 获取的图片与导航证据。冻结章节身份来自 `structure_model.ordered(snapshot.authoring_structure.nodes)`，与生成器的先序展开保持一致。要求图片检查完整、导航定位完整、`chapter_start_new_page`，并精确对应冻结图片/章节序列。
4. **节正文范围。** 以当前节起始页至**下一先序节起始页之前**为范围；不使用可能包含子章节的 `end_page`。起始页图片必须在已测标题矩形下方，标题矩形原有 0.01 pt 舍入只使用相同量级容差。父节图片移入子节、子节图片移到下一根节、图片放入目录或标题旁，即使图片像素和全稿图片顺序都正确，也产生 `AUTHORING_IMAGE_SECTION_UNVERIFIED` 并传播到 RICH 顶层。
5. **保守边界。** 连续分页、缺少目录目标/标题、图片本身不完整时不猜章节归属。没有图片时不增加无关资格门。此检查是内部同调用证据组合，不提供客户端自报成功入口，也不授予新的转换、评分或提交资格。

章节专项使用真实合成 PDF：实际目录链接、named destination、标题字形和嵌入图片都由 PDFium 读取。成功例包括同节延续页、末节延续页；负例保留正确像素与导航来证明新增归属检查确实捕获遗漏。接入初测曾因将 `section_id` 当作正文块字段而失败（1 failed / 44 passed），已改为实际冻结结构节点来源；mypy 初次发现结果字典类型不明确也已修正。这些中间失败不隐去。

## 全量检查及首次失败修正

按 `.github/workflows/workbench-ci.yml` 后端默认任务执行：锁定 Python 依赖、`pip check`、原公开固定 OCR 词典下载及摘要校验、本机已有 Tesseract/CJK 字体、锁定 npm 依赖与真实生产构建、`deploy/ci_checks.py --suite unit`。runner 会剔除业务配置、DSN、模型密钥和原生测试开关。

首次 npm 因默认 `/home/agent/.npm/_cacache` 不可写而失败；改用 `/tmp/tender-npm-cache` 后安装和构建成功，未提权或修改全局 npm 配置。

第一轮完整默认回归：**3825 passed / 2 failed / 0 errors / 2389 skipped，186.12s**。它收集测试后另新增的三个专项用例不在该轮计数内。失败均在既有 `test_init_volume_with_nonroot_owner_is_rejected_without_repair`：本环境 umask 将 `mkdir(mode=0755)` 生成的测试目录收紧成 0700，测试却断言最终为 0755。生产拒绝逻辑没有改动目录。

修正仅限测试 fixture：将自有临时合成目录初态显式设为 0755，继续验证拒绝后模式和内容完全不变。这比直接改断言为 0700 保留了对非法自动修复为 0700 的检测能力；没有新增运行账号、数据库权限或生产权限。该文件 **9 项通过**，随后重跑最终完整默认回归；另在显式 umask 0022 下复验也是 9 项通过。

## 最终验证

最终完整默认回归：**3830 passed / 0 failed / 0 errors / 2389 skipped，185.95s，退出码 0**，共收集 6219 项。2389 项按 179 种原始原因记录，不计为通过。全量 JUnit 与 summary 位于 `workbench/.local/ci/image-order-unit-final/`；交付副本位于 `/workspace/scratch/tender-render-validation/`，包含首次失败和最终结果，均为本地证据。复现命令如下：

```bash
cd workbench
.venv/bin/python -m pip check
.venv/bin/ruff check apps/api apps/worker packages deploy tests
.venv/bin/ruff format --check apps/api apps/worker packages deploy tests
.venv/bin/mypy apps/api apps/worker packages deploy
.venv/bin/bandit -q -ll -r apps/api,apps/worker,packages,deploy -x packages/parsing/qa
.venv/bin/python deploy/ci_checks.py --suite unit --report-dir .local/ci/image-order-unit-final
```

专项命令在首轮七个测试文件之外增加 `tests/test_authoring_rich_image_sections.py`，最终 **160 passed / 0 failed / 0 skipped，3.26s**。它与全量默认回归重叠，不相加。完整后端 ruff/format（1073 文件）、mypy（671 源文件）、bandit 与 pip check 通过。前端 `npm run format:check`、`lint`、`typecheck`、`build` 全部通过（构建 4.95s）；仅产生常规大 chunk 提示，生成的 tsbuildinfo 不纳入改动。未运行前端单测/浏览器回归，未改变前端源码。

## 原生阻塞与图注下一步

2389 项默认跳过按 runner 的精确原因保留；主要为未显式配置的隔离 PG17 非 owner、Kafka/S3/OSS、固定转换器、真实本地模型与历史验收档案。默认组不能替代原生验收，原生套件也未单独运行。本轮没有建立数据库、账号、权限或生产连接，未调用付费模型。历史档案缺失的 6 项单独维持未验收；原生恢复、评分或提交资格没有改变。

**章节定位可以在当前冻结协议中补齐，上述小闭环已经实现。图注定位不能据现有证据完整放行。** `rich_docx.assemble` 将图注生成为普通段落；`rich_verification.verify_container` 仅接受 `sec_[0-9a-f]{32}` 章节书签及最多 500 个配对 ID。冻结图注文字可能重复、跨行或换页，全文出现同样字符串不证明它属于哪张图片。可靠补齐需要独立的图注/图片锚点或等价严格测量方案、同步生成器与验证器协议及 profile，并在实际受控 DOCX→PDF 转换中验收锚点保留、换页和重复图注；不应静默复用章节身份或放宽书签准入。

当前仍缺既定 Word03 镜像可复现来源及新的受审 RICH profile，故没有完整转换成功结论。复杂跨页表格、混合表图相对位置、图注位置与 M1 全稿验收继续未完成。无需为本次已完成的小闭环新增产品授权；真实转换环境及图注协议增量是下一工程边界。文档仓库引用的协作文件 404 状态未改变。

全程仅本地开发与验证，不推送、不发布、不合并、不部署。
