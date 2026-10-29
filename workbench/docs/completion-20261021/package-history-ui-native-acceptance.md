# 严格整包历史研究界面：原生 HTTP 与独立角色验收

日期：2026-10-22。代码基线为检查点 15 的 `25954a22225713785106dff775287d913c0fc39c`，叠加本阶段本地候选。本文记录本阶段原生验收，不代表已经提交、发布、合并或部署。

## 结果与范围

最终冻结候选在新的 PostgreSQL 17.11 集群上完成 **5 passed、0 failed、0 errors、0 skipped**，用时 **53.293 秒**。执行前后 888 项 Python/依赖文件指纹和 42 项有序 SQL 指纹均相同；独立 PG 服务已经停止，其数据目录和临时口令文件已经删除。原始回执见 [第三轮回执](evidence/package-history-ui/native/run-03-receipt.json)，实际 pytest 输出见 [第三轮日志](evidence/package-history-ui/native/run-03-pytest.log)。

本次使用生产 `apps.api.main` 的实际路由及强制公开安装守卫，通过 FastAPI `TestClient` 执行 HTTP 请求；没有替换为绕过守卫的 standalone 历史研究 router。实际安装完整 exposure bridge 与只读目录 SQL，验证准入、协议、冻结历史组、训练和评估任务、任务控制、目录分页、原请求恢复以及来源后来失效的行为。训练与评估通过各自独立非 owner 凭据的真实 CPU 子进程执行。

业务原文、解析结果、官方结果、历史时点声明、页面覆盖和签名证明发行方均为**显式合成测试资料**。CPU 方法为既有无特征基线；外部模型调用与付费调用均为 0。原文字节读取使用显式内存适配器。本次不构成真实业务效果、真实官方评分、正式样本/投递资格、S3 原文运输、PDF 渲染、Kafka 运输或自动派发验收。浏览器对这些原生响应的重放由另一本阶段验收记录单独报告。

## 可重复运行入口

新启动器为 `deploy/package_history_ui_acceptance.py`，固定执行 `tests/test_package_history_ui_pg.py`，不接收任意测试选择或业务 DSN。工作目录为仓库的 `workbench`。本次三个实际命令如下：

```bash
.venv/bin/python -m deploy.package_history_ui_acceptance --pg-bin /tmp/tender-ui-runtime/pg17/bin --receipt /tmp/tender-ui-runtime/acceptance-first/receipt.json --fixture-dir /tmp/tender-ui-runtime/acceptance-first/fixtures
.venv/bin/python -m deploy.package_history_ui_acceptance --pg-bin /tmp/tender-ui-runtime/pg17/bin --receipt /tmp/tender-ui-runtime/acceptance-second/receipt.json --fixture-dir /tmp/tender-ui-runtime/acceptance-second/fixtures
.venv/bin/python -m deploy.package_history_ui_acceptance --pg-bin /tmp/tender-ui-runtime/pg17/bin --receipt /tmp/tender-ui-runtime/acceptance-third/receipt.json --fixture-dir /tmp/tender-ui-runtime/acceptance-third/fixtures
```

复跑时必须更换为**尚不存在的绝对回执路径及 fixture 目录**；启动器拒绝覆盖既有证据。必须提供明确的 PG17 `postgres/initdb/pg_ctl` 路径。它创建全新临时集群，随机选择 loopback 端口，使用新生成的临时 SCRAM 口令，不读取现有业务 profile。以 root 运行时，PG 进程降为 `nobody` 用户。正常结束或测试失败后，启动器停止自己创建的 PG、删除数据库目录及口令，保留无业务凭据的 pytest 日志和回执。

启动器传给固定 pytest 子进程的选项为：

```text
<当前 .venv Python> -m pytest -q --tb=short -p no:cacheprovider --junitxml=<本轮临时目录>/pytest.xml tests/test_package_history_ui_pg.py
```

