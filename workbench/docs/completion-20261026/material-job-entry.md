# 完整材料任务登记与恢复入口

## 本阶段实际交付

增加 `deploy/material_job_command.py` 单次隔离 CLI，调用既有 `material_judgment_jobs.start/read/refresh`。并未新建任务表、队列、预算账本或资格框架，也没有更改已有 native 方法摘要/权限。`start` 在原有事务内保存任务、全部条款三槽及 outbox；`read` 返回原任务及当前证据状态；`refresh` 必须使用新续期证据和确切旧 evidence revision，不能替换原始任务、范围或模型。登记不调用 reader、Kafka、供应商或扣费入口。

没有新增 Web 公共接口：现有专用原生服务只允许独立用途 LOGIN；把它的 DSN 放进公共 API 或借 API 身份调用会违反既有权限边界。当前可用入口为受控操作者 CLI，公开 execution-context 的拒绝和既有 UI 不变。不得据此声称上传到正式评分完整功能已交付。

## 操作协议

- 无凭据查询方法：`.venv/bin/python deploy/material_job_command.py --action method`。
- 操作：`.venv/bin/python deploy/material_job_command.py --action submit --profile /absolute/private-profile.json --request /absolute/private-command.json --expected-request-digest <原始请求文件SHA256>`。
- 两文件均须操作者所有、普通文件、0600、非符号链接、至多16KiB；严格 JSON 拒绝重复键。profile 只有 `MATERIAL_JOB_DSN`，必须引用已经配置的独立用途连接；本轮不创建或配置凭据。
- 子进程使用固定解释器 `-I` 和白名单环境，不继承 provider/API/存储凭据。命令文件只传引用和摘要，不能输入材料正文、资格布尔值或账户信息。
- 命令 envelope 为 `{version: "material-job-command/1", operation, arguments}`。所有 arguments 都必须包括当前 `expected_method_digest`。
- `start` 参数：renewal_id、expected_renewal_digest、profile_id、expected_profile_digest、command_id。
- `read` 参数：job_id、expected_job_digest。
- `refresh` 参数：job_id、expected_job_digest、renewal_id、expected_renewal_digest、expected_revision、command_id。
- 方法、引用、原生权限、当前来源/策略/续期和软件预算继续由现有适配器与 SQL 核验；CLI 不放宽原 native audit。

成功回执仅含任务/证据身份、摘要、代次/当前状态和不可执行标记，原生提交后才输出。登记与 read 分开：后续 read 失败不能掩盖已提交 start。丢 ACK 时命令结果不确定，重复**完全相同**的原命令或读取原身份；不自动换 command_id、不自动重试、不宣称回滚。原生同命令冲突继续拒绝。新错误输出经过限缩，不回显 DSN、私有路径、原件或数据库错误正文。

## 已有链路核对与真正阻塞

| 已有模块 | 实际能力 | 不授予的资格 |
| --- | --- | --- |
| material_input_authority / material_input_seals | 原生来源/范围政策核验与固定输入封印 | 正式发送、真实视觉可读性、原子快照或预测资格 |
| material_cost_quotes / material_input_renewals | 完整材料估价与现行证据/预算政策复验 | 真实账户价格确认、费用预留 |
| material_judgment_jobs | 固定原始意图、三槽任务、outbox、证据续期 | 模型执行、正式分数 |
| material_request_preflight | 完整 /3 原件与图像恢复、逐条序列化 | 模型实际 token 适配、真实视觉可读性、账户费用资格 |
| material_execution_dispatch / runtime | 原生租约、Kafka 投递、持久终态、明确机制分支 | production_admission 分支继续在读取/预留/发送前拒绝 |
| material_execution_attempts | 机制专用预算预留、一次发送、结算、未知费用保留 | execute_attempt 仍明确 LIVE_QUALIFICATION_UNAVAILABLE；只接受 MockTransport 的机制入口不变 |
| package_scoring_readiness / profile | 旧文本方法的公开固定拒绝 | 不可将旧文本 /1 自动当完整图文 /3 正式方法 |

因此不能简单把“有封印/有估价”接到真实发送。当前确定缺口是：真实账户价格、模型完整输入上下文适配、视觉可读性以及正式发送端口的**权威证据记录/撤销规则**尚无对应已批准 native 协议。需要明确证据来源与发行主体、精确绑定的账户/模型/方法/输入范围、有效期和撤销语义，再版本化连接既有预留及发送链；不自行设定合格阈值，不用调用者 verified=true、模型别名或机制结果冒充。

正式数值预测另受 DEC-010 的真实官方配对数据及冻结评价/发布要求约束；本轮既没有真实数据也未获得该资格。合成正例只能证明原生边界调用和代码机制。当前仍存在必需正式装配代码，不能把它们全部改名成环境问题。

## 验证

- focused：117 passed、22 skipped，23.06秒。包括固定请求、重复字段/方法/引用拒绝、符号链接/权限/大小边界、原命令重复及丢ACK恢复、原生拒绝不重试、读取陈旧状态、续期版本/跨任务身份拒绝、环境隔离与错误脱敏；关联费用未知/调度反例复用已有测试。
- 新增1项 opt-in 原生测试串联 operator start/read/refresh、重复登记和唯一outbox；未运行，缺隔离PG17环境。模拟原生通道不证明权限/事务/并发。
- 初始静态检查发现新命令分派映射的类型推断及测试导入/异常断言问题，已修正；完整静态检查通过。最终默认完整后端 4218 passed、0 failures/errors、2411 skipped，539.37 秒；5 个既有依赖警告。跳过不计通过。前端完整 187 文件、1895 passed，123.66 秒；format/lint/typecheck 通过。后端 ruff check、format（1113 文件）、mypy（690 文件）、bandit 与 git diff --check 通过。
- 没有启动真实长期调度、连接生产、运行付费模型、部署、创建PR/合并或新增安全权限。

本阶段起点 `5e4d8c0a8c19f8ebd4c829c065a2b27c57ea4f85`；提交前独立远端仍为该 SHA，fusion 仍为 `462ec226013b011a40c204fe1c65541c4dbfbc25`。Compose 默认 `.env` 缺失沿用已知未验收，不创建凭据；真实PG/转换/质量未验收与正式资格协议待定分别记录。

前端最终 build 通过，保留既有大 chunk 警告；本轮没有前端源码改动。
