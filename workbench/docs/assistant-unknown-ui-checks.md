# F08-02 unknown 显式恢复 UI 切片

2026-10-18，本切片接入已由 25 项非 owner PG/ASGI/Worker/CLI 测试验证的服务端判定。修改 `AssistantWorkspace.tsx`，新增 `AssistantIntentRecovery.tsx` 及独立组件测试；没有修改预算 SQL、业务 Python、管理 CLI、生成契约、全局 CSS、包或导出组件。

## 实际交互与契约

`AssistantTurnRequest` 已由实际 `fusion-implemented.openapi.json` 生成，项目与 global turns 使用同一请求契约；无需手写平行类型或扩后端。

| 用户明确操作 | 请求 / 行为 |
| --- | --- |
| 普通发送 | 原会话存在待核清费用时继续禁用，不自动换 nonce、profile、目标或用途 |
| 关联原任务查看状态 | 用户必须选择原 job。提交 `request_mode=continue`、`related_job_id`、固定“查看原任务状态”、空来源及空章节；不发送未另存草稿，不附新 target/purpose。服务端按原 job 回读，不新建任务/模型调用 |
| 明确新的业务对象与用途 | 用户逐项选择实际项目、对象类型及具体对象，再点击“提交明确的新问题”；提交 `request_mode=new_question`、真实 target 和该类型唯一允许的用途，服务端继续判 canonical 身份、五事实、来源和三 scope 预算 |
| 服务端复用当前原 job | 明确显示未创建新任务/模型调用；保留草稿，不把原费用当已核清 |
| 服务端拒绝独立性 / 身份依据 / 预算 | 显示真实错误，保留草稿、来源和所选对象，不自动改目标或重试 |
| 受理回执丢失 | 沿用 useRecordedCommand 保存的原请求体、If-Match、幂等键恢复受理结果；锁住目标和来源编辑，不将恢复 ACK 当新模型尝试 |

关联查看的回包必须仍属于当前会话/项目且 job ID 正是用户所选原 job；不匹配时保留草稿并拒绝“已读回”提示。服务器将新项目壳关联到另一会话的原 job 时，现有会话身份守卫仍拒绝把它写作当前会话结果；不会借此启动另一次调用。

新问题支持以下实际对象，不允许用户自由填写 UUID 或任意用途：

- project：项目会话只能明确选择当前项目；global 从用户已经选择的项目结构化来源中选择，并读取真实 `/bids/{id}`。发送继续保留该项目来源的精确版本。登记工程/标段/轮次/投标人用于核对名称，不在客户端授予 canonical 独立性。
- rule：读取当前项目 `/bids/{id}/rules`，校验返回 bid 及每条 scope.bid_id；用途固定 rule_explanation。
- finding：读取真实当前评审 `/reviews/{current_review_id}/findings?limit=50`，过滤不属于该评审的问题；用途固定 finding_explanation。若有后页，明示当前范围，不伪装完整问题清单。
- section：仅列本次已选且属于该项目的可信保存章节；用途固定 section_reference。本切片没有接入 section_draft 或正式生成动作。

global 的任何业务目标还必须有对应 project 结构化来源；只选择原件/章节不能替代所属项目。移除对应来源或读取失败时使目标失效，不切换成其他对象。项目会话给出明确的全局助手链接，不自动跨项目导航/发送。显式对象入口在没有当前会话 unknown 时也可打开，以便另一个会话仍有 unknown 时明确提出新的实际对象问题；默认请求保持原行为。

## 硬门与权限边界

区分 unknown 费用门与真正的硬门：任务列表加载中、失败、不可用、混入其他会话/项目记录，或真实 queued/running/cancel_requested，均禁止发送和恢复选择。选好新对象后收到这些状态也立即恢复禁用。关闭/归档会话、受理结果未取得、412 尚未核对等原门继续生效。

界面没有“我确认独立”勾选、预算管理员入口、假核清、费用归零或普通模型重试。可信账单核清仍仅走独立管理 CLI。客户端对象选择和本地来源缓存只是待提交输入；是否有当前依据、是否同一 canonical 业务对象、是否仍占预算全部由原服务端判定。

## 验证

- 新增 **17 项**：默认无选择、原 job 引用、真实 rule/finding/section/project及允许用途、global 所属项目来源、移除来源、读取失败、继续查看保草稿/不另发草稿、错误 job 回包、服务端复用/拒绝、丢 ACK 精确恢复、加载/错误/外来/在途及动态硬门。
- 最终完整前端 **178 / 178 通过**（39 个测试文件；JSON reporter 计 41 suites），约 **48.67 秒**。收据 `.local/assistant-unknown-ui-vitest.json`。
- `tsc -b`、全应用 ESLint、三个变更 TSX 的 Prettier、Vite build、git diff --check 通过。构建仍保留原 AssistantWorkspace 静态/动态同时导入的分包提示。
- 全目录 Prettier 检查有 **11 个既有字体资产格式提示**（`public/fonts/fusion/{inter,noto-sans-sc}` 元数据/CSS及 manifest/sources）；这些是另一切片的固定输入，不在本范围修改，不将全目录格式检查记为通过。
- 首次完整回归中两个新增夹具在数据加载/选择方式之前查找 option，报 176 通过 / 2 失败；只修测试等待与用户操作顺序后，新 17 项及最终完整 178 项通过，没有为测试放松生产门。

源实际字节 SHA256：

| 文件 | SHA256 |
| --- | --- |
| AssistantWorkspace.tsx | `343e89f2e5a8cfa273b7e982c1599bcb6a7b49c0100cbf973d5e8acb568585fb` |
| AssistantIntentRecovery.tsx | `2673cfbf9a4ecea93dba09c2b378f5b3ff2f0f5cce19aed281e1732c780e6b3e` |
| AssistantIntentRecovery.test.tsx | `d840270f7ad1a5b8ddc4d9b2a3be8452bab55dcb33d3b408d0953ccf09ee0fff` |

本次为实际组件代码与请求契约测试，fetch 使用显式合成适配器，没有真实供应商/费用。此前 25 项完整角色链见 [非 owner 检查](assistant-budget-nonowner-checks.md)；本次尚未部署融合应用、未完成真实 API 浏览器交互/截图与视觉验收，也不代表 Kafka 或生产收费放行。
