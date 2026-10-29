# M2：有界分章建议、完整对照与原子应用

本页记录当前分支的多章节 AI 编写实现及实际验证。它复用已有助手任务、模型调用账本和 Worker；生成成功先产生候选，正文只在成员明确选择并确认后追加一次草稿修订。模型质量、真实收费与业务标书效果各有独立验收条件。

## 实现范围

一次批次明确选择 1—20 个章节，冻结草稿修订／快照、各章修订、编写指令、来源、可编辑节点、模型价格版本和预算。单章最多 5 次显式尝试；没有自动新建收费尝试。每次排队前，完整模型消息包含系统约束、Rich 原文、来源与结构记忆，总长度不得超过 200,000 个字符；批次全部尝试的实际冻结输入累计不得超过 16 MiB。超限整件拒绝，事务回滚，不截断正文或来源。

受控模式为 `section_patch_set/1`。模型只能替换已冻结的段落／标题行内文字，或在获准的顶层锚点插入段落。模型不能指定新节点身份、图片、表格、来源对象或任意业务参数；新增节点身份由服务端确定性产生。表格（含单元格文字）、图片和未选择节点保留原字节，现有节点身份及属性不变。每项替换／插入均核对原文摘要，重复、越界、未知引用、空变更及超量响应拒绝。

确认前展示完整章节的前后 Rich 内容、实际改动和来源。图片读取指定历史资产版本并核对实际字节、摘要和尺寸；不能只凭缩略文字或模型自报摘要认定候选正确。既有 Word 导入章节、复制章节和图片保留原件来源约束；排队、候选发布和最终应用分别核验当前来源与编写依据。

## 预算与状态

- 成员明确填写批次总额与各章额度，沿用当前已核验的价格版本。金额按 `amount_scale=1000000000` 的整数计算，HTTP 整数限制在 JavaScript 可精确表达范围内；前端十进制输入不经浮点乘法换算。
- 预留是按冻结价格与输入／输出上界计算的预算估计，不是供应商侧消费硬上限。异常账单仍按真实费用保留；发现超额后阻止后续尝试，不舍弃已发生费用来维持绿色状态。
- 单章与总批次累计所有尝试的已结算费用及尚未结清的完整预留。重试不重置额度；价格或冻结上下文改变后须重新建立批次。
- `reserved`／`unknown` 调用、待人工核清或尚未释放的费用不被当作零。未知费用先走既有可信核清流程，不因刷新、换请求键或取消而重新发送。
- 任务 `succeeded` 与候选 `published` 分开。已生成但尚未发布候选时显示候选整理中并继续读取状态；服务端也阻止此时应用批次。
- 所有任务终结且费用核清后，可以明确选择部分成功章节，一次事务保存所有所选变更。任一候选过期、上下文变化、来源失效或草稿 CAS 冲突，整次应用不写入。
- 部分应用即结束当前批次；未选章节保持原修订，其候选记为已拒绝。要继续这些章节，应基于新的草稿状态建立新批次。批次拒绝不修改正文，取消仍在执行的任务并保留真实费用状态。

## API、历史与恢复

实际路由位于 [`authoring_generation_batches.py`](../../apps/api/authoring_generation_batches.py)，闭合请求与响应见 [`generation_batch_contracts.py`](../../packages/assistant/generation_batch_contracts.py)。

| 操作 | 实际路径（均以 `/api/v1` 开头） |
| --- | --- |
| 能力、上限、价格与预留估计 | `GET /authoring/generation-batch-capabilities` |
| 新建批次 | `POST /bids/{bid}/drafts/{draft}/generation-batches` |
| 分页历史摘要 | `GET /bids/{bid}/drafts/{draft}/generation-batches` |
| 完整批次与每次尝试 | `GET /bids/{bid}/drafts/{draft}/generation-batches/{batch}` |
| 精确完整候选 | `GET /bids/{bid}/drafts/{draft}/generation-batches/{batch}/candidates/{action}` |
| 明确重试失败章节 | `POST /bids/{bid}/drafts/{draft}/generation-batches/{batch}/retry` |
| 选择应用或拒绝整批 | `POST /bids/{bid}/drafts/{draft}/generation-batches/{batch}/resolve` |

写入沿用会话、同源 CSRF、幂等键和草稿强条件头。批次详情及候选的读取 ETag 不是写入用的 `base_draft_etag`。恢复使用原键、原请求体与原条件头；先查原命令回执，再判断新的业务资格，已关闭项目仍能读取既有回执与历史。历史列表只加载摘要，完整指令、节点与候选按明确选择读取。

批次候选不能从旧单章 `apply_patch` 或助手通用确认接口旁路应用。所选与未选候选的消费、最后结果、草稿快照、命令回执及审计在同一事务内提交；重复请求只返回原结果。

## 安装与角色边界

当前基础 schema 已含编写结构、Rich 和 Word 导入。本功能是可选扩展，顺序为：

| 顺序 | 相对 `packages/assistant/sql/` 的文件 | 本轮核对的 SHA-256 |
| --- | --- | --- |
| 1 | `assistant.sql` | `4030b5e6a749aa060956c4039aa0cdd34e057508ea6a4ce9c58100f5a6ca81b0` |
| 2 | `live-facts.sql` | `42fc9646225a67a8d209822ac9d0e3573e6903b3f5681042e9cb49fa6eeb11a2` |
| 3 | `intent-budget.sql` | `173078b95a5cd58db9f8f8aa09ff2728bae2c4a1e1b3817a4b593e719b04a6b0` |
| 4 | `generation-batches.sql` | `1042f97f6fa25411a1eabb28444fa3ca8f4389b7137990ebf67d6f97992a72e0` |

