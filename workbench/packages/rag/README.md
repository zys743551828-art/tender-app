# 本地检索与证据链

该模块实现真实CPU BGE-m3分块／向量、本地中文分词、PG向量与词法精确检索、RRF、可降级的真实重排、来源资格与引用校验。正式评分使用独立的完整章节和三判断协议；查证片段不成为完整评分输入。

## 运行

模型运行依赖与后端分离，权重只放被忽略的私有目录。首先创建`.venv-rag`，从`https://download.pytorch.org/whl/cpu`安装锁定CPU Torch，再安装根目录`requirements-rag.lock.txt`。`deploy/fetch_rag_assets.py`下载两个固定官方revision，验证权重SHA，保存全部六项资产清单；运行阶段不下载模型、不执行远端自定义代码。目录存在额外未验证模型文件时拒绝加载。

私有配置需要`RAG_RUNTIME_URL=http://127.0.0.1:8810`、随机`RAG_RUNTIME_TOKEN`、`RAG_ASSET_DIRECTORY`。新环境配置器生成这些字段。模型进程只接收模型角色环境，不应持有数据库或云服务秘密：

```sh
.venv/bin/python deploy/run.py --env-file .local/external-release.env --role model -- .venv-rag/bin/python -m packages.rag.server
.venv/bin/python deploy/run.py --env-file .local/external-release.env --role api -- .venv/bin/python -m packages.rag.coordinator
```

API控制面仅用受限API LOGIN，扫描新解析并持久安排`rag-index/1`任务；Outbox／Kafka文档topic和受限Worker处理任务。业务接口为`POST /api/v1/retrievals`，客户端只指定项目、普通界面上下文、查询和数量，不指定正式评分用途、来源白名单、业务时点或模型profile。

Worker运行还需要正常的relay、document consumer及reconcile。新空库初始化在基础角色脚本后执行`deploy/sql/vector-runtime-grants.sql`，只给Worker所需的三个纯向量函数；业务不使用owner。现有早期测试库不会自动成为完整RAG环境。

## 身份与并发

- 分块使用实际Tokenizer的原文offset，默认800／1200／120 token，保留物理页和原始块；不把中文字符数当token。
- 原件有稳定root来源，每个parse有确定子来源与完整祖先关系。`parse_source_id`和`original_source_id`供其他模块共用。撤回归一到原件根，重新解析不能恢复已撤回来源。
- 索引分为只读准备、无数据库连接的模型计算、短事务发布；发布仅使用已准备的词法与向量数据，不持图锁调用HTTP模型。相同parse存在其他分块方法时拒绝覆盖。
- profile绑定模型revision、权重、全部配置／词表资产及运行依赖。查询和索引须同一profile、1024维、有限值和L2归一化。
- 白名单向量先物化再精确排序，避免HNSW过滤改变默认路线。词法和向量各50候选；含数字／编号的查询另走相同有效范围内的字面精确通道，最多50候选，之后共同RRF融合。前20可重排，最多提供8个证据包。重排失败或缺少模型身份时保留原RRF顺序并明确降级，不标作成功重排。
- 数字通道只用于召回：查询表达式进行NFKC规范化，保留标号、版本、小数、正负号及ASCII标识边界；不将C30匹配成C300，不将3.2匹配成3.20，不解释单位换算或条款含义。单次最多32个不同标识、单项64字符，超限拒绝。原文、页码、引用内容不被规范化重写；方法版本进入实际检索策略摘要。
- 每次应用在同一短事务内先锁定项目上下文，再持来源图锁核验head与最终chunk资格，直到写入effect后提交。来源／祖先变化、排除组变化或正文／资料head变化均拒绝继续应用。幂等重放也重新核查当前范围。
- 引用ID对应实际提供的来源、parse、物理页和逐字摘录。逐字校验不等于已证明模型的语义主张；未验证主张不能据此成为正式事实。

## 验证与范围

`tests/test_rag_core.py`和`test_rag_http_port.py`是显式机制测试；`RUN_RAG_REAL=1`启用`test_rag_real_integration.py`，需要真实本地模型、独立测试库和受限LOGIN。`tests.probe_rag_pipeline`核验已实际上传的合成PDF、Kafka索引effect、当前ASGI查证和可逐项还原的引用。

当前公开检索仅接本项目文档，历史上下文也限本项目；企业知识发布与跨项目适用由后续领域接口提供，不能靠请求扩大白名单。扫描、表格和图页的未读范围来自解析记录；能索引可读文字不代表整份资料全部读懂。真实公司资料召回／引用质量、业务检测精度和正式评分资格独立验收。

## 可复现的独立本机验收

`deploy.rag_native_acceptance` 可以用明确指定的现成PG17二进制、离线模型Python和已核验BGE资产启动全新私有进程。PG安装须同时有`vector`和当前基础schema需要的`uuid-ossp`。应用测试环境另安装`requirements-fusion-checks.txt`（包含合成PDF测试依赖），模型Python依照前述RAG锁文件安装。

```sh
.venv/bin/python -m deploy.rag_native_acceptance \
  --pg-bin /absolute/path/to/pg17/bin \
  --model-python /absolute/path/to/rag-venv/bin/python \
  --assets /absolute/path/to/verified-models \
  --receipt /absolute/path/to/new-receipt.json \
  --scales 1000 10000 50000 --unique-texts 128
```

每次创建新库、不同非owner API／Worker登录和随机loopback端口，不接现有服务；模型进程不持有数据库口令。结束后停止本次进程，成功时清理本次临时数据与配置。失败诊断私有保存，不将口令或正文输出到终端。收据记录实际SQL输入摘要、模型／词典身份、测试结果、执行前后源码一致性以及分档容量；路径必须是新的收据文件。

容量档测量的是全部1k／10k／50k已授权文档chunk的实际SQL检索，不截为5k；128种合成文本先执行真实BGE embedding，重复文本复用相同真实向量。这个设计不测50k不同文本的embedding耗时，不证明企业知识大于5000个适用单元的业务范围，也不证明真实标书相关性。SQL耗时、实际CPU重排耗时分别报告，不能将SQL P95写成用户端到端延迟。当前结果见[本轮独立验收](../../docs/completion-20261021/local-retrieval-acceptance.md)。
