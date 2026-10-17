# 独立测试交接（2026-10-17，已静止）

用户已将当前优先级改为GitHub完整交接。测试角色停止新恢复attempt、Docker、云请求、模型、消费者和测试执行。当前没有测试角色仍运行的恢复进程或容器；首次实际恢复的唯一测试容器已精确清理，卷和失败证据保留。以下为交接状态，不是新的放行。

路径约定：`tender-docs/...` 指本仓库同级的 `/workspace/tender-docs/...`；不是仓库内 `docs/` 的别名。证据必须按原始字节归档，不能只保本文件或拿当前moving源码重跑冒旧候选。

## 现在最重要的未完成项

1. OPS05完整云恢复尚未独立通过。只读、纯包装器与冷启动通过；首次实际目标因QA编排nonce错误安全拒绝；第二次在创建进程之前被自动审批拒绝。两次原证据均保留。
2. 用户随后明确授权了“一次限定测试”：仅7个自建合成对象、总322字节，最多7PUT+7GET，固定测试前缀。**该授权尚未消费，未发生云请求。** 最后用户要求转GitHub交接，故当前授权不等于可以立即启动；先完成交接，后续由PM重新排资源与执行。
3. 当前完整路线driver03不满足这个精确授权：原restore内部已有7PUT+7GET，driver随后又GET7次；其动态目标前缀也与获准前缀不同。**禁止执行当前driver03的execute命令。** 新的限次/固定前缀修正仍停在设计，尚未写helper、未冻结新driver/prepared、未交架构审核。不要把“准备修”写成“已修”。
4. DB-only安全替代已有独立协议、两个脚本和prepare receipt；仅语法读取与离线prepare，不曾执行、不曾获架构具体审核。用户云授权后PM选择优先修完整路线，因此DB-only保留而未执行。
5. 当前资源曾被PM临时停放以提供恢复窗口：两套旧本地Seaweed模拟存储，以及全新19098 host-native Kafka。所有卷/数据/配置/恢复材料由PM保留。当前测试停止后，PM应决定按其恢复协议重新启动；测试角色不得自行恢复、删卷或清桶。

## OPS05已冻结身份

主证据目录：`tender-docs/04-验证与测试/application-recovery-independent-checks/code-05-single-target-plan/`。

| 输入/记录 | 完整SHA-256 |
|---|---|
| 开发code05 candidate | `6436b14fbd0bd9278f6ae70bea10b1ee4d7e7e2faebda140dd77421d8def052a` |
| 开发完整串行result（不是独立通过） | `9176380c0083fc479354a819b9221db370783392c8ccb9ee898282ce2d59c3ab` |
| 开发49项私有证据索引 | `5533e3df11748a2e6ce74b67e37b9257184ca93d368b5eba6291e8f6b14d206d` |
| 固定07应用308文件runtime manifest | `71fe0fb2c9dbde7d85e62d20bef2da8e188e59ac00e9eb056cc021a1bd75274e` |
| 原15SQL协议baseline-inputs | `76dc6abed9ae344dbf755a3c0d237e68f3a420b042fac6193debe2e16116f38f` |
| 源archive manifest | `ccacb97792be19b157748580a71b0c8e4f891e249556aa3d8dcad1511598358b` |
| 源database.dump，852503字节 | `6d568c5730a85cbf1dbf25406fd9fb1070cfc28b48c5b70acde5d87cb7ee3146` |
| 独立readonly-result.json | `d17e17578336b798265ae0c091cf4a9a44adf4e8685974a7776831dba2cc5949` |
| 15项纯暂停边界paused-boundary-result.json | `0842e38be17e69196771fb24f173c0397933daf2240531db58f68e72b15ea25f` |
| 离线prepared-cold-load.json | `d634c97f49bebf238a7b2a3f1725c1b01b7edebd01091936686c9be24068bba3` |
| 首次实际失败actual-40e8c1ed7230406293111e2c85006b98.json | `7207c783f1b8e2d10cf418b57f70c85a1235ee7228bac28d70816229f76f5f2f` |
| attempt01-failure-classification.json | `0eb37dfa03a5b8010c73aba8b8408b42a49dac0156fbbc7afd3c7beb1c13c100` |
| attempt02-approval-rejected.json | `759cd54f34fd4265aa928bf362de9f8c9b0c4ef4f59f4e14718e0a861d2689c6` |
| 最新单目标协议03（当前单目标独立恢复协议.md） | `db7abef9a5b6ee4ead27a6506953696c557af47ea52bf2b84b5c15f597d96e7c` |
| nonce marker-binding-offline-result.json | `c250b2c3088e81d506fd7d602bc2f23e584d3cf23a6399a48540b6fc4cb5381f` |
| 精确云确认材料cloud-scope-for-user-confirmation.json | `8a54340e8c2321cba4ddfc8c2189526c3d5c0811c220b8655403a76cff2706ea` |

