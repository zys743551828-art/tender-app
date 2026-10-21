# F12 助手确认卡差异与来源详情验收

日期：2026-10-21。范围：批准 UI 对照 AI4／AI5／AI7 中的助手来源详情、正文操作提议实际文字差异与完整稿核对。本批不关闭整个 F12，也不替代整应用端到端业务验收。

## 已实现行为

`AssistantActionCard` 的正文修改卡复用既有 `TextChangePreview`。用户按需展开实际文字增删、完整原稿、完整拟稿；初始状态不渲染长篇正文。相邻带格式文字不被错误拆成不同段落，软换行保留。列表、强调等格式仍可通过独立完整稿入口核对。短变化按文字标示，超过既有比较预算的变化明确提示按区块标示，两侧仍保留全部输入文字。

助手卡根据自身宽度切换对照布局：宽卡可并排读两份稿件；卡片宽度不超过 760 px 时，通过“修改前／拟修改后”查看单份。这同时覆盖小屏和桌面的窄助手栏。完整稿与差异区都限制显示高度、保留滚动全文；使用语义主题变量。

所有展开／折叠均为只读展示。确认、拒绝、刷新、原请求恢复的 handlers 与 `useRecordedCommand` 没有修改；历史卡展示的是当时保存的前后稿，不冒充当前正文或尚未执行状态。

来源详情只展示接口实际给出的字段：来源名称、类型、项目、固定版本凭据、原件物理页／知识查证记录、服务器可用性及原因。用途只陈述当前助手协议的“讨论参考，不作为正式评分输入”，不编造资料业务用途、修订号或版本时间顺序。

已选来源保留原引用及版本。只有项目与来源 kind／id／trace／物理页一致时才比较目录记录；同名文件不能代替引用身份。不同版本并列显示，用户明确勾选才换版。目录未列出、查询范围不同、刷新失败等均显示“尚未核对”；没有列出不被解释为撤回。不同版本的不可用原因明确属于目录所列版本，不推断已选历史版本状态。来源详情放在勾选 label 之外，展开不会勾选来源；选择锁定期间仍能阅读详情。

## 文件边界

| 文件                                                   | 改动                                           |
| ------------------------------------------------------ | ---------------------------------------------- |
| `apps/web/src/AssistantActionCard.tsx`                 | 仅正文提议预览接入，只读旧全文提取改为比较组件 |
| `apps/web/src/AssistantSourcePicker.tsx`               | 已选版本详情、目录详情、可用性观察失效处理     |
| `apps/web/src/AssistantPatchComparison.tsx`            | 只读差异与完整格式稿件                         |
| `apps/web/src/AssistantSourceDetails.tsx`              | 实际来源边界与版本详情                         |
| `apps/web/src/AssistantReviewDetails.css`              | 卡片响应、可读详情与语义样式                   |
| `apps/web/src/assistantReviewFixtures.test-support.ts` | 明确合成资料与 HTTP 夹具                       |
| `apps/web/src/AssistantReviewDetails.test.tsx`         | 12 项新增回归                                  |
| `apps/web/scripts/check-assistant-review-browser.mjs`  | 实际组件的隔离 Chromium 验收                   |

不修改 `ProjectWorkspace`、`RetrievalDrawer`、`Evidence`、共享样式／契约、保存或恢复 hook，也不修改既有差异算法。根在并行修改公共反馈组件；浏览器使用一次性 esbuild bundle，打包前后核对实际源码输入摘要，不接 HMR。回执记录本次 48 个源码依赖的实际 SHA-256，故不把其他未冻结文件概括成固定工作树候选。

## 已运行验证

以下命令工作目录为 `workbench/apps/web`。

```sh
./node_modules/.bin/vitest run src/AssistantReviewDetails.test.tsx src/AssistantWorkspace.test.tsx src/TextChangePreview.test.tsx src/AssistantIntentRecovery.test.tsx
```

结果：4 个文件、39 项通过，其中本批新增 12 项。覆盖以下实际风险：

