# 独立解析：已配置本机 HTTP 服务与 PG 发布验收

日期：2026-10-21。范围是新 `document-parse/1` 的 `configured_local` 分支，核对真实解析响应能否经过既有普通 Worker 和不可变发布协议保存；不把本次合成样本外推为完整标书、真实业务精度或生产部署验收。

## 实际执行链

新增显式门控测试 [`tests/test_document_parses_local_http_pg.py`](../../tests/test_document_parses_local_http_pg.py) 使用以下真实链路：

1. 独立子进程执行现有 `python -m packages.parsing.server`，仅监听随机回环端口。`LocalParser` 启动时校验本地中英文 OCR 资产、实际 Tesseract、解析源码和依赖身份；不存在请求时下载资产的步骤。
2. API 服务函数以独立非 owner API LOGIN 读取原件条件，执行 `service.start`，固定方法与精确文件身份并写入 operation/outbox。
3. 从真实 outbox 读取任务，通过普通 `engine.acquire`、`run_compute`、`finish`，以独立非 owner Worker LOGIN 发布。`ParsingHttp` 使用真实 TCP、Bearer 身份、原始 PDF 字节和 SHA-256 调用解析服务；观察器只记录真实返回值，不替换响应。身份探测和解析 HTTP 均检查数据库连接已退出。
4. 读取实际 `parse_runs`、`pages`、`evidence_blocks` 和结果记录，逐项比较服务原响应的物理页、尺寸、旋转、质量、缺口、文字、摘要、bbox、方法、章节路径、置信度及完整表格结构。发布完成后再次追加页，真实 SQL 必须拒绝。

基础库为隔离 PostgreSQL 17.11，沿用已有一次性 `fusion_package_requirements_api` fixture；owner 只装配 schema 与合成原件前置数据。对象存储明确使用内存字节端口；普通 Worker 函数在测试进程内执行，解析服务为独立进程。**本项没有重跑 Kafka 或真实 S3**，其独立实测见 [真实运输验收](real-transport-acceptance.md)。

## 发现并修复的真实问题

修复前同一真实集成测试得到 **4 通过、2 失败，3.48 秒**：普通文字、规则表、工程图和扫描页已通过；编号标题与首格带编号的表格失败。

真实 HTTP 响应均为 `coverage=usable`，但启发式章节识别把原证据 `kind` 改为 `heading`。编号标题得到 `heading/text/...`；首格带编号的规则表得到 `heading/text/heading`，表格块也被改型。独立解析规范化随后以 `DOCUMENT_PARSE_RESULT_INVALID` 拒绝。数据库和既有普通解析发布同样只接受 `text/table/visual_observation`，问题位于上游解析器。

最小修复仅移除 [`LocalParser.parse`](../../packages/parsing/core.py) 对证据类型的改写：启发式章节仍输出 `chapters`、`inferred=true` 与 `chapter_path`，文字仍为文字，表格仍为表格。不新增数据库枚举，不放宽 `normalize`，不修改 coverage／gaps 守卫。解析源码摘要属于方法身份，源码变化后方法摘要相应改变，旧任务不会自动换用新方法。

[`tests/test_parsing_local.py`](../../tests/test_parsing_local.py) 同时补充生产者回归，验证编号标题保留文字类型、首格编号表保留表格类型及网格，章节只作为启发式元数据。

## 修复后的真实结果

同一集成文件 **6 项全部通过，3.41 秒**：

| 明确合成的输入           | 真实解析返回                  | 独立解析保存与核对                                                               |
| ------------------------ | ----------------------------- | -------------------------------------------------------------------------------- |
| 普通可见文字及旋转物理页 | `usable`                      | `complete`；页序、尺寸、旋转和 bbox 保持                                         |
| 2×2 有边框规则表         | `usable`                      | `complete`；四个单元格、行列、文本、bbox 完整保存                                |
| 文字旁的工程示意图       | `partial`                     | `partial`；保留 `VECTOR_GRAPHICS_NOT_UNDERSTOOD`                                 |
| 英文文字图像构成的扫描页 | 实际 Tesseract OCR，`partial` | 读出 `120`，保留 `SCAN_LAYOUT_TABLES_AND_VISUALS_UNVERIFIED`；不是文字层模拟 OCR |
| 带编号的普通标题         | `usable`                      | `complete`；证据类型为 `text`，章节路径保留                                      |
| 首格带编号的规则表       | `usable`                      | `complete`；证据类型为 `table`，单元格结构完整保存                               |

