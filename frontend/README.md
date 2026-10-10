# 施组工作台 · 前端

React 18 + TypeScript（strict）+ Vite + React Router + TanStack Query；界面用 Tailwind CSS v4 + Radix UI 原语（shadcn/ui 式的自有组件层）、cmdk 命令面板、sonner 轻提示、Recharts 图表、Lucide 图标。纯静态 SPA，中文界面，浅色／深色两套主题。视觉与交互依据 tender-design 仓库的设计稿与 tender-docs 仓库的《交互与视觉设计》。

## 开发、测试、构建

```bash
npm ci
npm run dev        # http://localhost:5173，/api 代理到 http://localhost:8000
npm run check      # prettier --check + eslint + tsc --noEmit + vitest run + vite build
npm test           # 仅 vitest
npm run build      # tsc --noEmit && vite build，产物在 dist/
```

- 代理目标可用 `API_TARGET=http://host:port` 覆盖（`dev` 与 `preview` 都生效）。
- 联调用真实后端：`backend/tools/smoke/smoke_server.py` 起真实 PostgreSQL + API + 进程内 worker（脚本化模型），播种一个项目并自动跑完一轮评审，账号 `demo` / `correct-horse-battery`。测试用 msw 在请求层模拟后端（`src/test/server.ts`、`src/test/fixtures.ts`）。

## 部署（nginx）

`dist/` 是纯静态文件，路由使用 history 模式，**必须配置回退**：

```nginx
location / { root /usr/share/nginx/html; try_files $uri /index.html; }
location /api/ { proxy_pass http://backend:8000; proxy_buffering off; }   # SSE 需要关闭缓冲
```

- PDF.js worker、CMap（中文原件需要）与标准字体随构建输出到 `dist/assets/` 与 `dist/pdfjs/`，不访问任何外部 CDN；Inter 与思源黑体（Noto Sans SC）可变字体随构建打包。图表库单独成块，只在报价、度量两页按需加载。
- 分片直传需要对象存储桶的 CORS：允许来源页面的 `PUT`，并 **暴露 `ETag` 响应头**；读不到 ETag 时界面会给出明确提示。

## 信息架构

上传即评审，报告为中心。全局侧栏是“项目总览”和“度量”；进入项目后是项目侧栏，顺序即流程：

| 页面           | 路径            | 内容                                                                                                                                                                                                                                                        |
| -------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 报告（落地页） | `/projects/:id` | 流水线横幅（资料→规则→核对→预测；进行中、中断可重试、等待手动开始、输入有更新）、结论卡片、下一步、响应矩阵（“无法判断／检查失败”醒目排前）、问题分类计数、评分预测（始终带“未校准”与原因；可按项目设置只显示失分点）、依据说明、导出 Word 报告与批注版 PDF |
| 问题           | `findings`      | 按分类分标签（废标／否决风险、强制性要求、前后矛盾、范围残留、改进建议）＋状态筛选，键集分页，详情里看正文证据与复核、改稿建议；依据未确认的问题有标记                                                                                                      |
| 依据           | `basis`         | 规则（按性质分组，废标／否决／强制在前，显示确认状态与评分条款分值）与事实库两个标签                                                                                                                                                                        |
| 报价           | `price`         | 评标价规则、竞争对手报价、候选报价；防抖实时试算、价格分曲线、换算关系与风险提示；保存与历史版本；项目关闭报价模块时不出现                                                                                                                                  |
| 提交与结果     | `submit`        | 登记提交（闸门条件逐项提示）与开标结果两个标签                                                                                                                                                                                                              |
| 资料           | `materials`     | 上传、版本与解析状态；上传后直接看到评审进度                                                                                                                                                                                                                |

工具：检索、设置（含功能开关）。任何页面按 Ctrl／⌘ K 打开命令面板：跳转项目内页面、切换项目、切换外观。<1024px 时侧栏收为顶部菜单，窄屏下表格逐行变成卡片。

登录方式是账号加口令（账号由管理员用 `bidwb-admin create-member` 创建），没有角色与成员管理：登录后所有项目、所有操作都可用。

**功能开关**（项目设置）：自动开始评审、规则按原文接受、前后矛盾检测、范围残留检测、显示预测分数、报价模块、提示登记开标结果。默认全部开启，只有“规则按原文接受”默认关闭。废标／否决检测与证据溯源是核心，没有开关。关闭的模块不出现在导航、报告和“下一步”里。

## 目录