环境从允许列表重新建立，仅保留 `PATH/LANG/LC_ALL`，显式设置本轮生成的 `FUSION_REQUIREMENTS_ADMIN_DSN`、`FUSION_PACKAGE_HISTORY_UI_PG=1`、输出目录、禁用字节码写入及不载入业务 profile 的设置。回执和 fixtures 不保存 DSN、口令、会话 cookie、CSRF 值或私钥。没有设置原生开关的普通 pytest 收集会跳过这组集成测试；此前 4 skipped 的收集检查不计为通过。本次有效结果来自启动器的 **0 skip** 运行。

## SQL 装配与角色边界

每个测试由 owner 在新临时数据库装配 `deploy.schema_plan.BASE_SQL` 的 37 项 SQL，随后依次装配以下五项可选扩展；完整路径顺序和每项 SHA256 均保留在回执的 `ordered_sql` 中：

1. `deploy/sql/model-governance.sql`
2. `deploy/sql/package-historical-admission.sql`
3. `deploy/sql/package-historical-research.sql`
4. `deploy/sql/package-history-exposure-bridge.sql`
5. `deploy/sql/package-history-directory.sql`

其中未装配状态测试先观察 bridge/目录缺失，再安装它们观察真正空目录，避免将“未配置”误报为“已检查、无记录”。启动器同时断言上述五项仍不在 `BASE_SQL` 内。本阶段未将 B1—B4 或历史研究扩展加入默认 BASE、Fusion v14 或默认恢复清单，也未装配旧 WIP 的 retrospective SQL。

| 用途        | 实际 LOGIN / 角色组                                                                     | 本次约束                                                                             |
| ----------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| 测试 API    | `fusion_package_requirements_service`；`tender_api` + `tender_package_history_test_api` | 仅明确登记的可丢弃机制数据库允许保存 synthetic 准入；业务动作经实际 HTTP 与公开守卫  |
| 普通 API    | `fusion_package_history_ordinary_api`；`tender_api`                                     | 对同一 synthetic 证明的新准入返回 403 `PACKAGE_HISTORY_SYNTHETIC_ENVIRONMENT_DENIED` |
| 常规 Worker | `fusion_package_requirements_worker`；`tender_worker`                                   | 独立身份，不能调用历史研究协议目录函数                                               |
| 证明验证    | `fusion_package_history_verifier`；`tender_package_history_verify`                      | 独立子进程验证本轮 synthetic 签名证明                                                |
| 训练        | `fusion_package_history_trainer`；`tender_package_history_train`                        | 按明确 job/generation 的 CPU 子进程执行，不使用 API 凭据                             |
| 评估        | `fusion_package_history_evaluator`；`tender_package_history_evaluate`                   | 独立于训练与 API 的 CPU 子进程，明确启动 final 评估                                  |

完整 bridge fixture 还建立独立旧版 train/evaluate/research 登录及相应权限组，以满足生产 guard 的跨命名空间安装前提。API、Worker、验证、训练、评估角色均断言 `NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/NOBYPASSRLS`；角色口令仅在临时内存/子进程环境中使用。owner 只承担安装、显式合成上游资料构造、来源撤回模拟和验收只读断言，不承担待验业务命令。

实际 admission context 即使已经有有效 synthetic proof，仍保留 `PACKAGE_HISTORY_EXTERNAL_PROOF_ADAPTER_NOT_CONFIGURED`。原始响应如实记录这一“真实证明适配器未配置”状态；本次仅证明已显式登记的 test API 可以保存 synthetic mechanism candidate，普通 API 仍拒绝。不能据此宣称真实历史来源已配置、正式资格已授予，或开放任意证明上传/合成来源开关。

## 五项最终原生场景

