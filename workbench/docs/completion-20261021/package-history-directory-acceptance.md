# 历史研究元数据目录验收

## 本批完成的范围

新增四个独立 GET 目录：历史准入记录、冻结 CPU 协议、冻结研究组及组内任务。目录返回明确身份、原记录时间、状态和分页观察；不会读取官方分数数值、原件字节或模型输入，不调用资格核验 RPC，不创建命令、审计、暴露记录或任务。

记录存在不表示可重新训练或评估。每项固定带 `current_status=not_rechecked`，整体带 `currentness_rechecked=false`、`qualification_granted=false`、`research_only=true`、`formal_eligibility=unavailable`。后续详情与命令仍须执行原有当前资格、最终评估暴露及完整共同守卫检查。此批完成 API 目录，研究操作界面另行接入。

| 目录 | 路径 | 可选筛选 |
| --- | --- | --- |
| 历史准入 | `/api/v1/package-historical-research/admissions` | `bid_id`；同一项目下的 `scope_id` |
| CPU 协议 | `/api/v1/package-historical-research/protocols` | 无业务筛选 |
| 研究组 | `/api/v1/package-historical-research/cohorts` | `protocol_id` |
| 组内任务 | `/api/v1/package-historical-research/cohorts/{cohort_id}/jobs` | 路径中的明确研究组 |

每页 1–50 条，完整目录观察最多 2,000 条。超预算整体拒绝，不把截断数据当作完整观察。API 拒绝未知或重复查询参数、只给范围却没有项目、其他项目的范围以及不存在的协议或研究组。

## 数据库与部署边界

`deploy/sql/package-history-directory.sql` 是可选扩展，依赖既有基础库及 `package-historical-admission.sql`、`package-historical-research.sql`。它不加入 `BASE_SQL`，不改变 Fusion v14 默认恢复集合，也不安装旧的未完成 retrospective SQL。

四个固定 SECURITY DEFINER 入口仅授予实际 API LOGIN 调用资格；私有辅助函数不可由业务角色调用。每次请求在一个 `REPEATABLE READ, READ ONLY` 事务里完成，查询超时为 20 秒。目录专用角色检查与原核心要求 READ COMMITTED 的资格 RPC 分开，不能通过放宽原核心事务边界取得读取能力。

BASE-only 新库缺少目录 RPC 时，四个响应均为 `status=unavailable`、`schema_configured=false`，并保留 `total=null`、`has_more=null`、`observation_digest=null`、`complete_observation=false`。这与“已观察到零条记录”不同。公开研究核心入口还要求完整 exposure bridge；元数据目录本身不授予任何研究执行资格。

## 分页与记录变化

排序为原创建时间降序、ID 降序。API 签名游标绑定目录种类、全部明确筛选、完整目录观察摘要和上一项身份。换目录或筛选不能复用游标；游标被修改、存在重复 JSON 键或非规范身份均拒绝。分页间发生新增、任务状态或其他目录观察变化时返回 409，用户须从首页重新读取，不拼接不同观察的结果。

历史条目在来源撤回后仍可发现，并继续标为“当前性未重查”。真实详情检查会显示不再当前，目录不会将撤回记录重新变成可用资料。任务目录保留实际 generation、状态和结果是否存在，但不返回租约令牌、任务 payload、私有文件位置或官方分值。

## 实际验证

最终独立数据库运行：**5 passed，0 failed，0 error，27.46 秒**，PostgreSQL **17.11**。使用真实独立 API、验证、训练、评估和 Worker LOGIN；HTTP 走实际登录与 ASGI 路由。测试创建的原件和来源证明为明确的合成材料，签名核验器实际运行，付费调用和外部供应商调用均为 0。

五组原生证据覆盖：

1. 四目录真实返回、暂停任务后的状态与 generation 更新、目录读取前后的业务写入计数不变、来源撤回后历史可见但详情不再当前。
2. 签名 keyset 分页、不同目录游标拒绝、篡改拒绝以及并发新增导致旧观察返回 409。
3. 同一 RR 事务稳定读取、API 不能直接读取研究表或私有辅助函数、验证/训练/评估/Worker 角色不能调用目录、READ COMMITTED 调用被拒绝。
4. 实际 HTTP 重复/未知参数、范围缺项目及外来范围、协议、研究组的拒绝。
5. 另建 BASE-only 新库，四目录均明确不可用且计数未知。

另有 **20 项纯协议测试**，覆盖签名范围、重复 JSON 键、规范 UUID、未知字段、缺能力响应和连接数据库前的筛选拒绝；这些不替代真实 PostgreSQL 验收。三个产品 Python 文件通过 mypy、Bandit；五个新增 Python 文件通过 Ruff 与格式检查。

首轮原生运行停在缓存头断言：应用中间件将 `private, no-store` 规范化成 `private,no-store`。测试改为忽略分隔空格后重跑通过，产品 SQL/API 没有为此改动。初始结果与最终结果分开保留。纯协议首次运行因测试未注入合成 SESSION_SECRET 失败，补齐独立测试配置后 20 项通过，生产签名配置要求保持不变。

完整源摘要、SQL 依赖、最终原生收据及限制见 [目录检查记录](package-history-directory-checks.json)。整合路由、实际 OpenAPI、完整前后端回归属于本批后续检查点验收，不用以上定向结果替代。
