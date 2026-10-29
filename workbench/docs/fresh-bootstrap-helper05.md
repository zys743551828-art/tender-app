# Fresh 引导工具预算管理员隔离守卫

本修订只关闭 helper04 的 H04 权限继承反例；归档 SQL、冻结证据及原运行结果保持不变。预算 SQL 其他阻塞仍须独立修复和验证，通过本守卫不构成执行预算 SQL 的资格。

## 契约

- 执行已审 SQL 后、新建任何 LOGIN 前，预算能力组必须满足原有 NOLOGIN / 危险标志检查，且递归上游 membership 为空。任何祖先角色均拒绝，不因 NOINHERIT 或 SET 选项而忽略路径。递归使用 UNION 去重。
- 新预算管理员真实连接通过现有身份、危险标志及业务表 owner 检查后，直属 membership 必须精确等于 `tender_assistant_budget_admin`，且不能带 ADMIN OPTION；再次检查能力组上游闭包。
- 使用预算 LOGIN 自身查询 PostgreSQL effective privileges，包含 PUBLIC、直接、继承、列权限和PG17 MAINTAIN。仅允许对 `design.assistant_price_versions`、`assistant_budget_versions` 的 SELECT/INSERT，对三张 intent/reservation/event 表的 SELECT，及精确签名的 `assistant_reconcile_budget` 执行。其他 design/retrieval/model_governance 表、序列、函数权限或 schema CREATE 均拒绝；即使是白名单函数，也不能由预算 LOGIN 或其成员角色拥有并改写。空结果同样拒绝。
- 所有真实 LOGIN 验证通过才写业务及用途配置。预算 DSN 仅在专属用途配置和原有初始化恢复配置中，不进入业务配置。初始化 owner 不补业务权限；失败不自动回滚/删除数据库或资源，保留原有一次性 fresh 恢复边界。

## 验证与限制

离线新增 12 项检查通过，覆盖 H04 直接/多跳上游、额外或缺少 LOGIN 组、ADMIN OPTION、未知 effective 结果、禁止权限和配置隔离。原 purpose-profile 流程的模拟 catalog 同步补齐单一 membership。Windows 原完整测试初次结果为 32 通过、26 失败；失败涉及已有 POSIX chmod/0600 和 symlink 权限假设，未放宽权限守卫或用 skip 隐藏，完整原回归须在 Linux 复跑。

独立PG17.11临时库已执行14项实际检查：正常非owner预算LOGIN、预算组→API、多跳NOINHERIT路径、LOGIN额外组、ADMIN OPTION、PUBLIC表权限、直接列授权、额外函数执行、schema CREATE、序列权限、直接／继承函数owner、业务写入与MAINTAIN。交叉评审发现的MAINTAIN与继承owner先各复现一次未拒绝，再补守卫并复跑；14项及12项纯检查全部通过。Linux临时文件系统中原引导测试加新纯检查59项通过。

这些结果证明实际effective ACL反例已阻断，不代表已执行全应用初始化、预算完整链或运行期持续权限审计。最小PG夹具没有写可运行业务配置，完整fresh组合仍按F02验收。

角色或 ACL 在检查后被集群管理员修改不属于一次性引导可永久阻止的行为；运行期管理员管理和独立验收仍须另行实施。本工具不连接既有目标库，不启停任何业务服务。