六项均核对：结果不声称 Word 覆盖；原件摘要和配置摘要一致；原始响应到数据库的 bbox 和结构没有取整或降级；发布后不能追加页；当前正文、资料和评审 head 未改变；对应 operation 的 `model_calls` 为 **0**。解析服务的无令牌请求返回 401，子进程在 fixture 结束时终止，临时日志权限为 600。

实际解析运行依赖包括 Tesseract 5.3.4、PDFium Python 绑定 4.30.1、pdfplumber 0.11.9、Pillow 12.3.0；中英文词典以仓库 [`assets.json`](../../packages/parsing/assets.json) 的固定摘要校验。测试 PDF 使用 reportlab 5.0.1。此结果记录实际环境，不表示全部目标锁文件或生产镜像已经复现。

### 定向回归与静态检查

- `test_parsing_local.py`、`test_parsing_http.py`、`test_document_parses.py` 及新集成文件在未启用 PG 门的同批回归中得到 **35 通过、6 跳过，3.62 秒**。六个跳过属于新显式集成门，已在上文独立真实运行，不计为本批通过；既有中文扫描 OCR 回归使用明确指定的 Noto Sans CJK SC 字体。
- 改动的解析器和两个测试文件 Ruff、格式检查通过；解析器 mypy、Bandit 通过；新测试 Bandit 检查排除测试断言规则 B101 后通过，固定解析子进程入口有明确的本地 argv 说明。
- 首次在受限执行环境跑到 FastAPI TestClient 时挂起，未计为失败或通过；停止该指定测试进程后，在允许本地运行的最小环境重新执行，得到上述完整回执。该重跑没有数据库 DSN、模型凭据或业务配置。

## 复现与配置

前提：已安装 API／测试与解析运行依赖、系统 Tesseract、校验通过的本地 OCR 资产，以及专用本机 PostgreSQL 管理 DSN。示例从 `workbench/` 运行；DSN 必须指向明确可创建一次性测试库的隔离实例：

```sh
WORKBENCH_ENV_FILE=explicit-local-parser-no-business-profile \
PYTHONDONTWRITEBYTECODE=1 \
FUSION_REAL_LOCAL_PARSER=1 \
FUSION_REQUIREMENTS_ADMIN_DSN='postgresql://nobody@127.0.0.1:55441/postgres' \
PARSING_ASSET_DIRECTORY="$PWD/.local/parsing-models" \
.venv/bin/python -m pytest tests/test_document_parses_local_http_pg.py -q
```

测试自动生成仅存在于私有进程环境中的随机令牌，启动回环解析服务并清理进程；不读取业务 `.env`，不打印令牌，不发送模型请求。固定 fixture 库要求串行运行，发现同名库或角色已存在会拒绝。未同时给出显式开关和隔离 DSN 时跳过，不把 skip 计为通过。

真实使用时的独立解析环境、私有配置和启动命令见 [解析端口说明](../../packages/parsing/README.md)；API 与 document Worker 必须配置同一可达回环服务的 URL 和令牌，具体步骤见 [启动导航](START-HERE.md#可选接入已有的本机解析服务)。Fusion v10 API 预览没有该完整配置，不能据此宣称预览已能运行 OCR。

## 解释边界

`usable → complete` 是现有独立解析协议在无缺口且页级校验通过时的覆盖映射，不是对任意文件完整理解的承诺。扫描、工程图、复杂视觉和未验证布局仍保留实际缺口。所有样本均为合成技术输入；`quality_benchmark=not_business_validated` 保留，未证明中文标书 OCR 准确率、复杂合并表、跨页拼接、Word 保真或恶意 PDF 隔离能力。
