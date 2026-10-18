# 预算 helper05 / 非 owner 原生硬 Mock 验证

2026-10-18，最终候选 `tests/test_assistant_budget_nonowner.py` 在独立 Linux **Python 3.12.15 / PG17.11 + pgvector** 上 **5 passed in 16.71s**。没有生产代码修改、owner 补权、真实供应商请求或费用。

## 环境与初始化

- 检查镜像：`sha256:f21edf5853b0c337de05a4b6af7ee16787b5520d8e4101b34fea6ee2a70b25be`，62 个锁定依赖已由独立代理离线检查；本测试使用实际安装结果。
- 临时 PG 镜像：`sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d`。新容器 `tender-fusion-nonowner-pg`，内存上限 1 GiB，数据库仅 tmpfs，无宿主端口。
- 网络 `tender-fusion-nonowner-qa` 使用 Docker `--internal`，只包含检查容器与临时 PG；数据库别名 `fusion-nonowner-postgres`。没有 Docker socket、业务 env、业务服务或外网出口。
- 只读挂载允许的源码目录（packages、deploy、tests、apps/api、apps/worker），复制至容器私有 tmpfs。umask 077，`.local` 0700，profile 0600；直接执行真实 fresh helper，不跳过 POSIX 权限要求。
- 在此全新 cluster 一次创建五个基础 NOLOGIN 能力组及预算管理组。测试前后检查组能力不变，不复用其他 fixture 的全局 LOGIN。helper 创建随机 nonce 的全新库及五个随机 LOGIN，逐个实际登录验证。

实际 SQL 顺序为 BASE_SQL 的十项，再依次 `assistant.sql` → `live-facts.sql` → `intent-budget.sql`。每一项由 helper 在任何数据库变更前冻结实际字节与 SHA。没有 rag/structure/评分/模型治理扩展，也没有资格替身。

| SQL | SHA256（实际 LF 字节） |
| --- | --- |
| contracts/core.sql | `27f249ff5110c914404846d2e14f6d4fd8b85ae51e9f6a3b9caa7c1b9595e5cd` |
| contracts/domain.sql | `b279c9b1c3477feeb28eaa5f6a45adb4493585a1d112d7d7a637cefac1404d96` |
| contracts/bid-packages.sql | `f18cbd9a22cdcb3f1d3229d0e43b3ad4b0ff3568f4b160787e0c4572b6f9c319` |
| identity/stable-lot-identity.sql | `3d4775a72daa3fd1c813aab72212e9aefdf5e5ef5aa22eb0c83db2cd580b3738` |
| contracts/retrieval.sql | `afdfb3d81bc049cedaa45777af3c8aa622b8c3eb465cd6b35e3a37c992991876` |
| contracts/worker-functions.sql | `8f18a20578c010144ed851d0e96753894c86a4147deff95c49aa19ec5faaea4b` |
| contracts/roles.sql | `b1b77fc0d65a95da41b8071475c28d8918f958e3cc479b65ce099e0563fb7ec1` |
| deploy/bid-package-runtime-grants.sql | `1667815c514a455b29230753202876c125ce10e34a0c408b4d50f49f118bd14e` |
| deploy/vector-runtime-grants.sql | `c66ce4615b007706ad690166233aad58053ff38b53eab5f7549583fc7c400619` |
| deploy/research-source-qualification.sql | `0b04ba8dd0ae471d06c45b4c6d36b8570211d248fd60410e15362a2b373ba027` |
| assistant/assistant.sql | `4030b5e6a749aa060956c4039aa0cdd34e057508ea6a4ce9c58100f5a6ca81b0` |
| assistant/live-facts.sql | `42fc9646225a67a8d209822ac9d0e3573e6903b3f5681042e9cb49fa6eeb11a2` |
| assistant/intent-budget.sql | `173078b95a5cd58db9f8f8aa09ff2728bae2c4a1e1b3817a4b593e719b04a6b0` |