固定07的实际OpenAPI原文件SHA `3249fec969b04a3bc298bfd77a2f0dda7d1a4f3a1f1213a1a8d6648db6998fe7`，161路径/188操作/310schemas。独立冷加载的语义canonical摘要与该原文件一致（排序/缩进序列化SHA为 `d3a0f761b2a6f7677f0efd97d382899e411030803d8853278645b5be6b326627`）。不得因序列化方式不同把它误判为接口变化，也不能据此声称实际接口执行通过。

原完整场景1600 MiB初门和原create内部900 MiB保持不变。独立单目标场景是不可变源档案→一个新目标，另设**1536 MiB初门/256 MiB阶段余量**；不启动源容器、不挂原源卷，最多同时一个新PG容器。固定PG镜像只用缓存，不pull/build。预估1024 MiB VFS、192 MiB卷/WAL、32 MiB证据、288 MiB余量；不是生产容量保证。

## 首次实际失败的准确定性

实际起始free `1670701056` 字节，创建后 `711200768`，清理后 `1596825600`。真实pg_restore TOC已得到164 TABLE DATA；TOC SHA `ec876f7fccdb0f713d6ae60bf67a32f468b7e88e0be9f28bdd0dffcfd0c76604`。

错误 `DATABASE_RECOVERY_IDENTITY_MISMATCH` 出现在恢复后的首次受限reader身份检查，尚未进入对象端口。原因是**QA把新的execution UUID当作恢复数据标记**。原dump的recovery_control.identity保持源标记；生产guard正确拒绝，不是产品数据丢失，不应修dump、改目标表或跳guard。

修正03分开两种身份：新resource/DB/LOGIN/卷/systemID继续随机；cluster.nonce绑定原plan SHA `62a347bdd144c80f1e8ebcbb4c81fb579b70068598aebb4120e4dc8317bc82da` 的源标记。该标记在建容器前按真实row_to_json与8字节big-endian长度前缀算法重算，必须等于封存唯一identity行SHA `348bacba4fc40399c20fd19e723a64b8dd24348613194f189f996cf035c34e04`。正确绑定与错误UUID、0行、错误摘要、重复marker表5项离线检查通过；架构还独立提取helper复验5项。生产源未改。

首次容器全ID `a4c4e77945d11b53c75e3267ee556c2eb4bd23afb26aeca7b7d0d50bbf26fb4f` 已stop/rm；保留卷 `twb-ar-data-8424a94ed45745299d4abbcc58aded3c`。不在该旧目标修补或重试。原403输入和当次prepared25输入在失败后再次核SHA未变。

## 自动审批拒绝、随后授权及未完成修正

第二次执行在CreateProcess前被自动审批拒绝，故没有新容器、PG连接、云请求或execution intent。理由为一般桶使用授权不足以覆盖特定恢复载荷的敏感外发。明确的“不通过变相/间接执行绕过”已遵守；拒绝原文在脱敏记录中保留。

PM随后向用户展示限定范围，用户明确回复“授权这一次限定测试”。范围文件8a5434…已把本地7对象逐字与冻结fixture.create的7个bytes literals比对，确证全部为自建合成载荷，不是仅凭命名推断；不含用户原件。限定：

- bucket为用户指定tender-base杭州；只用固定前缀 `workbench-checks/7f9f160a-9154-48fd-8ac8-f33e9ce5337c/recovery-qa/`。
- 仅7对象、322字节，最多7PUT+7GET；只传该7载荷，不传dump/manifest/成员/会话/凭据等其他档案。
- 条件写入防覆盖，冲突或unknown即停；无隐式补发/换目标，无LIST、DELETE、全局桶设置或模型调用。

该授权未消费。主会话最后要求交接并停止所有新工作，优先于此前执行窗口。接手者必须先修复并审核以下小片，不能直接调用当前完整driver：