| 测试                                                                             | 实际验证                                                                                                                                                                                                                                                                                                               |
| -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_missing_public_installation_and_unknown_directory_are_not_empty`           | 实际主路由在缺 bridge 时 503；目录缺安装时 `status=unavailable`、数量/观察摘要为空；安装后为空的目录才返回 observed/0；读取不新增 command、audit、exposure、admission、protocol、cohort 或 job                                                                                                                         |
| `test_actual_public_ui_flow_exact_ack_directories_and_isolated_cpu`              | 同次固定范围、实交和官方结果目录；真实证明验证、准入 POST/GET；协议冻结；fit/development/final 精确选择、全关联组闭包与标签截止；train queued→pause→原 pause ACK 恢复→新键旧条件 412→resume→独立 CPU succeeded；明确 evaluate→独立 CPU report；四种目录与稳定分页；来源撤回后 current=false，原准入 ACK 和报告保持不变 |
| `test_protocol_original_ack_survives_current_method_change_but_new_key_refuses`  | 模拟当前 CPU 方法版本变化后，原 body/key 返回原 status/body/ETag 及 `Idempotency-Replayed=true`；新键仍 409 `PACKAGE_HISTORY_METHOD_CHANGED`；不增加持久记录                                                                                                                                                           |
| `test_actual_directory_cursor_refuses_changed_observation_and_wrong_scope`       | 真实 HTTP 创建协议形成分页；同观察页不重叠；新增协议后旧游标返回 409 `PACKAGE_HISTORY_DIRECTORY_OBSERVATION_CHANGED`；把协议游标用于历史组返回 422；新第一页更新摘要，读取本身不写业务记录                                                                                                                             |
| `test_normal_api_cannot_admit_synthetic_and_purpose_roles_cannot_read_directory` | 相同证明在测试 API 接受、普通 API 拒绝；独立角色无 owner 等权限；非 API 用途不能读取协议目录；拒绝动作不写业务记录                                                                                                                                                                                                     |

主流程保留真实官方零分值 `"0"`，没有把未知标签转成零。最终报告分母为 3：成功 1、拒绝 1、无标签 1、失败 0；区间覆盖率和不足独立组的 bootstrap 区间为 `null`。关联组跨 submission split 的样本实际排除，超过标签截止的成员保持原排除理由。这里的数值仅验证机制口径，不是模型质量结论。

历史恢复仍先经过当前会话、公开安装守卫及必要读取依赖检查。本次覆盖“来源证明后来失效，但原始依赖仍在且调用者仍有权限”的恢复；不能推广为任意撤权或依赖删除后都能读取。

## 原始 HTTP fixtures

只保存请求的业务正文、路径、查询、原 `If-Match`/`Idempotency-Key`，响应的 status、ETag、白名单公开头和原 JSON body。记录格式为 `responses:[{name,method,path,query,request_body,request_headers,status,etag,headers,body}]`。未重新计算、改写或拼接 HTTP body 中的 ID、digest、时间戳、ETag 或 `current` 字段。

最终同次第三轮 fixture 与仓库文件如下。主文件从采集原名 `package-history-ui-http.json` 改名保存为 `package-history-ui-complete-http.json`，**字节未变**；回执仍以采集原名登记。

| 仓库内文件（均位于 `apps/web/src/test-fixtures/`） |   字节 | SHA256                                                             |
| -------------------------------------------------- | -----: | ------------------------------------------------------------------ |
| `package-history-ui-complete-http.json`            | 309735 | `66bf161e65cdb09cc72e4b4a1e4803ecacc57830e32dfcd123beb34519e9679a` |
| `package-history-ui-directory-change-http.json`    |  22489 | `e2d7425f8eca919e9136fc1840d0dd0b3bc9980f87ca22798a96895900d068e6` |
| `package-history-ui-unavailable-http.json`         |   7815 | `21e039e5fdec975e5b3d03713e739e8c27aea0cd19c76f1a525f23d29342ed74` |
| `package-history-ui-method-recovery-http.json`     |   8809 | `0d282dd471a65a67f52651c757e6c6e641dadbb2338326b69bd0f973f323d1aa` |
| `package-history-ui-role-boundaries-http.json`     | 129127 | `75e4faf6aa8a2e0b35b130fd0c81a5cd89f9c93b8565eaf903f43edba0583ef7` |

主文件有 58 条响应，包含同一准入对象的 `saved_scope`、`scope_submissions`、`scope_outcomes`、`admission_context`、`admission_created` 和真实 `admission_current`；其他六条资料各自也有真实 `*_current` GET，不从 ACK 人工包装 `current=true`。协议、历史组、任务、控制 ACK、训练/评估报告与四类目录来自同次数据库。独立反例文件来自各自的新测试数据库，不能把其对象 ID 与主流程混接。

## 三轮执行与修正轨迹

| 轮次 | UTC 时间          | 实际结果                                              | 判定/修正                                                                                                                                                      |
| ---- | ----------------- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | 01:13:30—01:13:45 | 2 passed / 2 failed / 0 errors / 0 skipped，12.448 秒 | 新测试错误地按顶层读取 CLI 的 `paid_calls`；实际既有 CLI 输出是 `{ok,result}`。原始失败 `KeyError: 'paid_calls'` 保留，随后只修测试为 `receipt["result"][...]` |
| 2    | 01:14:28—01:15:26 | 4 passed / 0 failed / 0 errors / 0 skipped，55.488 秒 | 修正后重跑完整当时专项，指纹稳定；作为中间原生样本，未冒充最终五项候选                                                                                         |
| 3    | 01:18:30—01:19:26 | 5 passed / 0 failed / 0 errors / 0 skipped，53.293 秒 | 补齐各准入 GET 与目录变更反例后重新冻结、完整重跑，最终验收证据                                                                                                |

三轮回执和 pytest 原始日志按原字节保存在 [native 证据清单](evidence/package-history-ui/native/archive-manifest.json)，不能把各轮通过数累加。初次失败没有通过删测、增加 skip 或篡改输出消除。每轮均记录服务清理完成。

原始日志还保留依赖库的 `DeprecationWarning`；前两轮出现既有 `oss2` 的字符串 escape `SyntaxWarning`。这些不改变测试结果，也没有用过滤器改写日志。

## 源码与 SQL 指纹

启动器记录 `apps/api`、`apps/worker`、`packages`、`deploy`、`tests` 下所有 Python 文件及 `requirements.lock.txt`、`requirements-package-history.txt`，共 888 项。执行前后逐项比较，不只依赖分支 HEAD。完整逐文件值在第三轮回执的 `source_before` 中。JSON 的键排序、紧凑分隔符序列化后，该集合的 SHA256 为：

```text
19f7cec8a384a2c06511947c222d40b34c44577995c08b894df62b430b2ed519
```

本轮原生候选关键文件：

| 文件                                      | SHA256                                                             |
| ----------------------------------------- | ------------------------------------------------------------------ |
| `apps/api/package_historical_research.py` | `ad0e146da6b5e6555ca266672d7923f91886e0fa85261ac0771a5d0d107897bf` |
| `deploy/package_history_ui_acceptance.py` | `957379e6e7d238b19fbeaaf58bb66b3f392c9320e4ecaa3776403b6073ce3ee2` |
| `tests/test_package_history_ui_pg.py`     | `6cd5b1ee1bc4a00f8df803fa80a391c730b3e26ecc36c9137635877e45696ffb` |

42 项有序 SQL 列表同样按键排序、紧凑 JSON 序列化后的 SHA256 为 `08b0e4c235fce36a3fbff1863db65136576ed0a3b6cf89ec70411a17fc221ef8`。前后 `source_unchanged_during_execution` 与 `sql_unchanged_during_execution` 均为 true。第三轮原始回执本身的 SHA256 为 `c672830faf6c1862defe63fde3aae106da3cdfece9011bfa9a3ac6717ebeb4d9`。

该集合有意不含前端代码：同一阶段的前端并行开发不是本原生运行的输入，不能用原生通过替代前端组件、类型、构建或浏览器验收。归档/说明文档也不在执行源码集合内。后续若修改已登记后端/原生测试/SQL，必须按影响重新冻结和验证。

本阶段后端产品差异仅为 `create_protocol` 把当前 CPU 方法构造及摘要校验放到 `Command` 原回执恢复之后。原请求重放无需运行新的方法，新的 body/key 仍检查当前方法。鉴权、安装依赖和原请求绑定保留。本阶段没有改 HTTP schema；实际 OpenAPI 导出入口仍为 `apps.api.export_openapi`，与前端契约的集成验证由阶段总记录报告，不以计划规范 `packages/contracts/openapi/openapi.json` 代替实际应用输出。

## 静态检查

本轮原生新增文件实际执行：

```bash
.venv/bin/python -m ruff format deploy/package_history_ui_acceptance.py tests/test_package_history_ui_pg.py
.venv/bin/python -m ruff check deploy/package_history_ui_acceptance.py tests/test_package_history_ui_pg.py
.venv/bin/python -m mypy deploy/package_history_ui_acceptance.py
.venv/bin/python -m bandit -q deploy/package_history_ui_acceptance.py
```

Ruff 检查通过，格式已应用，mypy 为 `Success: no issues found in 1 source file`，Bandit 退出 0。Bandit 输出保留一条已有 `# nosec B603` 没有对应失败检查的提示，不等同于安全缺陷命中。未把本阶段专项结果替代检查点 15 历史全套成绩，也未重跑无关完整套件。