各 SQL 只用于已审字节的全新隔离初始化，通过现有 `deploy.bootstrap_fresh.bootstrap` 的 `extensions` 传入路径及 SHA-256。需要专用预算配置身份时使用其 `assistant_budget_admin=True` 参数；该参数目前没有对应的 `create_check_environment.py` CLI 开关。价格、额度及可信费用核清继续使用 [`packages.assistant.budget_admin`](../../packages/assistant/budget_admin.py) 的独立非 owner 身份，不向业务 API 或普通 Worker 授予预算管理权。

三个新增批次表只授 API `SELECT, INSERT`，内容追加后不可变。普通 Worker 沿用冻结任务和调用账本；候选发布由 API 身份的 coordinator 完成，Worker 不获得批次写权限。未安装助手扩展、缺价格或模型配置时，能力接口明确返回不可用。Fusion v10 默认预览不安装这些助手扩展，也没有模型 Worker。

## 验证记录

本节记录各个实际执行批次，不把重叠用例累加为一次全量结果。

| 层次 | 当前实际证据 |
| --- | --- |
| 纯协议与关联回归 | `test_authoring_section_patch_set.py` 90 项；联合既有单章／Rich／Word 来源／provider 回归单次 210 项通过。包含完整消息长度 200,000 接受、200,001 及 262,145 整件拒绝；未发起模型请求 |
| API 接线 | 新路由与 M1 装配联合 10 项通过；检查七个实际路由、读写认证、CSRF／幂等／条件头、只读事务、项目草稿范围与读取 ETag |
| 静态检查 | 本轮 18 个改动 Python 文件 Ruff 与格式通过；协议／共享生成 8 个、领域 3 个、API 装配 2 个实现文件的 mypy 与 Bandit 分批通过；16 个前端文件 Prettier 及改动文件 ESLint 通过 |
| 真实 PostgreSQL | 最终源码独立复跑 13 项同批通过，24.67 秒；非 owner API／Worker、MockTransport 模型、原生调用与预算账本、完整表图候选、一次保存，以及并发幂等、费用未知、来源撤回、容量、CAS 和数据库旁路反例 |
| 最终完整后端 | 1,945 项通过、1,208 项环境门跳过、0 失败、0 error，56.83 秒。3,901 个选定源码／契约文件运行前后摘要相同：`931a7d56a5aae8b17f5f70474a59936bd69e0bd04d091af6456967646d1e98ae` |
| 完整前端 | 99 个文件、838 项通过，29.60 秒。此后仅补可见“原稿／候选稿”标题，最终相关 2 个文件、21 项再次通过；未把两轮结果相加 |
| 最终类型与构建 | 最后显示修正后的 TypeScript 与 Vite 生产构建通过，3.79 秒；入口 chunk 520.06 kB、gzip 160.47 kB 的既有体积提示仍保留 |
| 实际浏览器 | 1200／768／390 三档宽度，完整候选、未知费用和应用后状态共九张截图；表格合并单元格、四张实际解码图片及可见前后稿标题均核对，零横向溢出、页面异常与错误提示；未知费用阻止应用和重试 |

所有模型返回均为明确合成端口；本轮真实收费调用为 0。合成通过证明限定机制，不证明生成内容准确、工程适用或正式投递资格。

浏览器候选来自真实非 owner PG、MockTransport Worker 与 coordinator 的服务输出，网络响应、未知费用场景及应用 ACK 使用合成端口。浏览器时间固定为候选建立后一分钟（`2026-10-21T02:12:01.916Z`），以检查未过期候选；未调整生产过期策略。各宽度均只发出一次合成 resolve 请求。[浏览器检查回执](authoring-m2-browser-receipt.json) 保留实际检查结果；该项不能表述为真实业务 HTTP 端到端或真实模型验收。

真实 PG 还覆盖：第二章预算失败时全部任务／outbox／预留／批次回滚；最后章发生真实数据库错误时，先前章修订及所有消费和回执均回滚；部分应用关闭其他候选并保留未选章修订；已付费失败重试继续累计旧费；拒绝未知费用任务保留原 hold；旧单章确认／拒绝入口不能消费批次候选。新增 SQL 延期守卫同时约束 `assistant_action_links` 终态和 `action_consumptions` 的独立插入，防止仅写消费表绕过整批结果。

复验入口如下。`FUSION_REQUIREMENTS_ADMIN_DSN` 只允许指向操作者明确准备的隔离测试实例；这些测试会创建一次性数据库，不连接业务库。

```bash
WORKBENCH_ENV_FILE=review-readonly PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  tests/test_authoring_generation_batches.py \
  tests/test_authoring_generation_batch_api.py \
  tests/test_authoring_section_patch_set.py -q --tb=short

# 已在独立进程注入隔离实例 FUSION_REQUIREMENTS_ADMIN_DSN 时执行：
WORKBENCH_ENV_FILE=review-readonly PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  tests/test_authoring_generation_batches_pg.py -q --tb=short -p no:cacheprovider
```

第一组为 118 项组合回归，与 210 项协议／旧路径回归存在重叠，不能相加。最终 PG 复跑包含静态检查后改成完全参数化 SQL 的历史查询，未把较早源码的通过结果作为最终结果。
