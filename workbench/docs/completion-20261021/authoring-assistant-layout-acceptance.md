# 正文优先与项目助手并排验收

## 本批范围与结论

本批实现批准计划 **F12-09**，以及 **F12-11 / F12-12 的章节编制与助手部分**。不是整个 F12、39 点设计、正式业务质量或真实模型效果的完成声明。根代理负责的差异组件、主题、技术评分及已冻结报价/复盘文件未由本批修改。

桌面项目助手在指定工作区有足够空间时成为非模态侧面板：预留至少 620 px 任务容器，助手宽度 340—720 px，实际最大值还受可用空间限制；支持拖动、左右键、Home/End，保存界面宽度偏好。正文可编辑，Tab 可返回正文，body 不锁滚动。空间不足时转为模态任务面板，维持同一会话与同一草稿组件实例。面板收起保留讨论、待发文本与原请求，不取消任务。

已选正文的草稿管理和章节目录默认收起。章节编辑器、目录内的待核操作始终保留挂载；章节切换继续等待原有保存队列确认。失败不会切章，原请求键、请求体和条件令牌保持；用户明确重试成功后才可切换。目录未决状态仍限制正文操作，并在正文工具行给出续接提示。编制页抬头压缩，390 px 的格式工具按需展开，正文节点不卸载。

手机/窄工作区的目录与助手使用单任务弹层。项目级助手、查证资料、目录开关通过按 bid 隔离的展示事件互斥；事件不保存、不授权任何业务操作。助手里的来源选择有独立窄屏面板，Escape 先关闭来源并恢复来源按钮焦点，再关闭助手并恢复原入口。更早讨论默认折叠，保留最近两条消息与续接输入。长讨论滚动后收起按钮持续可见。

## 共享接线

只改 `ProjectWorkspace.tsx` 的下列必要接口，其余布局逻辑在独立文件：

- 给助手传 `dockTargetId="main-content"`，作用域只在助手生命周期内预留空间；收起或窄屏时清理属性和 CSS 变量。
- 助手/查证打开 handler 互斥，并广播当前项目的辅助任务。
- 为编制页添加专用样式类，不改 App 或公共 styles。
- 按根代理要求补可选 `onOpenKnowledge?: (knowledgeId: string) => void` 并传给 `SubmissionPanel`。App 中既有导航保护由根代理接线。

`SourceEditor.tsx` 仅把格式栏放进 `EditorToolsDisclosure`；编辑器节点、选区、内容序列化、保存协议未改变。`AuthoringPatchPreview` 与 `TextChangePreview` 等根代理负责文件未改。

## 已执行证据

### 组件回归：43 项通过

```sh
cd workbench/apps/web
npx vitest run src/AssistantDrawer.test.tsx src/AuthoringLayout.test.tsx src/AssistantWorkspace.test.tsx src/AssistantIntentRecovery.test.tsx src/AuthoringRichEditor.test.tsx src/AuthoringStructure.test.tsx src/NavigationGuard.test.tsx
```

其中新增 8 项覆盖：桌面非模态 Tab/正文访问；键盘宽度边界与清理；桌面→窄屏→桌面保持同一正文/提问节点；内层来源先响应 Escape；每层焦点恢复；不同项目辅助事件隔离；目录默认收起且不卸载；真实 `SectionEditor` 断网保存阻断切章、明确重试同一请求后切章。

另外原有 35 项助手请求恢复、富文本、目录影响预览与导航保护继续通过。新增布局测试没有用新保存实现替换现有队列。

### 实际 Chromium：14 组流程通过，38 张截图

```sh
cd workbench/apps/web
PLAYWRIGHT_MODULE=/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright \
CHROMIUM_EXECUTABLE=/tmp/tender-completion-runtime/chrome-156/chrome-headless-shell-linux64/chrome-headless-shell \
node scripts/check-authoring-layout-browser.mjs /tmp/tender-authoring-layout-browser
```

真实组件为 `ProjectWorkspace`、`AuthoringPanel`、`SectionEditor`、`AssistantDrawer`、`AssistantWorkspace`。HTTP 完全为明确的合成夹具，不连接真实业务服务、模型或转换器。

- 1440、1280、820、390 px × 浅色、深色、跟随系统，共 12 组：正文默认出现、无全页横向溢出/出界可见控件、桌面面板分隔不覆盖正文、拖动及键盘宽度限制、窄屏模态、Escape/焦点恢复、长对话收起按钮可见、收起后原阅读位置恢复。
- 窗口往返缩放、来源选择、查证与助手互斥；未发送文本恢复且节点未重建。
- 390 px 断网保存→拒绝切章→本地正文与 beforeunload 保护保留→明确原键恢复→成功切章，确认仅一次实际合成保存。

初轮人工截图检查发现手机实际正文仍被格式工具推到屏外，已修复并提高断言：正文区域进入初始视口后至少保留 100 px。最终正文起点为 1440/1280：609.69 px，820：675.47 px，390：727.25 px（390 视口高度 844 px）。实际截图已人工查看，390 页可见章节标题和正文段落；不是仅以容器边界代替正文可见性。

当前通过回执：`/tmp/tender-authoring-layout-browser/receipt.json`。代表截图：

- `/tmp/tender-authoring-layout-browser/body-light-390.png`
- `/tmp/tender-authoring-layout-browser/assistant-dark-1280.png`
- `/tmp/tender-authoring-layout-browser/sources-compact.png`
- `/tmp/tender-authoring-layout-browser/directory-save-failure-390.png`

完整源文件 SHA、用例结果及截图清单复制在 `authoring-assistant-layout-checks.json`。临时目录保留早期失败诊断；当前验收以 `receipt.json` 与仓库 checks 文件为准。

### 静态/构建

- `npx tsc -b --pretty false`：全应用通过。
- 本批源代码、测试与脚本 ESLint：通过。
- 本批 20 个代码/样式/测试/脚本文件 Prettier check：通过。
- `npx vite build --outDir /tmp/tender-authoring-layout-browser/vite-build`：通过（332 modules）。仍有混合静态/动态导入助手与大 chunk 提示；本批不宣称性能验收完成。

## 未执行与明确边界

未做真实项目资料、真实 Word/模型/OCR、真实发布与数据库验收；本批是前端布局与状态保护，不新增后端操作。未执行完整应用所有自动化；根代理在独立候选树做全量回归。未以本批代替完整 F12-14 的读屏工具、各系统软键盘、真实长会话/中断恢复及全部工作面可用性验收。

来源原件 `RetrievalDrawer` / `Evidence` 的桌面并排查阅仍属另一个软件项：本批保持其既有模态查证能力，并处理与助手的互斥。39 点其余残项由下一份只读 `ui-39-point-review.md` 逐项核对。

## 冻结文件

修改既有 5 文件：`AssistantDrawer.tsx`、`AssistantWorkspace.tsx`、`AuthoringPanel.tsx`、`ProjectWorkspace.tsx`、`SourceEditor.tsx`。

新增 15 文件：`AssistantDrawer.css`、`AssistantDrawer.test.tsx`、`AssistantSourceSurface.tsx/.css`、`AuthoringLayout.css`、`AuthoringLayout.test.tsx`、`EditorToolsDisclosure.tsx/.css`、`assistantDock.ts`、`useAssistantDock.ts`、`useAuxiliaryFocus.ts`、`useElementWidth.ts`、`workspaceAuxiliary.ts`、`authoringLayoutFixtures.test-support.ts`、`scripts/check-authoring-layout-browser.mjs`。

加本验收文档与 checks 回执，共 22 个 owned 文件。本批未 stage、未 commit，未改远端。