1. 前缀固定为上面的获准值，移除driver额外7GET。原archive.restore自身在DB核验后已做7PUT+7GET。
2. 在实际SDK SafeSession.do_request处设7个精确对象的PUT→GET计数硬门；SafeSession原本max_retries=0、无重定向。原OssClient在409时可能fallback GET，须让该失败先停止，避免随后多GET或误将冲突视为授权内重放。
3. 同一次7GET保留真实大小/SHA断言，可在原read_object返回处做独立观察核对，不再发第二次GET。任何unknown消耗本次窗口，不自动重试。
4. 新协议/限次helper/driver/prepared全部重新SHA，保留原03与失败，交架构最小diff审查。仅静审通过、PM重新资源窗口、1536/256门及用户授权范围仍一致才可执行一次。
5. 完成后独立核164表逐表SHA、完整catalog/ACL/965 CHECK精确例外、非owner权限、暂停ASGI真实登录/CSRF/幂等/恰好一个新bid、旧队列与unknown费用不变；精确清本次容器保卷，立即归还窗口。云失败必须保实情，不用DB-only或开发结论替代。

## 现存WIP与精确状态

| 文件（仓库内qa/） | SHA-256 | 状态 |
|---|---|---|
| run_recovery05_single_target.py | `bfaf841ae77cc01313dc95cfcff2ed007205c690d41860981b577cbecef22665` | 完整driver03；nonce已修，额外GET/前缀尚未修，禁止execute |
| run_recovery05_db_only.py | `f03fdd4e28b9bb7427f016ecdeaa25ed3641d1e2f69dd3d1f72d107c78935a16` | 新DB-only编排，prepare完成，未架构审/未执行 |
| recovery05_db_only_child.py | `5150900dc18a8e65b1117d60296a74478d615638dc39540c5f85bd9b7a742752` | 显式API环境、外部HTTP/socket硬拒、真实本地ASGI；未执行 |
| inspect_application_recovery05.py | `b19d043798f982c91737c1117ed53c4b0ffcd18ca4e215642c770d99e1e1d0b8` | 已执行只读检查，结果禁止覆盖 |
| check_recovery05_paused_boundary.py | `1e28d4eb3fee6839483eb8d34eaefbd00483a8b725e18b2b565688c6f6adf5fc` | 15项合成下游包装器检查通过，不是实际API通过 |
| check_recovery05_prepared.py | `a0a3bfd8348cc8b9054dea6bfb4744b039fac913b673744f0fc4adbc02735295` | 本地档案validate及308应用冷加载，无网络，通过 |

DB-only协议SHA `766bfd56327fd246d22473fb7deac21a52c14f76f96288e79b7a54714c0bbb9c`；单独prepared SHA `0c341fca67f90577e09b781df58ffc848eeb1127e55fbb74b8cf31f20548ccc2`。它不读云配置、不调用含云分支；DB部分显式原pg_restore/reassign/accounts/finish_ddl，云状态永远blocked，不可标完整恢复通过。该路线目前只是备用WIP，不需要继续执行。

`executed-driver-02.py`保留首次实际执行原字节，SHA `bd07a298be3992565c264911e3b70033a5b58e3f64e26276ea324fab7785404c`。不要用后来driver03覆盖解释原执行结果。

## 私有材料（不进Git；只交保存位置）

以下路径可能含口令、DSN、会话或原始档案；即使600也不能提交。不得cat到日志，不复制到公开handoff。完整受控材料需单独安全交接；仅Git克隆不足以重做真实恢复。

- `/workspace/tender-workbench/.local/backups/application/drill04-20261017-c23d8a71/`：开发源/目标archive、dump、7+7本地对象、49私有原始证据；source-initialized.json、target-initialized.json、source-resumed-resource.json、source-objects.json、target-objects.json、member-credential.json等配置。
- `/workspace/tender-workbench/.local/qa-recovery05-1909d6d8fc8440eeaab9316b4203370e/`：最初协议01离线prepare，已废弃，只保留。
- `/workspace/tender-workbench/.local/qa-recovery05-40e8c1ed7230406293111e2c85006b98/`：协议02实际失败的完整执行根、目标配置/登录身份/TOC、intent、私有result；其prepared SHA `6c42fdc8ff830d3fb3a3c5b616d484698c8b579c84ae2723caafaab6b19c7ca4`。原目标配置位于该根 `.local/backups/application/single-target-40e8c1ed7230406293111e2c85006b98/`，不恢复运行。
- `/workspace/tender-workbench/.local/qa-recovery05-ea8eb4ed0a5945ac920e75620ea2717e/`：协议03未执行根；prepared SHA `3ca8de5f3490ac1e204d6a6040003d21ebbd8b95d3d1cfc26bd5739a7a044a84`。因审批拒绝尚无完整路线目标创建。
- DB-only receipt：上述ea8eb根 `.local/backups/application/db-only-abc9d774ce4846348bddcac10dcb57c4/prepared.json`（仅prepare，无目标）。
- `/workspace/tender-workbench/.local/providers.env`，以及该目录下external/QA/各专项数据库purpose文件、成员文件、Word renderer私有profile，均不可提交或输出。需要哪些凭据应由接手者按用途重新配置，不能共用owner做业务测试。
- PM停放Seaweed和19098的完整配置/二进制/数据归档由PM管理；参考其application02-native相关停放证据，不能从本测试交接推断可以删旧容器、卷或cluster数据。

