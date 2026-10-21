# 整包历史研究切片：机制验收与接线交接

此切片已有 28 项纯逻辑测试、17 项真实 PostgreSQL 测试通过；数据库分为 10 项核心、6 项 HTTP／完整分组、1 项真实租约过期独立运行，完整收据见同目录 `package-historical-research-checks.json`。所有原件、历史事件声明、完整图文证明和签名来源都是显式合成输入。0 次外部模型请求、0 次付费调用；不代表真实历史样本合格、真实精度或 F06 全部完成。

## 接线清单

1. 独立 router：`apps.api.package_historical_research.router`。生产 main 已为全部10条核心路径挂 `Depends(require_history_public_guard)`；只安装原生两 SQL 时全部503。standalone机制测试显式移除/还原本模块生产路径，不能用作未安装bridge的公开入口。
2. 独立实际 OpenAPI：`packages.contracts.package_historical_research_api.extend_openapi`。响应 schema 已包含严格类型的准入、四时点 cohort、owned job、训练模型和最终评估报告。
3. 可选 SQL 顺序：完整 `BASE_SQL` → `deploy/sql/model-governance.sql` → `deploy/sql/package-historical-admission.sql` → `deploy/sql/package-historical-research.sql`；生产公开核心还须显式安装已经验收的 `deploy/sql/package-history-exposure-bridge.sql`。不要加入 BASE 或默认恢复计划，不安装旧 WIP `retrospective-research.sql`。
4. 核验进程依赖：`requirements-package-history.txt`。Pillow 仅用于真实原图片字节验证；不能用签名代替内容真实性审查。
5. 专用入口：`deploy/package_history_worker.py`，用途 `verify`、`train`、`evaluate`。每个 profile 只能有一个对应 DSN，0600、普通文件、非符号链接；子进程仅继承该 DSN 和固定 locale/timezone，不继承主应用、对象存储、供应商或 owner 凭据。

固定命令运行一个确切 owned job。当前有独立 heartbeat、generation/fence、120 秒租约、暂停/恢复与完成重放保护，尚未新增自动轮询或 Kafka 调度服务。

## 实际公开路径

选定原生 saved scope 的基址：

`/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}`

- `GET /historical-admission-context?submission_id=...&outcome_id=...`
- `POST /historical-admissions`

独立研究基址 `/api/v1/package-historical-research`：

- `GET /admissions/{id}`、`GET /cpu-protocol-template`
- `POST /protocols`、`POST /cohorts`、`GET /cohorts/{id}`
- `POST /cohorts/{id}/jobs`、`GET /jobs/{id}`、`POST /jobs/{id}/control`

没有普通 API 配置可信来源、上传证明授资格或切换合成环境的入口。API 引用既有专用 verifier 回执；证明来源只能在独立部署初始化时配置。

五个 GET 均有独立严格查询参数守卫。准入上下文只接受唯一的 `submission_id` 和 `outcome_id`；其余四个 GET 不接受查询参数。相同值重复、不同值重复以及未知参数都以 `PACKAGE_HISTORY_QUERY_INVALID`／422 拒绝。完整公开守卫可用后，该补充在认证后、核心上下文读取前执行；公开装配守卫只读元数据在此之前校验；没有改变 SQL、CPU 协议、锁内 context/ETag 复核或原请求优先重放顺序。

实际 HTTP／PG／CPU fixture：`/tmp/tender-review-current/package-historical-research-http.json`。其中保留真实回执与 ETag、官方 0 分、条件写入、暂停/恢复和评估报告；不含口令、会话、签名私钥或真实私有原件。

## 验证覆盖

| 范围 | 已证实机制 |
| --- | --- |
| 精确绑定 | 原生 scope、包修订、实交及 submission binding、完整 v2 主体/工程/标段/轮次、官方当前结果和核验决定；错主体、lot、round 均失效 |
| 历史证据 | Ed25519 真验签、原件/来源原字节 hash 与 size、完整资源清单、存在/取得/发布/生效的明确时间与对象、完整物理页/图像/条款映射；未来时点、缺页、字节篡改、未知聚合均拒绝 |
| 资格边界 | 签名只证明来源及声明完整性；可信来源适配器是可配置接入方式之一，真实事实仍需来源能力、原件和时点语义证明；未配置真实来源时明确缺口 |
| 独立权限 | API、verifier、train、evaluate 为实际独立非 owner LOGIN；train 无 proofs、native context、官方原件/标签源、final 导出、API 会话及 evaluate RPC 读取权限 |
| 冻结与分组 | 四时点冻结，全部已登记候选参与传递闭包，包括未选中桥接候选；跨实交边界整组排除，标签迟到为 unknown，不能转换成 0；新增关系使原 cohort 失效 |
| 实际 CPU | 项目等权 mean/median 的真实训练、development 选择、固定后 final 预测；独立 evaluate 复用分组统计，官方 0 分正常计算，未标注/被拒样本保留分母 |
| Final 暴露 | 原生同 cohort 完整成员/预测/闭包先持久提交，下一事务才能读取 final；另建原生 cohort 不能重选；同事务打开并读取失败且事务回滚 |
| 运行恢复 | 真正等待 120 秒租约过期后新 owner 取得 fence=2，旧 token/fence 不能发布；完成重放不增加结果，暂停/恢复增加 generation |
| 撤回与更正 | 来源撤回、适配器撤回和官方结果更正阻断新 job/读取/发布；历史结果和原 0 分仍只读，不回退旧 head 授资格 |
| HTTP | 真实 session/CSRF、显式 ID、ETag、幂等原 ACK；五个 GET 的 14 种重复／未知参数反例均为 422；撤回后原请求仍重放原回执；standalone BASE-only context 明确 unavailable、写入503；生产公开core缺完整bridge时全部503，无500 |

## 本切片不覆盖的后续软件工作

跨旧正文 namespace 的反向曝光桥接已作为独立增量通过13项真实PG验收，含旧 API/Worker、同 OID缓存语句、私有ACL、对象I/O及并发栅栏；见 `package-history-exposure-bridge-acceptance.md`。生产main的公开core必须经过该完整装配检查，桥接未安装时明确拒绝。核心两SQL本身仍不能单独声称跨命名空间完整防漏。

本片没有原生整包三判断特征到 ridge 等校准训练的正式闭环、真实资料的质量验收、业务接受门槛签发、正式模型发布/回退或自动任务调度部署。mean/median 基线不冒充三判断特征，不补造正式训练样本、事前预测或在线误差资格。后续的软件接线与真实证明资料各自列明，不能把可实施的软件缺口归给用户材料。
