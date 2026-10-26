# FR-002 阶段一：独立业务门槛冻结入口

用户已同意版本化、无默认门槛、final 前冻结及真实证据治理方向。本阶段是其中最小冻结闭环，**不是认证签发或正式预测闭环**。不配置真实阈值、不签发真实模型、不启用调用。

## 实际代码与调用

- `POST /api/v1/model-admission/cohorts/{cohort_id}/protocol`：登录、Origin/CSRF、稳定 `Idempotency-Key`；body 只有 `document` 和具体 `reason`。
- `GET` 同一路径读取不可变历史回执。只允许现有 cohort 的创建者且成员仍有效；不是新增角色或管理员授权入口。
- document 封闭字段：`schema=score-business-admission-protocol/1`、`artifact_family=registered-score-artifact/1`、`baseline`（mean/median）、`thresholds`。thresholds 必填 `maximum_project_mae`、`minimum_paired_baseline_gain`、`minimum_success_coverage`、`minimum_interval_coverage`、`interval_level`，没有默认值。误差/增益与现有评价归一化 0–100 尺度对应，coverage 为 0–1，interval_level 必须严格在 0–1 内。这里只冻结声明，尚不读取指标或判断通过。
- 任何 `accepted`/`origin`/资格声明、训练协议标签或 `/3` artifact 标签均拒绝。测试里的数值仅是反例/机制夹具，不是推荐门槛。
- 应用层只依赖标准库与 Store Protocol；数据库适配器在单次连接/事务中执行原生冻结或读取，HTTP 仅做认证和错误映射。连接错误不声称事务未提交，操作者应使用原 key/body 恢复。

可使用既有登录客户端向上述 POST 提交已明确决定的文档，然后用同一 key/body 重试或 GET 读取。不提供自动填入数值的示例或一键批准按钮。本阶段没有新增专用 UI；实际 API 与完整 actual OpenAPI 已挂入现有服务，正式预测 UI 仍不可用。

## 原生边界与安装限制

`deploy/sql/model-admission-protocol.sql` 是**可选全新初始化**扩展，要求现有跨通道曝光桥已安装、旧 cohort 为空；不执行热补丁、不加入默认部署、不新增 LOGIN。使用既有 tender_api 与 cohort/member 权威。表无 API 直接写权限，append-only；写入由受控函数完成。

第一次冻结沿用 `91143` 来源锁、`current_cohort` 的全局关联身份/来源复验及曝光桥 readiness，再取得既有 `91144` 曝光锁。拒绝自身已曝光和跨 cohort 的 sample/group/project/body/template/near-duplicate 身份曝光；桥处理跨 `/3` 通道关联。两通道原函数及其冻结摘要未修改。冻结保存 cohort 摘要和数据库生成的 JSONB 文档 SHA（明确为数据库 JSONB 文本编码，不冒充 Python canonical JSON digest）。

同 cohort 只允许一份协议；不同 key/body/reason 拒绝。丢 ACK 的同请求返回原冻结记录，即使后来来源失效，也**不**返回当前资格：`current_source_verified=false`、`certification_issued=false`、`formal_eligibility=unavailable`。后续签发/消费必须另行复验当前来源、时序、版本及权威证据，不能把此历史回执当认证。

## 已验证与未验证

定向机制/API/OpenAPI 28 passed；包含所有门槛缺失、数值强转/非有限/超界、版本混用/资格字段、可变数据隔离、认证调用、连接异常/取消释放。现有 Starlette/anyio 一条弃用提示。

SQL 权限/锁序静态断言不等于真实并发验收。当前无 PostgreSQL 工具，Docker 镜像列表为空；未拉取镜像、配置 DSN、执行 SQL 或创建权限。原生重放/并发曝光/跨成员/撤回和回滚仍须在已审隔离环境执行，不能被本地模拟测试代替。

## 剩余有限编码顺序

1. 复用原生 `/3` cohort/模型/曝光权威，明确版本化适配与等价的业务门槛冻结；本阶段只接受旧 registry artifact，绝不静默互换。
2. 独立报告、影子观察、回退验收权威绑定与认证生命周期（有效期/撤销/审核权限），消费冻结门槛；不能由调用者 verified 布尔值代替。
3. 合格模型→固定业务输入→预测持久化/恢复→review/API/UI/报告隐藏投影与 metrics 配对。资格不齐继续不可用。

FR-001–013 有限需求映射仍见 `fr-audit.md`：本次没有把 FR-002/009/011/013 的关联缺口标为完成，也不把其他 FR 的既有代码当真实用户验收。环境验收与真实配对数据缺失仍单列，不无限增加产品范围。

完整回归：后端 4415 passed、2424 skipped、0 failures/errors；前端 192 文件、1944 tests passed。ruff/format（1155 文件）、mypy（715 源文件）、bandit 及前端 format/lint/typecheck 通过；actual OpenAPI 和生成类型一致。四个材料方法摘要未变。原生并发/权限/丢 ACK 的 SQL 仍未执行，跳过不算通过。
前端构建通过，保留既有 chunk-size 警告；没有部署或外部调用。