开发原源卷 `twb-ar-data-1ef3578f791e4e948d3a136a7f6057c1`、开发目标卷 `twb-ar-data-24365862de8a4cdca341588bbe103045` 和首次QA失败卷都保留；不要在Git交接时当缓存删除。

## 安全接手命令（离线，只验字节；此处不含执行命令）

在仓库根目录：

```bash
git status --short
sha256sum qa/run_recovery05_single_target.py qa/run_recovery05_db_only.py qa/recovery05_db_only_child.py
python -B - <<'PY'
import ast
from pathlib import Path
for name in ('run_recovery05_single_target.py', 'run_recovery05_db_only.py', 'recovery05_db_only_child.py'):
    ast.parse((Path('qa') / name).read_text())
print('syntax only; no restore or external request')
PY
```

原只读/纯机制脚本输出具有拒绝覆盖保护；不要为了“复现”删除已有结果。若需新跑，先为新运行选择独立输出并冻结脚本SHA。当前不得调用任何`execute`，不得以导入后间接调handler绕过本次交接停止指令。

## 已完成的近几批独立验收（范围以原报告为准）

全部是独立范围结论，不能累计数量授全系统/真实业务/模型资格。更多历史正式结果的路径与SHA见同目录 `testing-evidence-index.json`。

| 已完成片段 | 原final-result位置（tender-docs/04-验证与测试下） | 完整SHA-256 |
|---|---|---|
| TechnicalScale应用01，10项；真实无网Word两条+非ownerPG/ASGI，0模型/云/Kafka，score分母未链接 | technical-scale-independent-checks/candidate-01/final-result.json | `891dbbb5417a5c420957a9bf2bbc81a3b1d7ec6ee0129e77e136989783a3484e` |
| A2 PAGE02，4真实PG/registered engine/no-net Docker；PAGE1..8及正文digits，取消/旧稿/撤回；TOC/章节页范围/rich未完成 | authoring-complete-independent-checks/candidate-02/final-result.json | `bcaa389af2ef55c3577d9dbb550adf7ab172d27ec0ee01a0ba976cec7aa67ac0` |
| Score execution01，12项，硬Mock用途LOGIN/unknown/受控复用/完整范围；无真实模型资格 | score-execution-independent-checks/candidate-01/final-result.json | `afea60c119d107cfb022d181f790e4d2f7070384529dfd08eb8d55d3e299fefb` |
| Word主桥接01，11项PG/ASGI/no-net Docker/CPU parse/Memory；非完整Kafka/OSS或复杂业务Word资格 | word-mainflow-independent-checks/candidate-01/final-result.json | `b5ea12903f381722d1da765063a84427cef131f91d6bbfc75cbcc9a7c1087529` |
| HistoricalInput应用01，19项，固定327/4ops，Memory+PG；非历史真实材料资格 | historical-input-independent-checks/application01/final-result.json | `f1a6932b1646b4dd1519a09f9776f7a70473e82ec5fdbeb3a671da7ecc24c3cb` |
| Backend07，14项，归档/受限producer与Worker/助手真实registry/tasks/comparison路由范围 | backend07-independent-checks/final-result.json | `fc94f4ba0634ac37e529283cf918e5034ffd9e04a68a8db7a0e5a9ea697c021e` |
| 助手/A2 implementation01，14项，受限PG+显式Mock；非07正式全站组合 | assistant-independent-checks/implementation-01/final-result.json | `6fc91549c0224775949a0c41c7bd9cd1bc6711c732b7d5bd8c0d99474ef60704` |

此前真实OSS单对象传输、multipart、Parser隐藏文字、RAG重放与RR、普通模型账本、主04 Gate/报告/补录、metrics、知识、内容dismiss06等记录均保留在各独立目录，按其候选和真实执行边界引用。开发自测/架构静读不能替代测试执行；旧候选pass不外推后续moving源码。产品A1原13条及真实业务/真人/正式模型资格剩余项以产品验收清单和PM门禁为准，不能因本文件勾通过。

最后状态：**测试工作已静止，未发起新云请求/新Docker/新测试；后续先完成GitHub安全交接，再由PM排下一步。**