```
src/api          client.ts（CSRF / Idempotency-Key / If-Match / 错误解析 / 401）、errors.ts、
                 endpoints.ts（与 openapi 路径一一对应）、types.ts（类型，注释标明对应的契约 $defs）
src/features     report（报告、流水线横幅、响应矩阵、预测面板）、findings（问题与改稿建议）、basis（依据页）、
                 rules、facts、price（报价与价格分曲线）、submit、outcomes、materials、upload（分片状态机）、
                 evidence（PDF.js 原页与检索）、metrics（度量与图表）、projects（总览与设置）、command（命令面板）、
                 auth、tasks、snapshots
src/components   ui/（button、badge、card、input、kbd、skeleton、tooltip：基础组件）、ui.tsx（页头、空状态、提示条、
                 字段、统计等页面模式）、Dialog、Tabs（Radix）、Toast（sonner）、Icon（lucide-react 的白名单）
src/lib          cn.ts、theme.ts（浅色／深色／跟随系统）、chartColors.ts（图表取主题色）、sha256.ts（增量 SHA-256）、
                 evidence.ts（bbox 换算）、labels.ts、format.ts、nextAction.ts、errorHints.ts、useIdempotentAction.ts
src/routes       App（路由，图表页按需加载）、AppShell（侧栏、用户菜单、命令面板）、ProjectNav、ProjectLayout
src/styles       index.css：设计令牌（:root 浅色、.dark 深色）、@theme 映射、基础样式与数据表格
```

## 关键实现说明

- **会话与 CSRF**：会话只靠 httpOnly cookie；`csrf_token` 只在内存。所有写请求带 `X-CSRF-Token` 与 `Idempotency-Key`；没有令牌时先取 `/me`。任意接口 401 时清空查询缓存并回登录页。
- **幂等键**：`useIdempotentAction` 把“一次用户动作”绑定一个键：原样重试复用，输入变化换新键，成功后重置。
- **错误**：按 `ApiError.kind` 分支（auth / stale / validation / unavailable / rate_limit …）；页面显示后端中文 `message` 与请求编号；412 保留用户输入；提交闸门等 409 按错误码补一句下一步（`lib/errorHints.ts`）。
- **流水线**：报告页轮询 `GET /projects/{id}/pipeline`，评审进行中时报告自动刷新；“开始评审”“重新评审”都是 `POST /projects/{id}/analysis`（失败环节重试，已完成环节不重做）。
- **上传**：`features/upload/uploader.ts` 状态机：本地增量 SHA-256（4 MiB 一块）→ init → ≤4 路并行 PUT（8 MiB 分片，失败退避重试 3 次）→ complete；预签名地址临近过期或 403 时刷新；失败后“重试”只补传未完成分片。上传表单可选“作为”某现有文件的新版本（`version_of_file_id`）。
- **原页**：`PdfViewer` 按 `physical_page` 渲染，bbox 为归一化 `[x0,y0,x1,y1]`（原点左上）；`bbox` 为空或非法时只显示整页并说明，不画高亮。
- **报价**：金额全程按十进制字符串处理，前端校验与后端一致；试算 `POST /projects/{id}/price:simulate` 不保存。
- **AI 标识**：候选（待复核的问题、未确认的规则、修改建议）使用石板蓝“AI 建议 · 待人工确认”；人工确认后回到中性标签。评分预测始终标“未校准”。
- **设计令牌**：颜色、圆角、阴影都是 CSS 变量，组件只用语义名（`bg-card`、`text-muted-foreground`、`border-border`、`bg-primary`、`danger／warning／success／ai` 各一组 soft／foreground／border）。中性灰底、单一松绿强调色、细线描边，阴影只给浮层；数字一律等宽（`tabular`）。
- **主题**：`public/theme.js` 在首帧前按 localStorage 的选择（缺省跟随系统）给 `<html>` 加 `.dark`，不闪白，也不需要内联脚本（CSP 友好）；用户菜单与命令面板可切换。
- **图表**：价格分曲线与逐轮趋势用 Recharts，颜色从当前主题的令牌读取；悬停看数值，同样的数值总以表格或文字给出，图有完整的读屏描述。结果分布等计数用带数值的横条。

## 范围外与有限

- 复检、项目助手未实现；改稿建议只有采纳／驳回，不支持提交人工编辑后的差异，采纳后需自行修改正文并上传新版本。
- 无障碍已按键盘、焦点、aria、对比度自查并有单元测试，没有做屏幕阅读器与完整 WCAG 验证。
- PDF 旋转页面没有坐标，只显示整页；非 PDF 资料不在线预览。
