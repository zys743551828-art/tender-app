# 严格历史 CPU 任务派发

此能力只发现并执行已经明确登记的严格历史CPU任务，不创建准入、协议、研究组、训练或评估任务，不调用供应商，不授真实样本、正式模型或评分资格。

## 安装与身份

在全新独立研究环境中按原要求安装BASE、model-governance、package-historical-admission、package-historical-research及完整package-history-exposure-bridge之后，追加`deploy/sql/package-history-dispatch.sql`。它不进入BASE、默认Fusion预览或旧恢复清单；现有数据库升级需独立审查，不以owner修复业务权限。

新增RPC为`package_historical_research.dispatch_candidates(purpose text, after_at timestamptz, after_id uuid, page_size integer) -> jsonb`。仅独立非owner train／evaluate LOGIN可调用；API、普通Worker、verifier、PUBLIC无执行权限。既有assert_role拒绝混合用途、原始标签／会话／证明读取权限和非READ COMMITTED事务。调用者不能以参数改用另一身份的用途。

发现前核对原readiness函数的准确来源摘要、安全签名及owner，核对完整76项共同曝光安装契约、13个原入口OID、当前函数／触发器／ACL与安装清单；不授CPU身份API成员资格或私有守卫表读取权限。守卫缺失或变化时拒绝发现任务。

## 有界目录与执行

页大小1—20，两个游标参数必须同时为空或同时提供，时点须有限。按`created_at,id`稳定升序，严格晚于游标；只返回同用途queued任务和租约已过期的running任务。paused、cancelled、failed、succeeded及仍持有效租约的任务不列出。数据库索引按用途与顺序支持该范围。

返回为最多20项的数组，每项只含`job_id`、正整数`generation`及带时区的`created_at`。没有研究组成员、正文、证明、标签、分数或最终集内容。发现不领取任务，也不授当前来源／执行资格。

Python派发循环先严格核对闭合字段、UUID、精确时点、代次、数量、去重及顺序，再逐项调用既有`package_history_runtime.run`。实际领取、当前来源、代次、owner、fence、120秒租约、心跳和发布继续由原SQL与执行器核对。评估仍先独立提交曝光，再在另一连接读取最终集，不把元数据发现当作曝光或跳过曝光事务。

竞态、代次变化和陈旧候选保持deferred，不换键、补造结果或强制接管有效租约；扫描位置仍前进，避免阻塞页后任务。空页才回绕，下一轮重新检查此前延期任务。数据库连接／权限故障终止当前派发，不继续领取后续任务。输出只含任务身份、代次、计数与固定状态，不打印数据库错误原文或配置。

诊断字段`completed`表示本轮核对到成功结果，可能包含竞争进程已经完成后返回的原结果，不等于新增CPU计算或发布次数。持久结果仍按原job唯一约束、owner与fence保证一份有效发布。

## 显式进程

`deploy/package_history_dispatcher.py --purpose train|evaluate --profile <私有文件>`默认执行一轮，最多5项。可明确设置`--batch-size 1..20`、`--cycles 1..1000000`与`--poll-seconds 1..300`；多轮进程持有自己的扫描位置，短期单轮调用不承诺跨进程持久游标或长期公平性。SIGTERM／SIGINT停止领取后续任务，当前owned执行按原协议收尾。

配置沿用原固定launcher：0600普通文件、非符号链接、只允许对应一个用途DSN；父进程以`python -I`启动固定子进程，仅传该DSN与固定locale／timezone。子进程不收到profile路径，不继承owner、API、另一个用途、存储或模型凭据。

本能力无HTTP／UI／默认启动变化。默认预览不自动安装或运行；完整研究部署须明确安装SQL并分别启动train和evaluate进程。原手工执行入口继续有效。正式图文特征、受控模型发布、真实配对与目标环境交付分别验收，CPU mean／median机制不代表真实预测质量。
