# F11 精确整包事件与定时触发：前端独立验收

日期：2026-10-21。范围：明确选定的整包否决核对输入，保存模板／私有草案、显式选择触发方式、读取持久触发目录、取消未决意图、恢复原请求、核对原生任务与站内通知。本文件承接 [后端独立验收](exact-package-trigger-acceptance.md)，不将前端回放计为新的数据库或模型效果证据。

## 结果

实际服务器生成的 OpenAPI、TypeScript 类型和接口目录下，相关 **7 个测试文件、188 项通过**。包含原有手动任务的 169 项回归，以及新增的 7 项触发协议、12 项界面交互检查。没有覆盖或放宽 `supportsApi`；`taskTriggerContracts.ts` 仅重新导出实际生成的类型。

实际 Chromium 执行 **18 组**组件交互：事件模板、定时模板、取消回执丢失后的恢复、触发目录与站内通知、跳过漏时后的重新核对、私有草案创建，每组分别在 **1280、768、390 px** 宽度运行。前两档使用浅色，390 px 使用深色。所有场景无页面脚本异常、无未配置 HTTP 请求、无横向溢出、无越出视口的表单控件，也没有提交运行接口。手机展开完整来源身份、取消回执、漏时记录、私有草案，以及桌面目录／通知和平板定时表单均已目检。

机器回执为 [exact-package-trigger-frontend-checks.json](exact-package-trigger-frontend-checks.json)，记录源码、生成契约、原始测试报告、18 组浏览器结果和截图摘要。任务相关 ESLint **0 警告／错误**，Prettier 与 `git diff --check` 通过。全应用 TypeScript、构建和完整前后端集成回归由集成负责人统一执行，不把本组件验收当成其替代。

## 使用路径与输入边界

### 从已核对的整包保存

在整包工作面明确选择原包修订、需求清单、冻结输入、执行准备和依赖计划后，可以进入“保存为任务模板”。进入时核验服务器能力、方法摘要和所选记录身份。十个 ID／摘要只读保留；上方工作面后来选择不同计划，不会替换正在编辑或等待回执的输入。

默认触发为手动。只有读取到服务器明确的 `exact_package_triggers` 能力，用户才能选“资料入库后核对这份输入”或“按计划核对这份输入”。选择自动方式才将来源模式改为 `exact_package_trigger`；手动仍为原 `exact_package_review`，二者都保留原十字段。表单显示 cron、时区、独立调度服务要求、执行可能产生费用，以及错过时段不自动补跑。

保存只提交模板，不调用 `/runs`，不读取资料列表或选择 `latest`。自动模板卡片不显示新的手动运行按钮。若旧手动请求尚未取得可信回执，随后模板改成自动模式，也仍保留恢复该旧请求的入口，不用自动模板另发一次手动请求。

### 先生成私有草案

同一份已核对输入还可选择“先用文字拟定私有草案”。创建请求固定传 `exact_package_review` 与原十字段，默认手动，不借助自然语言推断新来源。解释结果保持私有草案；用户随后在草案表单明确选择任务类型与触发方式，更新草案后再保存模板。

草案创建、更新和保存分别保留原 CAS 基准和幂等请求。创建回执核对成员、项目、初始修订、ETag、原请求、确切来源和完整解释摘要；草案更新核对原修订加一、完整配置和摘要；模板保存核对已确认草案配置与初始模板版本。回执缺失或来源不一致时保留原请求。变更服务器读取基准是明确操作，不能顺便换成新的整包来源。

草案创建与编辑的前端 HTTP 反例为根据实际契约构造的合成响应；这部分不声称新增了原生数据库草案用例。原有后端草案机制和本轮自动解释约束的证据仍以相应后端报告为准。

## 持久触发目录、取消和状态

任务页新增“整包事件与定时触发记录”。目录只在展开或由原触发深链进入时读取；使用服务器的 `next_after`，不把 UUID 大小当作创建顺序。每页先核对项目身份、精确输入、触发身份、终态及原任务引用；刷新第一页后旧分页链失效，重复项或游标不前进时保留原目录并停止追加。详情支持原触发 ID 深链。

详情区分别显示 pending、accepted、blocked、cancelled，以及原事件或计划时刻、原模板版本、精确来源和摘要。后续读取若变更同一意图的不可变来源或倒退终态，保留上次可信快照供阅读，暂停新写入。服务未返回完整原始 manifest，因此客户端不伪称能重算其不透明总摘要；客户端核对已暴露身份和关联，原子完整性仍由后端与 SQL 守卫保证。

