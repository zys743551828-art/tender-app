# 独立原件解析前端检查点

## 实现范围

入口为 `apps/web/src/DocumentParseWorkspace.tsx`，参数为 `bidId`、`memberId`、`documentId`、可选 `disabled`、可选 `onParsed(DocumentParseView)`。

- 默认收起，挂载和展开均不自动发送 RPC。用户明确读取条件、填写理由后申请。包内大量成员不会因挂载产生解析条件与历史的并发请求。
- 待恢复请求会自动展开，但不自动重发。恢复使用原始成员、项目、文档、请求 key 和 body；项目只读时仍允许恢复及读取历史。
- `document-parse` 恢复记录登记到 `recordedCommandStorage`，遵守退出、换成员清理。新申请先写恢复记录，配额失败时不发送 POST。
- `COMMAND_INCOMPLETE`、`IDEMPOTENCY_CONFLICT`、作用域异常、网络错误、身份验证与未知错误保持原请求；明确条件变化等已知拒绝会释放 pending，并要求重新读取条件。读取当前条件不会覆盖原请求。
- ACK 校验当前申请成员及 canonical 请求摘要；合法复用允许原解析记录来自其他成员，保留原申请者与原理由。不同成员的请求不冒充当前申请者。
- 稳定 ACK 后读取精确 request 状态，每三秒轮询活动任务。已确认终态及结果不能退回或被替换；旧排队 ACK 的再次恢复不会覆盖已读到的终态。
- 已验证的后台任务会通过现有 `rememberOperation` 索引到本浏览器的处理记录；可从既有任务中心取消。索引保存失败不改变已受理状态、pending 或服务器历史。
- 运行终态和解析覆盖分别显示。`succeeded + coverage=failed` 如实显示无可用覆盖；物理文本方式不接受完整覆盖声明，Word 覆盖标记始终为 false。
- `onParsed` 只通知已校验且有结果的终态记录，供父入口刷新服务端解析列表，不选择解析、不改材料或正文、不启动评审。
- 历史使用每页 10 条替换显示，核验作用域、顺序、重复 ID 和游标。损坏的本地恢复记录不会阻断只读历史。
- 原页预览独立读取精确文档版本、用途与下载授权，再核对实际字节长度和 SHA-256。没有调用仅返回最新解析的 `/documents/:id/evidence`，避免历史解析串版本。

## 验证

在 `workbench/apps/web` 执行：

```bash
./node_modules/.bin/vitest run src/documentParseProtocol.test.ts src/documentParseRecovery.test.ts src/DocumentParseWorkspace.test.tsx src/DocumentParseOriginal.test.tsx --reporter dot
```

当前结果：4 个测试文件、41 个测试全部通过（测试日志本地时间 2026-10-20 15:45:02）。限定新增源码的 ESLint 无报错。

测试使用明确的 synthetic protocol fixture、模拟 HTTP 回执及浏览器存储。覆盖精确摘要绑定、跨成员复用、部分与失败覆盖、旧 ACK、关闭项目恢复、存储写入前后失败、卸载与文档切换、历史分页及原页实际字节校验。原页测试替换了 PDF renderer，只验证正确文件到渲染器的边界；不代表 OCR、真实 PDF 绘制、版式或浏览器视觉验收。

独立组件检查时，官方五个 DTO 和能力目录曾等待统一生成；组件测试显式声明合成服务具有对应能力。最终集成已生成 `DocumentParseContext`、`StartDocumentParse`、`DocumentParseView`、`DocumentParseStarted`、`DocumentParsePage`，并将实际路由写入实施版 OpenAPI。生成后全项目 TypeScript 与 Vite 生产构建通过，完整前端回归 91 个文件、764 项通过。后端真实 PG、解析适配器及原页渲染的验证由对应主线分别记录。

## 本轮边界

不自动将解析结果选入包成员。取消沿既有任务中心能力，本独立组件当前展示取消状态但未新增取消按钮。Word 原件须经受控 PDF 转换才能进入此解析路径，历史读取仍独立可用。
