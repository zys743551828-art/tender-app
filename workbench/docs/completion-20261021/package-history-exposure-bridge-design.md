# F06：原生整包与既有正文研究的共同暴露守卫

状态：已按分步审阅实现的独立可选增量。真实 PostgreSQL 的函数身份、权限、双向暴露、旧 API/CPU/研究 Worker 及并发栅栏已有实际验收；公开 main 挂载的最终收据见同目录 `package-history-exposure-bridge-acceptance.md` 与 checks 清单。所有输入为合成，不授予真实样本/模型资格。不会执行或修改旧 `retrospective-research.sql`，不会进入 BASE 或默认恢复清单。

## 1. 必须封闭的路径

当前原生历史研究已经拒绝旧治理 `exposure_members` 所标记的工程、正文和模板身份，但旧正文 `current_cohort` 不读取原生暴露记录。原生候选不能直接冒充旧正文样本；这仍不足以阻止同一原件或关联工程被重新导入为旧正文。新桥接必须同时保护新建 cohort、已存在 cohort 的资格重查，以及 Worker 在 claim/read/renew/finish 期间的每次新用途，不仅检查一个新查询接口。

官方结果更正和来源撤回继续由两侧原有当前性守卫处理。桥接保留所有原有拒绝条件。历史模型与报告仍可读；`current=false` 后不允许新数据读取、执行或发布。

## 2. 函数身份：保留原 OID

不能只把旧 `model_governance.current_cohort(uuid)` 重命名后再建同名函数。已解析语句、函数依赖及 SECURITY DEFINER 调用可能继续持有原 OID。

采用以下安装方法：

1. 在明确的新机制数据库安装阶段，检查两侧函数存在、参数/返回类型、语言、SECURITY DEFINER、search_path 和已审函数体摘要。任何不匹配都拒绝安装，禁止猜测或静默兼容。
2. 将旧函数体完整复制为 `package_history_exposure_bridge.legacy_current_original(uuid)`；保持原校验语义与固定 search_path，不赋予任何业务或 CPU 角色直接执行权限。
3. 对原 `model_governance.current_cohort(uuid)` 使用 **CREATE OR REPLACE，同签名、同 OID**，先调用完整旧守卫，再加共同暴露检查。安装断言替换前后 OID 完全一致。
4. 原生侧已有 `related_admissions`、`already_exposed`、`freeze_cohort`、`current_cohort` 同样保留 OID。只有经摘要核对的精确挂接位置被扩展，原 scope/submission/identity/source/label/proof/lease 检查全部保留。

实际测试必须在原路径已经调用/准备语句之后，证明旧 API 与 claim/read_training/read_final/renew/finish 都执行新守卫；不能以直接 SELECT 新 wrapper 代替这些测试。

## 3. 共同身份和完整闭包

新 schema `package_history_exposure_bridge` 保存 append-only 暴露闭包回执和原生 cohort 的跨命名空间闭包绑定。不创建旧 samples、模型资格或正式路由。

统一实体命名为 `package:<admission_id>` 与 `body:<sample_id>`。闭包使用已登记事实派生的键，不接受 API 指定关系：

- 明确工程、稳定标段、轮次、实交与原生范围身份；工程级关联是保守分组，不能靠换标段或轮次洗白同一工程。
- 原始目标字节与输入来源祖先字节。原生读取冻结 proof/context；旧正文读取样本原始实交、冻结 identity、正文、原依据/官方来源及已有 source bindings。不会挑 latest 解析授资格。
- 已有模板、近重复与源组关系；当前注册记录及已冻结记录中的既有别名均保留，纠正标签不能删除已经暴露的关系。

共同递归闭包包含没有被选进当前实验的桥接实体。容量超限明确拒绝，不截断、抽样或只检查选中行。新增桥接记录以后，现有 cohort 的闭包摘要不再匹配，必须失效。

原生 `closure_ids` 继续保存原生 admission UUID，扩展后的关联查询可经旧正文节点连接原生候选。完整旧/新实体、键和四时点关联另存不可变 `cohort_bindings`，与原 cohort ID/digest 和 membership digest 一对一绑定。跨实交边界判断使用共同闭包的全部实际提交时点；原有 `group_spans_submission_split` 排除语义保持，不能把旧桥接实体遗漏后视作独立 final。

