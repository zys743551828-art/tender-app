# F06：共同暴露守卫与公开入口验收

## 交付结论

本批是原生整包历史研究与既有正文研究之间的独立可选暴露守卫。软件已真实执行 PostgreSQL 的原函数 OID 保留、私有权限拒绝、双向完整闭包隔离、已暴露资料重导/重选拒绝、旧 API/CPU/研究 Worker 路径和实际并发栅栏。公开历史 core 的10条生产入口还必须通过完整装配检查；仅装原生两份 SQL 时全部明确503，目录元数据独立可用。

所有原件、官方标签、发行方签名、模型特征、来源证明和实验均为明确合成机制输入。正向 CPU 是实际运行，但不代表真实资料已经合格或模型精度达标；provider请求0、费用0。旧 v1 fixture 是显式建库合成的既有历史记录，不是通过削弱现行 v2 identity 或官方来源校验制造的合格样本。官方0分保持0，unknown不补0。

## 文件与安装

实现边界：

- `deploy/sql/package-history-exposure-bridge.sql`：同事务摘要核验、保留 OID 的挂接、完整共同闭包、不可变暴露回执、触发器及只读装配契约。
- `apps/api/package_history_public_gate.py`：生产 core router 的 mandatory Depends；只读核验固定 readiness 身份和完整当前契约，缺失/漂移503。
- `apps/api/package_history_exposure_errors.py`：仅翻译确切暴露冲突为409，保留原数据库错误处理。
- `packages/research/package_history_exposure_fence.py` 与既有 `packages/research/worker.py` 两个明确挂点：读取对象前和 heartbeat 的共同守卫；session fence 贯穿对象 I/O。
- `tests/package_history_legacy_fixtures.py` 与 `tests/test_package_history_exposure_bridge_pg.py`：真实独立 LOGIN、actual old API/CPU/Worker 与生产 main 挂载的 PG 验收。
- `tests/test_package_history_pg.py` 仅作已批准的 standalone fixture 修正：生产路径与原生两 SQL 机制路径明确分开，测试结束还原完整应用。

完整依赖顺序：BASE → `model-governance.sql` → `package-historical-admission.sql` → `package-historical-research.sql` → `package-history-exposure-bridge.sql`。目录 `package-history-directory.sql` 可独立追加；它不授资格。缺旧治理依赖时 bridge 明确拒绝安装，不自动建立假空表、不执行旧 WIP。所有 bridge 安装改动处于显式事务，依赖摘要不匹配整批回滚。**本批不进入 BASE 或默认恢复清单。**

main 的挂载由 root 完成：core router 带 `Depends(require_history_public_guard)`，目录独立，数据库 handler 注册以后安装 exposure error translator。公开 PG 测试直接使用 main 的这10条路径，断言无重复/漏守卫；不会由测试替换 router 掩盖生产漏挂。

## 已执行反例与实际正向