pending 意图可以填写原因并取消。取消记录使用已有 `task-package-run` 存储命名空间并加 `trigger-cancel:{intent_id}` 范围；成员切换与退出清理无需另造未注册存储类型。原 body、ETag、幂等键与预期意图一并保存，页面刷新或 GET 已显示 cancelled 都不会清除尚未收到的原取消回执。只有可信终态 ACK 才完成该请求；已关联原生运行时转到原运行与 operation 的取消入口。

原触发 ACK、当前意图和当前任务结果分开显示。accepted 不等于核查完成，复用同输入原运行不等于新增一轮模型调用。站内通知显示实际持久状态，并明确不代表邮件或外部消息送达。

## 漏时与重新确认

`skipped_reconfirm_exact_input` 与 `run_current_once_ref=null` 只显示跳过的有界时段、下一计划时刻，以及原模板的确切输入核对链接。不提供“运行最新包”或自动补历史的操作。链接能够读取第一页之外的指定模板；用户必须明确保存为手动模式，再沿原手动流程运行。

精确自动模式的漏时条目不再重复挂载同一模板的可写卡片，避免同时从目录和恢复条目编辑同一模板。旧手动模板的恢复显示保持原行为。

## 检查证据与真实边界

| 检查 | 结果／边界 |
| --- | --- |
| 实际生成契约 | 3 条意图读取／取消路由与 4 个新命名类型已在共享生成输出；前端无临时接口覆盖。 |
| 协议与界面测试 | 188 项；默认手动、自动选项显式启用、输入不替换、自动模板不调旧 `/runs`、错误来源／终态／回执拒绝、取消原请求恢复、UUID 更小的后续分页、漏时核对、两步草案保存。 |
| 浏览器 | 6 场景 × 3 视口，共 18 组；实际 React、实际接口目录、实际表单和存储恢复机制。 |
| 静态检查 | 任务范围 ESLint、Prettier、diff 检查通过；全应用检查由本批集成回执记录。 |
| 后端证据隔离 | 已冻结的 37 项 PG／ASGI／原生 Worker 收据所列源码和 SQL 字节未变化；16 份 HTTP 响应内容与原导出逐项相同。新增复盘 schema 后，根另以完整共享 BASE 重跑 37 项全部通过，见检查点 11 集成收据。 |
| 外部调用 | 浏览器和前端测试均为合成 HTTP，真实模型调用与付费调用为 0；没有启用部署 runner、外部通知或对话自动化。 |

除私有草案构造响应外，浏览器 HTTP 回放来自 `apps/web/src/test-fixtures/task-package-triggers-http.json` 的实际本地 PG／ASGI 验收数据。材料与模型 HTTP 为明确合成数据。本轮浏览器没有连接数据库、Kafka、真实对象存储或模型供应商；证明的是前端契约和交互，而非真实标书业务质量或长期调度效果。

当前整包自动输入生产者仍仅为否决核对。评分、补遗语义影响、章节建议不能因出现触发界面而被当作已有完整整包生产者；各自真实范围沿用后端能力声明。

## 重现

在 `apps/web` 下执行相关测试：

```sh
./node_modules/.bin/vitest run \
  src/taskPackageProtocol.test.ts src/useTaskPackageCommand.test.tsx \
  src/ExactPackageTaskUI.test.tsx src/PackageTaskTemplate.test.tsx \
  src/TaskPanel.test.tsx src/taskTriggerProtocol.test.ts \
  src/TaskPackageTriggers.test.tsx --maxWorkers=1 --fileParallelism=false
```

浏览器脚本使用明确安装的 Playwright 和 Chromium，只启动随机回环端口，并在结束后关闭自身页面与 HTTP 服务：

```sh
PLAYWRIGHT_MODULE=/absolute/path/to/playwright \
CHROMIUM_PATH=/absolute/path/to/chrome-headless-shell \
node scripts/check-task-triggers-browser.mjs /tmp/new-task-trigger-browser-output
```

仓库保留 [手机事件表单](screenshots/task-trigger-event-390.png)、[平板定时表单](screenshots/task-trigger-schedule-768.png)、[手机取消回执](screenshots/task-trigger-cancel-390.png)、[桌面目录与通知](screenshots/task-trigger-history-1280.png) 与 [手机漏时核对](screenshots/task-trigger-missed-390.png)。完整 18 张截图由可重现脚本生成，机器回执记录其摘要。
