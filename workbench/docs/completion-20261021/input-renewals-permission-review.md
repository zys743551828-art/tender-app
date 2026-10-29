# 完整输入当前证据续验权限审查

material_input_renewal及tender_material_input_renew只在全新独立检查库可选安装，不进入BASE37、正常业务库、API／Worker、公开HTTP或前端。续验LOGIN与报价、封存、核验、受控程序及请求者分别认证，固定账号OID，只有record／read两个RPC，无直接表、列、序列或依赖私有函数权限。初始化owner不参与运行时调用。

不可变profile固定续验账号epoch、准确报价政策及摘要、origin、接口／实际SQL方法、数据库OID／名称和有效期；当前head／修订单独保存。新旧事实准确引用，不选latest、不推算过去身份。共同治理→bid→图→command互斥及相关政策／程序／审核／来源head行锁内核验后，只追加续验UUID、时间、主体与闭合记录。

新核验必须来自另一个已持久化程序命令和程序结果，实际原生核验记录、主体LOGIN／OID、purpose和当前政策修订有效；新旧bid、scope、context、完整报告、方法、登记及审核引用逐项一致。续验逻辑command必须等于新程序已持久命令的command，不接受任意nonce冒充程序执行。记录明确区分原admission_verification与新current_verification，不改旧封存引用或报价。

依赖中的session身份布尔不跨用途复用。续验独立核对已记录封存者／报价者的实际账号、OID、purpose、profile／修订、方法、数据库、有效性与完整存储字节；旧核验到期导致的旧input_current不能继续当当前资格，也不能使同根的新核验失去续验能力。价格时效及当前head仍单独检查，不能借续验更换价格或隐藏旧金额。

Python接口通过固定声明复用native_rpc_audit，检查本组三表及schema owner、18个明确函数的实际正文、owner、语言、volatility、search_path／UTC与caller EXEC；旧依赖不增加USAGE或私有EXEC授权，旧冻结方法不改。提交前校验闭合原生记录、全部准确引用和方法，返回验证失败回滚。错误只映射固定协议，不记录正文、图片、定位符、DSN或口令。

read为独占RR／RO，限记录主体及账号OID；固定历史与当前profile／封存／报价／新核验状态分别返回。过期或撤销保持旧事实，当前资格为false。同command原引用重放返回旧事实，引用改变冲突，不能把重放当新当前资格。下游任务／账本必须在自己的事务中重新核准确续验及来源，外传JSON布尔不构成权限。

软件续验和原生绑定不授输入／发送／执行、资金预留、自动重试、账户合同、token可装入、请求体预检、原子快照或人工阅读资格。续验保留原material_input_digest／quote_digest，逐条请求内容与语义摘要核对不等于已有模型调用或账单验收。合成数据不授生产资格，正常Word与预览服务保留。
