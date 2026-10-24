# 完整图文任务登记权限审查

material_judgment_job及tender_material_judgment_submit仅在全新独立检查库安装，不进入BASE、正常业务库、API／Worker、公开HTTP或自动消费者。登记LOGIN固定OID，与原请求者、核验／续验／封存／报价／程序分别认证，只获start／read／refresh；无表、列、序列和依赖私有函数权限。初始化owner只用于全新配置与夹具，不承担运行时登记。

批准profile固定登记主体、允许的原请求主体、准确续验profile及摘要、origin、接口／SQL方法、数据库身份与有效期，当前head／修订单列。当前检查独立核已记录续验主体实际OID／purpose／配置／时效，不跨用途复制含session身份的布尔。原封存、报价、当前独立核验、完整来源及字节对象沿原生链核验；完整规则从私有context取得，与原报价规则数组逐项相等。

intent追原封存准入核验所引用的原生程序逻辑请求。原请求实际LOGIN／OID、case有效期及当前授权修订仍须有效；另一个有效新核验case不能绕过原请求撤销。新核验UUID、新续验或任意新命令不产生第二份同intent任务。原intent唯一约束与共同治理→bid→图→command锁配合，锁内核相关profile／新旧case／审核及完整来源head。

start在一事务内保存固定job、完整规则每条三个native槽、初始续验证据／head及仅含job_id／generation的准备Outbox。预算不足不创建部分任务；槽位UUID不是模型调用ID。samecommand原引用优先恢复，引用变化冲突；不同command同intent明确拒绝。提交前闭合记录、全部槽位及准确引用独立验证，失败整笔回滚，不留孤立槽或事件。

refresh只接受本主体及OID的准确job、同封存／报价／输入／完整规则的新续验、预期证据revision与command。行锁内追加不可变事件并推进head，原job、槽、报价及intent不改。旧revision冲突、旧命令准确恢复。read为独占RR／RO，固定job／证据历史与本次当前性分开；到期、撤销或槽位不完整使准备资格false，历史不改。

native_rpc_audit核七表／schema owner及24个明确依赖函数的正文、owner、语言、volatility、search_path／UTC和caller EXEC，旧冻结方法与审计器不改。异常只返回固定协议，不记录正文、图像、定位符、DSN或口令。Outbox未运输，无正文或价格／凭据载荷。

状态awaiting_budget_reservation、generation=1仅为登记事实。资金预留、Worker／发送lease、输入／执行、账户价格、token可装入、请求体、自动重试、人工及原子快照资格均false；合成数据不授生产资格。后续owned Worker、账本及发送必须各自核验，不能信任外传JSON。正常预览和Word保持，独立检查资源在验证后清理。
