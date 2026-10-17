# 运行状态、重建与私有资料交接

GitHub源码检查点与当前机器的运行状态是两种交付物。**密钥、成员口令、DB dump、Cookie、私有原件和运行数据不放进Git。** 它们保留在原机器；跨机器继续时由项目负责人经安全渠道传递或重新配置，不能仅靠clone还原其原身份。清单只提供路径与用途，不提供秘密值。第三方模型缓存可重下，冻结候选和失败证据不可重写为新结果。

## 当前/计划环境

| 环境 | 端口与绑定 | 状态/约束 |
| --- | --- | --- |
| 早期combined04 | API8806，前端5176及知识09 overlay5179，PG55441 | 固定248源，actual33e3…129/150；保持旧运行身份，不混入新候选 |
| workbench08 F05 | API8808，报价08前端5178，Kafka19097 | 固定310源，actual3249…161/188/310；document/export/comparison及免费索引控制面；无paid/assistant/research消费组 |
| Parser03/CPU RAG | 8812/8810 | 独立解析与检索服务，固定源资格不授复杂Word/RICH资格 |
| 助手/任务夹具05 | API8816、Origin5184、前端11 | 本地对象+显式MockTransport，private控制文件必须hold；旧unknown不清。新budget未接本实例 |
| paid一次验收专用 | API8804 | 固定157源；真实付费消费者未启动，原费用审批未得答复 |
| 新统一native | 计划API8818、Origin5186、Kafka19098 | API/Worker/12前端尚未启动，clean delivery03 DB尚未创建。勿将app_composition02含Memory验证行的库作纯净用户演示 |

PID是可变运行观察，不作为跨机器identity。停止进程前须核UID、完整argv、具体角色，不能按端口/模糊字符串批量kill。未被本次交接明确关闭的旧环境保持原状；后台进程不会成为GitHub可恢复制品。

## 原环境私有路径

全部相对 `/workspace/tender-workbench`，通常600、目录700：

- `.env`、`.local/*-init.env`：初始化owner与新建库恢复身份。只用于新空库/成员引导，不修业务权限。
- `.local/*-runtime.env`、`*-checks.env`、`*-model_train.env`、`*-model_evaluate.env`、`*-model_score.env`：业务和独立用途身份。不得把owner/评分/训练/评测/预算管理员DSN注入普通API或Worker。
- `.local/workbench08-runtime.env`：现F05实例；`.local/assistant_ui01-runtime.env`及`.local/assistant_ui01-test-members.json`、`.local/assistant_ui01-control.json`：夹具05/前端11，control=hold。不要重用测试成员作为正式成员。
- `.local/app_composition01-*`、`app_composition02-*`：17/19SQL机制库；后者已有组件测试行。`.local/score_denominator01-*`为已执行B，不改它来补C。
- `.local/authoring_rich01-*`、`technical_scale01-*`、`score_execution02-*`：各自独立用途检查库。
- `.local/backups/application/drill04-20261017-c23d8a71/archive`：code05开发串行恢复的真实dump/manifest/7合成对象档案。原件保持；不是生产备份。
- `.local/qa-recovery05-*`：独立QA首次失败和后续未执行prepared身份/receipt。旧target失败卷保留；不会因生成新prepared就允许复用旧目标。
- `.local/parked-early-object-stores01/`：两早期S3容器rootfs gzip、原始配置与engine recreate payload。不可入Git，含私有存储身份。原始named volumes均保留，不能凭新随机身份“恢复”旧资料。
- `.local/models/`约4.3GB、`.local/parsing-models/`约6.3MB：本机Embedding/rerank/解析缓存。保留模型ID/版本/来源并按各RAG协议重新取得，文件不进Git；没有这些能力应返回明确不可用，禁止伪造检索质量通过。
- `.local/handoff-publication/`：本次发布的本地扫描/完整性回执，含私有文件路径元信息；不含已打印秘密。
- 文档仓库若存在`*-private-input.json`，保存的是夹具子进程输入；本次按具体秘密扫描结果/人工分类决定是否发布，不能只按“private”名称推定安全。被隔离项的原字节本地保留并记哈希。

## 新Kafka19098临时park