| 风险                       | 已验证结果                                                                                     |
| -------------------------- | ---------------------------------------------------------------------------------------------- |
| 预览错误拼接或截断正文     | 对照前后全文与独立预期字符串相等；相邻强调文字、软换行、列表及末段保留；短变化只标实际改变文字 |
| 查看预览意外执行           | 展开文字／完整格式／来源详情均没有写请求；只有明确采纳发起确认                                 |
| 长卡或历史卡误导           | 超长稿完整保留；stale／expired／rejected 卡可读历史全文，不提供再次采纳                        |
| 来源在查看后撤回           | 明确确认采用服务端 stale 回执，业务效果为未执行                                                |
| 答复丢失导致重复采纳       | 原请求恢复在组件重新挂载后仍存在；相同幂等键、请求体、If-Match 重放；只产生一次合成业务效果    |
| 来源版本被静默替换         | 老版本与目录版本同时可核对，只有明确勾选才更换                                                 |
| 同名、物理页、查证记录串用 | 同名但无引用不能冒认；物理页与 trace 属于精确身份                                              |
| 过期目录冒充当前可用       | 读取失败保留原选择，旧目录不可新选；不同版本的撤回原因不冒充原版本状态                         |

所属 TS／TSX 与浏览器脚本 ESLint 通过；8 个所属源码文件 Prettier 检查通过。整应用 `tsc -b --pretty false` 在本批代码落盘后通过。随后运行 `npm run build` 时，根并行新增的 `SourceSurface.test.tsx` 与 `sourceSurfaceFixtures.test-support.ts` 出现类型错误，构建停在 TypeScript 阶段，未到 Vite；具体错误已回报根，未越界修改这些文件。这个后续构建结果不能登记为通过。最终整应用构建与全量回归由根在合并候选上完成。

### 实际 Chromium

```sh
PLAYWRIGHT_MODULE=/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright \
CHROMIUM_EXECUTABLE=/tmp/tender-completion-runtime/chrome-156/chrome-headless-shell-linux64/chrome-headless-shell \
node scripts/check-assistant-review-browser.mjs /tmp/tender-assistant-review-browser
```

结果：11 组流程通过、17 张截图；没有页面错误、意外 HTTP 路由或外网请求。

| 场景               | 范围                                                                                                                |
| ------------------ | ------------------------------------------------------------------------------------------------------------------- |
| 正常核对与明确采纳 | 1280／768／390 px × 浅色／深色，共 6 组；键盘展开、完整文本、完整格式、来源详情、显式换版、单次明确确认、无横向溢出 |
| 桌面窄卡           | 1280 px 视口、窄卡容器；单份切换、键盘、全文和布局                                                                  |
| 长文               | 390 px 深色，原稿／拟稿各 120,061 个 UTF-16 码元；精确全文、完整格式末段可滚动到达，没有应用                        |
| 来源失效           | 390 px 查看后、确认前来源失效；服务端 stale，无业务效果或第二个确认入口                                             |
| 原请求恢复         | 390 px 答复丢失后重新挂载卡片；查看不重发，明确恢复使用同一个键／体／条件，一次业务效果                             |
| 目录读取失败       | 390 px 已选原版本保留、可用性改为未核对、旧候选禁选，没有写操作                                                     |

已目检 390 px 深色差异、390 px 浅色来源、1280 px 浅色并排及长文末段截图。第一次浏览器运行暴露 768 px 卡片双栏过窄，已通过卡片宽度断点修正并重跑；长文断言曾误取列表内最后段落，已改为完整稿实际最后段落，并检查它落在滚动区域内。最终回执只登记完整通过的运行。

本地证据：`/tmp/tender-assistant-review-browser/receipt.json`，同目录 17 张截图。源码、命令结果及完整浏览器回执已收在 [assistant-review-details-checks.json](assistant-review-details-checks.json)，包括依赖和截图摘要。

## 实际边界与后续项

1. 浏览器使用真实 React 组件、现有 API 封装、命令恢复 hook、差异及格式渲染器；项目资料、HTTP 响应和业务效果为明确合成夹具，不代表真实后端／模型／业务质量验收。
2. 助手 action 的 `authoring_patch` 现协议为 `AuthoringDocument`。本批验证其中标题、段落、列表、强调、软换行；没有扩充为图片／复杂表格 action 协议。完整稿渲染复用既有历史快照组件，并非新增富内容授权。
3. `AssistantSourcePage` 仅为部分目录，详情不会声称全量来源已核对；操作时仍以现有服务端重核为准。来源的 opaque 版本凭据不能解释为人为修订号。
4. 原数据中的组合 emoji 在本机无头字体环境中显示占位字形，文本码元完整；本批不是全平台字体、读屏或真实手机软键盘验收。系统主题动态切换已有独立主题批证据，本批仅测浅色／深色，不重复累加。
5. 长知识候选卡、冲突合并页、四阶段上下文选择、整包项目摘要及完整 F12-14 任务矩阵仍属独立剩余项。此次通过不关闭这些项目。
