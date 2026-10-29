# 契约

`design-source.json`绑定已审技术候选及逐文件摘要。`schemas`、`openapi`、`sql`、`policies`是目标设计快照，只作目标范围与建库输入，不表示全部接口已经实现。产品和技术主记录仍在`tender-docs`。

实际API契约由已实现应用生成到`implemented.openapi.json`，前端从实际契约生成首批类型。下列必要实现补充保持在实际API契约中，冻结目标快照不改：

| 补充 | 用途 | 约束 |
| --- | --- | --- |
| GET /auth/session | 刷新页面恢复HttpOnly会话及CSRF | 必须有效服务端会话；敏感响应no-store，不新增登录绕过 |
| GET /documents/{document_version_id} | 逐版读取真实原件元数据，使历史版本可发现 | 必须登录；返回真实head和previous链，不把历史稿设为当前稿 |
| GET /documents/{document_version_id}/evidence | 在未开始评审时发现PDF解析页及证据 | 登录可见范围，返回真实parse、coverage、gaps和证据，不把解析当作完成评审 |

只读补充由PM确认，实际实现仍需独立测试和架构review。其他实施差异须逐项记录，不能通过更改历史摘要使旧证据变成通过。