| 验收面 | 实际观察 |
| --- | --- |
| 函数身份/安装 | 原 current_cohort 的 OID不变；原13个入口签名/函数体摘要不符则安装整体回滚，没有半装 schema |
| 私有 ACL | 旧私有 original 对9类独立非owner LOGIN均拒绝；API不能读契约表、调用私有helper或在bridge schema建替身 |
| 无暴露正向 | 实际旧 HTTP protocol/cohort/jobs 与专用 train/evaluate CPU通过；真实官方0值保留；预先缓存的 SQL 能继续正确执行 |
| 原生 final → 旧路径 | 实际 exposure 提交后，旧 current/cohort新发布/claim/read/renew/open_final/finish及旧CPU入口均拒绝；原旧报告保留只读 |
| 已解析路径 | 在安装前 PREPARE/EXECUTE 的 current、claim、read、renew、final和research scope在安装后仍走同 OID守卫 |
| 暴露并发 | 旧读事务先持治理锁，原生open_final实际等待；提交后暴露成立，旧发布拒绝。按提交顺序线性化 |
| 追加未选关系 | 已暴露记录的原snapshot不改；后来未选择的unknown桥接体扩展当前闭包，不能重建cohort、换项目/轮次/命名空间洗白 |
| 来源撤回/身份别名 | 旧源组和来源字节关联保留；撤回不删除已暴露事实；既有身份或known_at不能被静默改写 |
| 旧 final → 原生 | 旧actual CPU final已暴露后，原生新cohort被拒；既有报告仍读得到0分 |
| 研究 Worker 读前阻断 | 无bridge时仍执行完整原守卫；bridge后暴露已提交时实际 packages_for_item在第一个对象字节前拒绝，模型请求0 |
| 对象I/O栅栏 | 读对象时reader PG连接idle、xact_start为空，session91143仍持有；实际独立final和heartbeat在同锁等待 |
| 取消/异常/超时 | RuntimeError、KeyboardInterrupt、真实1秒总deadline都释放连接锁；独立heartbeat随后完成，租约不被无限等待耗尽 |
| 租约到期 | 显式短租约实际到期后读取前拒绝，不把已过期所有权复活；reserve/finish保持同当前性守卫 |
| 公开半装 | 生产main全部5 GET +5 POST，在原生两SQL已安装而bridge缺失时统一503、命令0 |
| 公开完整装配 | bridge安装后真实template200、protocol201；API普通/机制LOGIN在READ ONLY事务调用metadata RPC成功；7类Worker/CPU拒绝 |
| 装配漂移 | 初始负例DDL分别改写旧guard、禁用exposure trigger、误授私有EXECUTE、伪造readiness；生产HTTP全部503，命令0 |

readiness 检查76个契约：58函数、11触发器、6私有表和1schema，包括真实入口的 OID、完整定义摘要、owner、ACL/列权限和触发器启用状态。返回 ready 不授资格。API另钉住 RPC 自身函数体及安全签名，不能只造同名表/函数冒充。信任根是经审部署代码和数据库初始化owner；不声称防御恶意超级用户整体替换数据库与程序。

## 运行收据

精确源码/文档摘要、各运行端口、用例数、失败修正和原始 receipt 路径在 `package-history-exposure-bridge-checks.json`；完整交付文件在 `package-history-freeze-manifest.json`。最终生产 main 挂载回归已完成，以该清单为冻结依据。

最终生产 main 直接入口与全桥接：**13通过，154.61秒**，收据 `/tmp/tender-review-f06/history-pg-hyjmd5st/test-receipt.json`，端口53857，运行前后源码摘要一致。生产挂载后的原生 standalone HTTP/groups：**6通过、11未选，103.97秒**，收据 `/tmp/tender-review-f06/history-pg-gfc94nfr/test-receipt.json`，端口50307。两套集群已停止。最终 ruff/format 7文件、mypy/bandit 4源码文件全部通过。

此前 bridge-only 完整运行：13通过，147.99秒，PG17.11，独立非owner API/verify/train/evaluate/旧research等实际LOGIN；收据 `/tmp/tender-review-f06/history-pg-iep3p88r/test-receipt.json`。首轮新增reader曾发现跨metadata commit后 SET LOCAL search_path失效的真实 UndefinedTable；修正为短寿命专用连接的固定 SESSION search_path，未改变业务权限或降级guard，再通过新增reader与完整回归。Bandit最初提示固定字符串SQL组合，改成 psycopg.sql 的固定组合；未抑制检查。

## 使用与剩余边界

旧研究对象读取目前要求 POSIX独立主线程且无其他活动 ITIMER_REAL；不支持的运行模式在读取前明确拒绝。45秒总deadline和先核验后120秒续租是固定实现限制，不是请求字段；无法在限制内读完完整原件就保存失败，不截断。

原生严格历史核心仍保持四时点、独立证据、准确实际提交、官方标签/量尺、完整来源祖先、purpose隔离与先提交final exposure后读标签的原有语义。此次只扩大共同闭包和实际入口保护，没有生成正式样本资格。F06-08线性校准、正式发布/回退、真实三评feature producer仍须继续实现；mean/median CPU与本桥接不能冒充这些功能。下一批 `package-technical-producer-v2-design.md` 仅为设计，不把尚未实施的软件缺口列成外部材料阻塞。
