# 助手 live 五事实资格检查范围

新候选是内部资格机制与预算 RPC 集成，不是生产部署。收费消费者始终关闭。

## 实际输入

| 文件 | SHA256 |
| --- | --- |
| packages/assistant/sql/live-facts.sql | 42fc9646225a67a8d209822ac9d0e3573e6903b3f5681042e9cb49fa6eeb11a2 |
| packages/assistant/sql/intent-budget.sql | 9b57df3476d308f18b22ecca6e6bf4b5f1ab1f44968043ae55ce970d934221c8 |

完整规范见 [live 资格协议](assistant-live-facts-protocol.md)。Python proof来源仍是原生人工确认basis及source_closure；缺basis不回推，不给旧任务补造证明。

## 验证

`tests/test_assistant_budget_live_facts.py` 在独立 `fusion_budget_live` PG17+pgvector空库执行实际 BASE_SQL、assistant.sql、live-facts.sql、intent-budget.sql。原生登记/identity绑定、解析、来源登记、连续五次fact_sets.replace_set确认自然产生等价carryover；使用实际Python project_identity/resolve、jobs.queue_answer、真实SQL target身份/源资格/reserve/dispatch，资格函数无no-op。

25 项实际检查覆盖：

- 合法原生basis/等价carryover与真实queue→reserve held、完整native账/步骤→dispatch sent。
- 仅撤回原件或parse来源、不改变任何五事实/heads；过期、移出当前资料角色、新解析，reserve与dispatch均拒绝，原held110及事件数保留。
- proof缺basis/缺引用/改fact identity/改闭包，原生新确认缺basis，最新carryover等价摘要破坏均拒绝。
- 真双连接撤回先赢、等待图锁期间自然到期均拒dispatch，无dispatched事件、不清零。
- 第一事实使用独立短期来源、后四事实使用另一长期来源，保留实际最后事实核验后人为延迟至第一来源到期；统一最终clock门拒绝，防止逐事实clock漏掉早期来源过期。
- 实际global queue和native reserve按target bid→run顺序，与普通bid→run竞争无死锁；新call冻结原lease。
- 新内部helpers PUBLIC与Worker均无EXECUTE，不新增原始facts读取授权。

联合原身份、会计、三scope、旧三类死锁/崩溃窗口与助手测试共199项通过（32.71秒）；ruff/format/mypy/bandit通过。原会计叶测试仍对完整资格使用明确替身，不能把它们当live资格证据；完整live资格仅由本模块授予对应机制范围。

## 限制及保留失败

本模块在完整schema上运行，但native model_calls/步骤由合成fixture按真实FK建立，没有启动Kafka消费者、实际Worker模型调用、ASGI/浏览器、OCR/Word或供应商。provider构造使用显式MockTransport且其handler一旦被调用即测试失败。实际API/Worker受限LOGIN整链另验；此片不替代真实模型费用或生产验收。

Windows首次执行在既有runtime读取协议时遇默认GBK解码失败，改用现有Python `-X utf8`后继续，没有改其他代理文件。并发夹具首次复用相同五编号，被原防复制项目机制正确复用旧job而触发重复步骤；只为独立合成工程设置不同的事实值，没有削弱生产防重发。

fixture的普通用例事务回滚；并发用例仅在专用库提交自建记录以供双连接观察，模块退出删除本次创建的design/retrieval schema。没有连接业务库或外部模型。