## 4. 暴露回执与事务

在两侧 exposure 表安装受控 AFTER INSERT 捕获：与原 exposure 在**同一事务**固化完整共同闭包、命名空间、原 exposure ID、cohort 身份和摘要、模型/预测摘要及闭包摘要。任何捕获失败使原 exposure 事务整体回滚。

独立 evaluate 仍须先提交 exposure，再在不同事务读 final。桥接不能缩短此顺序，也不能撤销已经提交的暴露。共同守卫将两侧既有 exposure 与桥接回执一起检查，自己的同一 cohort/评估恢复可继续读取原 final；另建 cohort、改命名空间或把暴露来源重新用作 fit/development/calibration 均拒绝。

撤回、改名、结果更正、来源停用不会删除 exposure 或其历史闭包。新关系会使防漏边界扩大，不能让旧暴露失效。

## 5. 锁顺序和竞态

统一顺序为治理锁 `91143` → 完整相关 bid 排序锁 → 来源图锁 `90127` → 暴露锁 `91144`。原生 freeze/current 增补旧桥接 bid 范围必须发生在来源图锁之前。共同闭包计算和暴露检查处于同一治理事务，不另开无锁快照。

旧 Worker 的读取和 finish 已经经 `assert_lease → current_cohort`；保持原 OID 可让这些路径统一通过桥接。具体竞态应满足：

- 若 final 暴露先提交，旧 Worker 随后的 claim/read/renew/finish 都拒绝。
- 若旧读取先持有治理锁，暴露事务等待其提交；暴露提交后，旧 CPU 计算即使已经得到输入，也不得发布新结果。
- 若 finish 与暴露竞争同一锁，按实际提交顺序线性化；不能在暴露已提交后继续通过旧路径发布。
- 已完成结果内容保持只读。拒绝不会制造一个新训练结果或删除历史。

## 6. 私有 SQL 接口与安装依赖

已实现接口（除只读 readiness 外均为服务端私有；HTTP 无资格开关）：

| 接口 | 作用 |
| --- | --- |
| `entity_keys()` | 从原生/旧正文事实派生共同实体与来源键 |
| `related_entities(text[])` | 完整共同闭包，受容量限制 |
| `closure_snapshot(text[])` | 绑定实体、来源键、实际时点和分组事实的规范快照 |
| `related_bids(text[])` | 图锁前所需完整且排序的 bid 集 |
| `has_foreign_exposure(text[], namespace, cohort)` | 查询其他用途已提交的完整暴露闭包 |
| `bind_native_cohort(uuid, uuid[])` | 固化跨命名空间闭包与现有 cohort 摘要的一对一绑定 |
| `native_binding_current(uuid)` | 新关系/更正后的闭包当前性复查 |
| `legacy_current_original(uuid)` | 原旧守卫私有副本；任何业务/CPU LOGIN 直接调用均禁止 |

安装顺序为完整 BASE → 已审 `model-governance.sql` → `package-historical-admission.sql` → `package-historical-research.sql` → **独立可选** `package-history-exposure-bridge.sql`。本批原生 SQL 自身已依赖旧治理角色/暴露结构；旧治理尚未安装时，桥接以明确依赖错误停止，不自动初始化旧 WIP、不创建假空曝光表，也不声称已完成跨命名空间保护。BASE-only HTTP 继续显示未配置。

## 7. 实际验证要求

以新 PG17 独立库和真正的旧、新非 owner API/CPU LOGIN 验证：旧路径无暴露时仍可运行并保留官方零分；原生 final 提交后，同工程、同字节、经未选择桥接体相连的旧正文重导/旧 cohort/旧 Worker 全部拒绝；反方向同样拒绝；旧私有副本不能直接调用；暴露前缓存/准备的函数路径仍受守卫；读取/发布与曝光竞态实际阻塞并按提交顺序拒绝。所有数据和来源声明均为合成机制输入，零外部模型/费用，不作为真实质量或 F06 全部完成的证明。


## 8. 旧研究 Worker 的对象读取栅栏