相对路径中 contracts、identity、assistant 均位于 `packages/<目录>/sql/`，deploy 位于 `deploy/sql/`。这些指纹对应 [SQL 字节记录](fusion-sql-input-bytes.json) 的 Git/LF 候选；先前 Windows 原始 CRLF 的 199 项验证收据仍保留原指纹，不改写为同一输入。

## 五项实际验收

1. **helper / 权限**：五个非 owner LOGIN 实际连接验证通过；API/Worker 业务子进程各仅收到一个 DSN，既没有 owner，也没有预算管理 DSN。两者不能写价格或限额，也不能直接调用两个内部 live helper。预算管理由独立正向 allowlist 子进程执行真实 CLI，使用单独 0600 profile，写入留存 SHA 的显式合成价格及三 scope 限额。
2. **项目链**：API 身份创建身份/原件记录，Worker 身份创建合成解析页/证据并发布真实 source graph，API 使用原生 fact_sets 确认五事实和 human basis/carryover。真实 ASGI 受理 → 普通 Worker 已注册的 `assistant/1` 原生 acquire/compute/finish → API coordinator 发布 → 历史两条消息。native call 与 dispatch 各一条，冻结 usage 12+20 按合成价格实际结算 32 minor；同任务重放零新增模型请求。
3. **全局链**：真实全局会话 API → global_runtime.handle → API coordinator 发布和历史读回；同样一次 native call/dispatch、结算 32 minor、重复执行与 HTTP 幂等重放不增调用。该例为 general target；项目目标的五事实资格由上一例及 25 项完整来源测试覆盖。
4. **撤回**：项目受理后，用真实 Worker 撤回原件祖先；原生执行没有 native call 或 dispatch，也没有 Mock HTTP。初始 held 2099200 保留，实际非 owner `coordinator.tick([job])` → terminal_tick → settle 将已终态且未发送任务释放为 0；仍无 dispatch/native call。
5. **未知**：全局调用显式 Mock ReadTimeout 一次，状态 unknown，原 held 2099200 保留。重复 Worker 执行零新增请求；实际 API coordinator.tick 后仍 unknown/原额；相同 HTTP 请求复用原 job。

模型端口只替换 `DeepSeekClient.from_env` 为明确构造的客户端，其实际 generate/解析/usage 入账走 `httpx.MockTransport`；API 的传输器遇 HTTP 立即失败。未替换 budget/target/live helper、Worker handler registry、compute、finish、coordinator 或 SQL。对象存储是显式进程内字节适配器；测试原件页/解析数据为合成机制输入，没有宣称实际 PDF 解析质量。

## 证据、清理与复跑

本地原始 XML 和无凭据 JSONL：`.local/nonowner-evidence/nonowner.xml`、`nonowner-receipt.jsonl`；源 allowlist SHA 清单 `.local/nonowner-source-sha.json`。记录包含 SQL 输入、真实调用/事件/账本计数及清理结果，不包含 DSN、口令或业务原文。helper 临时库、五个 LOGIN、所有私有 profile 均在 finally 清理；独立查询确认 nonce 库与 LOGIN 均为 0，能力组不变。

可在同隔离条件下设置 `FUSION_NONOWNER_OWNER_DSN`（专用内部 PG17 的 postgres 库、显式合成 URI）运行 `python -X utf8 -m pytest tests/test_assistant_budget_nonowner.py -q -x -p no:cacheprovider`；可选 `FUSION_NONOWNER_RECEIPT` 保存安全 JSONL。测试刻意要求 Python3.12/POSIX 和固定专用 PG 别名/端口，拒绝业务端点，不能把环境变量指向已有业务库。

ruff/format、mypy（Linux 目标）通过。Bandit 对本测试除 assert 与固定 argv subprocess 的预期 B101/B404/B603 外无发现；没有生产代码新增需扫描。Windows 直接 mypy 还会涉及原有 `authoring.build` 的 POSIX killpg/SIGKILL 属性，正式检查使用 `--platform linux`。

这关闭受限角色完整 fresh/原生助手预算机制这一边界。真实 Kafka broker/消费者传输、对象存储服务、供应商质量/费用、生产部署及浏览器视觉仍未验；不能由本结果授真实模型费用资格。