## 环境恢复与已知缺口

新副本从旧干净工作副本复制 Python 虚拟环境和前端依赖；实际工具始终通过新副本 `.venv/bin/python -m ...` 运行，避免复用旧 shebang 写入旧目录。没有修改旧副本或旧数据库。Python 为 3.12.14。

PG17.11 从 PostgreSQL 官方源包恢复，核验官方 SHA256；pgvector 0.8.2 固定至官方 tag 对应 commit `cab9da72c04353f143bb06b42ab70a403daac64a`，登记实际源码 SHA256；编译产物仅用于本地验证。详见 [PostgreSQL/pgvector 来源](evidence/package-history-ui/native/runtime-postgresql-source.json)。本轮 postgres 二进制 SHA256 为 `21f336a1b90edecbb3bad0924521a3f56d51fe4fe59db49fbf3760f335c8bb30`。

初次构建发现系统缺 bison/flex/m4，后从 Ubuntu Noble 官方包索引下载并核验对应包 SHA256，只解压到 `/tmp/tender-ui-runtime/builddeps`，没有安装/覆盖系统包；详见 [构建依赖来源](evidence/package-history-ui/native/runtime-builddeps-source.json)。系统已有 libuuid 运行库但缺头文件，恢复了匹配 util-linux 2.39.3 固定 commit 的官方 `uuid.h`；详见 [UUID 头文件来源](evidence/package-history-ui/native/runtime-uuid-header-source.json)。曾尝试的其他未通过校验的下载没有作为本轮构建输入使用。