旧 model-governance CPU RPC 的 current_cohort 守卫并不自动保护 `packages/research/worker.py` 在数据库事务外读取对象的 Python 路径。因此增加两个明确挂点：`heartbeat` 先执行原 `lock_run_scope`；`packages_for_item` 通过 `package_history_exposure_fence.source_read_fence` 的专用连接读取。原资料范围/来源/资格检查全部保留，optional bridge 未安装时仍执行原守卫，不因能力探测失败绕过。

专用连接取得 session 级 91143，核对 owned lease 并在仍有效时续租到120秒，随后提交元数据事务；对象 I/O 期间连接为 idle 且没有 xact_start，但 session 锁继续阻挡 final 暴露。对象读取后再次执行范围/资格校验，提交并关闭连接后才释放。独立 heartbeat 可以等待这个有限窗口；读取总时限固定45秒，包含连接、锁等待及对象读取，不能无限自阻塞。原租约已经到期时不复活。

当前受支持运行条件是 POSIX 主线程、没有外部活动 ITIMER_REAL。运行环境不符在任何对象读取之前明确拒绝；不会退回无栅栏读取。总 deadline 使用不可被普通 `except Exception` 吞掉的内部超时，再转换成明确领域错误。正常完成、对象异常、取消/KeyboardInterrupt 和超时全部关闭专用连接并还原计时器。此连接在跨提交后显式保留固定 SESSION search_path，避免 SET LOCAL 失效。

真实 PG 验收观察到对象 I/O 时 reader 连接 idle、独立 final 和 heartbeat 正在等待同一 advisory lock；关闭后按提交先后线性化。暴露已提交后实际旧 Worker 在第一字节读取前拒绝，acquire/heartbeat/reserve/finish 继续拒绝。异常/取消/真实超时后另一个非 owner 连接均能立即取得锁；实际短租约到期不能再次续命。测试没有调用 provider。

## 9. 公开核心入口的完整装配守卫

只安装原生 admission/research 两 SQL 不足以开放公开核心入口。`apps/api/package_history_public_gate.py::require_history_public_guard` 由 main 在整个 core router 上通过 Depends 挂载；10条核心 GET/POST 均受保护。独立目录只读元数据，不授资格，因此保留其自身 configured/metadata 行为。

桥接在同一安装事务末尾固化76个不可由业务角色修改的安装契约：58个函数、11个触发器、6个私有表及1个 schema。函数包含全部27个原生核心函数、原旧 current/lock/claim/read/renew/finish 等9个入口、20个桥接函数，以及 append_only/lock_worker_bid；保留 OID、owner、完整定义摘要和 ACL。触发器保存 relation/function OID、定义摘要与启用状态；私有关系/schema 保存 owner、ACL和列权限。目录的6个只读函数不属于资格契约，独立追加目录不会改变核心资格。

`readiness()` 是唯一可被 tender_api 调用的桥接函数，STABLE SECURITY DEFINER、固定 pg_catalog/pg_temp，只读取安装元数据，拒绝 owner/混入高权限的运行 LOGIN。API 在 READ ONLY 事务内先核对 readiness 自身固定函数体摘要/签名/可信 owner，再以同一语句观察核验当前全部契约；函数缺失、身份不符、依赖漂移或 SQL 失败一律503。返回 ready 只表示守卫装配当前吻合，`qualification_granted=false`。

旧私有实现、闭包查询、契约表与 helper 无 API 或 CPU 直接权限；API 只获 schema USAGE + readiness EXECUTE，不能在该 schema 创建替身。metadata 已登记后，禁用 exposure 触发器、改写旧 current_cohort、误授私有 EXECUTE 或伪造 readiness 均使生产 HTTP 入口拒绝。此检查以数据库初始化 owner 与部署的固定程序为信任根，不能声称防御恶意超级用户改写整个数据库和程序。实际旧守卫仍由数据库执行，readiness 本身不替代业务锁内当前性核验。

原生两 SQL 的 standalone 机制测试明确移除并还原 core 模块路由，不改变生产应用。公开 gate 验收直接使用 main 中原有10路径，先断言每条都有依赖且没有无守卫重复路径，再测半装503与完整正向；不通过替换测试 router 掩盖漏挂。
