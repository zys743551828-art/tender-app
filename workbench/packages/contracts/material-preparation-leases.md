# 完整图文任务的受控准备租约

Worker只能凭准确job及批准准备profile认领任务。profile固定Worker LOGIN／OID、准确job profile及摘要、origin、接口／SQL方法、数据库身份、有效期和1—120秒准备租约。准备权不授费用预留、模型发送或结果发布。

同一job只有一份当前准备租约。认领原生生成lease ID、时间、generation和单调fence；未过期不换主，过期后新认领推进fence，旧lease不能心跳或读取材料。同command准确恢复原事实，不能借重放续期。心跳独立命令追加不可变事实后更新到期时间；历史与当前状态分开。

所有写入口在共同治理／bid／图锁及job证据head、配置／来源行锁内复核。当前job的实际登记者LOGIN／OID、目的、profile／修订、原请求授权、续验证据、完整规则槽位、报价及材料必须有效；不能直接复用要求登记者session身份的旧profile_current布尔。准备profile和账号epoch分别核对，其他purpose、同组其他账号、旧fence或过期租约拒绝。

owned_context只返回该任务的准确封存输入metadata、完整context及对象摘要；owned_assets一次取回同一原生存储packet的全部去重页图／裁片，按SHA的C顺序返回，不接受调用方子集。最多384对象、单张32MiB、合计64MiB，客户端逐项重核数量／摘要及完整集合。owned_asset保留单张补读。任意源PDF、其他任务对象、解析／成绩／标签不因准备租约可读。每次读取均重新核原生lease／fence／当前材料，固定旧输入引用不改。返回完整metadata不等于重建了带权威的MaterialContext，不得绕过既有完整图文序列化校验。

读取独占RR／RO，写入独占RC／RW；返回后数据库事务关闭，再做文件／渲染／网络I/O。材料正文、图片、locator、凭据和DSN不入日志／Outbox。profile仅在全新独立检查库安装，不增加正常业务库、API或公开HTTP权限，不启动自动消费者。准备租约不冒发送lease、账户价格、token fit、请求体或正式评分效果验收。