浏览器资源为匹配当前 Playwright 锁定版本的 Chrome for Testing 151.0.7922.34，下载自官方发布路径，核对长度及官方 ETag 的 MD5 并登记 SHA256，`ldd` 未发现缺失库。路径为 `/tmp/tender-ui-runtime/chrome-linux64/chrome`，来源见 [浏览器来源](evidence/package-history-ui/native/runtime-browser-source.json)。浏览器可执行文件的恢复不等于已完成浏览器验收。

OCR 数据按现有 `packages/parsing/assets.json` 的锁定修订恢复并验证：

| 资源      |    字节 | SHA256                                                             |
| --------- | ------: | ------------------------------------------------------------------ |
| `chi_sim` | 2469156 | `a5fcb6f0db1e1d6d8522f39db4e848f05984669172e584e8d76b6b3141e1f730` |
| `eng`     | 4113088 | `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2` |

本环境仍缺系统 Noto 中文测试字体；本阶段历史研究测试不执行 OCR，不能据此补报 OCR 通过。若重跑完整 OCR 范围，必须先恢复实际字体条件。Docker 受控转换、S3/Kafka、生产容量及长期恢复均未在此新增证据；PDF 的既有限制继续成立。

## 交付与清理状态

新增可复跑启动器、五项原生测试、最终同次原始 fixtures，以及本文和归档证据。公开依赖来源和三轮原始日志均包含在仓库内，临时数据库及认证材料不进入 Git。归档目录原字节清单可用 `archive-manifest.json` 逐项重算验证。

这批工作为本地候选，没有提交/推送、合并或部署；也没有触发付费模型。原分支和原 PR 的后续发布状态应以阶段总交付记录及实际远端为准。