- 新集群ID `N8d3T4cNR6Wt6Ba9RX3kgA`，broker19098/controller19099，原始9topic，0消费组；无业务消息。
- `.local/kafka-app02-data`、`kafka-app02-server.properties`、原启动日志全部保留。仅暂停JVM并移除210MiB可再生`.local/kafka-4.1.2-app02`二进制树，释放OPS独立QA容量。
- 精确镜像：`apache/kafka@sha256:5cc2a2fd93fa2687b44015eee04fb2c3edd9e526bd64bf8bec5ff1e268772e0e`，已缓存的source容器`tender-workbench-protocol01-kafka`中`/opt/kafka`。
- 重启：从该**不变镜像**重新展开同二进制路径，逐文件核文档`04-验证与测试/integration-runtime-checks/application02-native/kafka-binaries-and-config.json`原SHA；用原config/data与JDK21启动。**不format，不新cluster id，不覆盖旧日志**。只传PATH/LANG/TZ/heap/LOG_DIR正向环境。
- 仅在OPS唯一目标容器已清理、余量允许后重建缓存。19093—19097旧broker有稳定消费者，未经新的具体论证不可停。
- Topic当前工具默认07实际policy，9个topic；`packages/contracts/policies/execution-policy.json`的6个只是历史目标快照。实际检查应传expected cluster id并先check-only。

## 两早期S3容器park

原QA19002、dev19000容器已退出并移除，**named volumes不删**。配置/HostConfig/网络/数据卷和rootfs已存上述私有目录。

- QA旧ID79c3ec4a…，volume`tender-workbench-qa_object_data`。
- dev旧IDdee6a231…，volume`tender-workbench-dev_object_data`。
- 精确restore-create-payload.json与restore-plan.json在私有目录；须核镜像、网络、volume、bound config SHA后按原参数创建并启动。公开索引在`integration-runtime-checks/early-object-stores-parked01.json`与`early-object-stores-restore-plan.json`。
- 第一次park脚本因Mounts列表排序不同而停止的失败保留；resume02按Destination map比较后完成，不意味着Mount身份改变。

## 新环境重建顺序

1. 克隆5个仓库的同名handoff分支。新源码在tender-app/workbench；按START_HERE建立原路径，先跑只读publication inventory，不启动服务。
2. Python3.12、Node24/npm11；按`requirements.lock.txt`安装基础环境，RAG/parsing分别用对应锁。前端npm ci只重建依赖，不改锁。JDK21仅用于native Kafka方法；受限Docker按平台proxy/CA配置，不hostnetwork、不绕过代理。
3. **不要直接使用历史README的最小initialize_database.py作为最新完整应用初始化器。** 通过已审helper03、统一02 final recipe19份精确SQL的digest检查后新建空库与7限定LOGIN；先核连接identity再DDL。helper04已有隔离阻塞，不能执行。
4. 原环境已准备、未执行的脚本在文档`integration-runtime-checks/create_application_delivery03.py`（clean19SQL/Origin5186）与`create_score_denominator02.py`（新20SQL/C）。先读脚本/检查固定SHA；不能复制其创建名称后重跑到已有库。不可通过owner在旧库临时补权限。
5. Word03最终review通过后，从其固定源根生成新Word与generated PAGE profile；profile包含runner路径/源码指纹，只能据同根生成，不能借旧root profile。private600，受限runner只读。默认Word入口能否启用以真实能力检查为准。
6. 只启动明确授权的普通document/export/comparison、relay/reconcile与免费索引。**paid review/assistant/research不启动**。两新QA成员用新随机凭据私有保存。新API实际OpenAPI/所有产品模块来源与固定manifest绑定再联调5186。
7. OPS恢复必须另有经审计的目标身份/精确源档案/资源门与实际调用限额；本次仅一次7+7云授权，读testing.md确认未消耗再执行。禁止私自扩大到全备份或真实文件。

## 恢复资格边界

代码/文档能从GitHub恢复，私有配置可重新配置，但原DB中的unknown、审计与旧身份不是新随机种子可代替。若原环境将销毁，需要项目负责人另行安全保存上述私有档案和数据库/卷，当前GitHub提交**不包含完整运行实例备份**。接手者必须看到这个限制；不能以源码清单通过声称生产RPO/RTO或跨机器原样运行恢复已完成。
