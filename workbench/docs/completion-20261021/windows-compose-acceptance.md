# 合并主线的 Windows Compose 预览验收

应用基线为 PR #1 合并提交 `784c038de0d22d15660c8683adbf8686e0394178`。本次使用已有 PowerShell 7、Node 22、Python 虚拟环境及 Docker 镜像，在固定 `tender-fusion` Compose 组验证；未启动旧 dev／Claude 容器、付费通道或后台自动接续。

## 已验证

| 检查 | 实际结果 | 边界 |
| --- | --- | --- |
| 完整前端 | 176文件、1,731项通过，243.44秒 | 使用本机现有依赖，minWorkers=1、maxWorkers=2；初次线程上下限冲突未运行任何测试，原日志保留 |
| Linux配置与历史研究 | 161项通过，11.98秒 | 固定Compose checks服务；初始化、角色引导、完整运行配置结构、私有文件及严格历史研究纯机制；不是完整运行组容器验收 |
| 原生整包接口 | 66项通过，157.58秒 | 独立检查库、实际PG与非owner接口；包含核查、人工决定、复检对比、报告、生成采用与独立解析；7条既有依赖警告 |
| 实际契约与生成 | 4项通过，4.73秒 | 实际完整OpenAPI、确定性gzip、生成器及锁定Prettier输出一致；格式器直接经Node调用，兼容Windows |
| 静态与构建 | 前端format／lint／TypeScript／生产构建，改动Python Ruff／format／mypy／Bandit通过 | 保留既有主包体积及混合导入提示；不据此证明真实模型效果 |
| 5188实际HTTP | 1,140个运行输入、65个JS／CSS资源逐字节匹配；登录、会话、退出通过 | 不写业务项目；登录会话及认证审计按真实接口产生 |
| 默认数据库 | `tender_checks_fusion_v14`，136张design表、37项BASE SQL；受限非owner API、依赖计划只追加 | 项目、冻结输入、prepared与依赖计划均0；v8、v7保留；不把可选研究扩展算作默认安装 |

API、Web与数据库healthy，init退出0；checks及checks-postgres已停止，专用测试库／角色均0。前端没有QA夹具。部署仍使用开发只读源码挂载，运行输入回执是启动观察，不是不可变发布镜像证明。

严格历史研究公开入口在默认预览返回503 `PACKAGE_HISTORY_PUBLIC_GUARD_UNAVAILABLE`，与可选完整装配尚未安装的实际状态一致。没有将未装配能力伪装为已运行。完整Kafka／S3／Worker链必须另用完整运行配置验收。

## 本机修正与保留

- `public/theme.js`固定LF，避免Windows检出后出现纯换行格式失败；不修改冻结历史证据。
- OpenAPI生成测试使用实际Node及锁定Prettier脚本，避免Windows直接执行Unix shim。
- 新增固定`delivery-pure`检查套件，复用同组检查服务和现有镜像，读取锁文件及已构建前端，不建立零散临时容器。
- 原本机范围核验WIP完整保存在Git stash `9bbbbe2cedd04070343b646935e540c83342e15f`，含未跟踪文件。尚未重放到新主线；须核对功能重叠、当前gzip契约及整包核查实现后再决定吸纳，不能直接覆盖新主线。

## 未验证

内置浏览器初始化失败：应用加载器引用不存在的`browser/26.1016.62342/scripts/browser-service.mjs`，本机现有插件目录为26.1013.40934等旧版本。本轮未进入浏览器发现或页面控制阶段，不能归为网站无法连接，也不能沿用旧截图宣布视觉通过。未修改签名应用、沙箱、安全控制或浏览器个人数据；应用／插件安装关联需另行恢复后补实际界面验收。

本次尚未完成完整运行组Compose、受控转换隔离、真实资料／排版、正式评分方法与配对精度、独立生产主机恢复和全39点用户验收。真实业务效果继续保持未验收。

原始命令结果、失败日志、测试XML、运行资源摘要和数据库观察见[evidence/windows-compose](evidence/windows-compose)。初次Windows默认临时目录检查为53通过／4个setup错误，未授通过；相关私有文件行为由上述Linux套件覆盖，没有放宽权限。
