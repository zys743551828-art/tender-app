# 完整图文准备租约与材料读取权限审查

material_preparation及tender_material_preparation_worker仅在全新独立检查库安装，不进BASE、正常业务库、API／公开HTTP或自动消费者。Worker LOGIN固定OID，只继承准备purpose，只有claim、heartbeat、inspect、owned_context、owned_asset、owned_assets六RPC，无直接表／列／序列、旧业务RPC或私有函数权限。owner不作运行时补权或代调用。

批准profile固定Worker主体、准确job profile及摘要、origin、接口／SQL方法、数据库身份、有效期和1—120秒租期，head／修订单列。跨purpose不能复制旧job.profile_current的session身份布尔；独立核真实登记者账号／OID／purpose、原profile／修订／时效／DB／SQL与不可变job记录摘要，再核当前证据、原请求授权、全部槽位、输入／报价及完整材料。Worker与请求者／登记／核验／续验／程序主体分开。

写入口独占RC／RW，治理→bid→图→command互斥后，锁Worker／job profile、证据head及完整来源／审核／新旧case。states行锁内原生创建lease UUID／时间、generation和单调fence；活跃租约不换主，过期重认领推进fence。samecommand仅恢复旧事实，引用冲突拒绝，不续期。heartbeat追加独立不可变回执后更新当前到期时间，原claim文档不改；旧fence、过期、来源／配置失效均拒绝。

inspect独占RR／RO，返回原claim和独立当前状态，校验当前账号epoch、profile修订、generation、fence与服务器到期时间。owned读取在开始和结束重新核当前lease，只允许该任务的准确旧context／输入metadata及同存储packet图像。context原生对象SHA、上下文摘要、旧input和binding摘要、冻结方法及false资格在客户端再核；返回metadata不是可直接执行的typedMaterialContext。

owned_assets一次取全部去重图像，不接受对象子集；按SHA的C顺序返回二进制数组，最多384对象、单张32MiB、合计64MiB。服务端核完整集合及字节SHA／长度，客户端再核数量、顺序、唯一SHA、每份内容及总量；截断、置换或替换拒绝。避免逐张反复核整个包的开销，owned_asset保留补读，非图context／原件／其他对象仍拒绝。事务结束后才做渲染／网络等外部I/O。

native_rpc_audit核五表／schema owner和34个明确函数的正文、owner、语言、volatility、search_path／UTC及caller EXEC；旧模块与审计器不改。返回协议不符在提交前回滚，错误只映射有界代码，正文、图片、locator、DSN和凭据不入日志／Outbox。二进制数据对象禁用repr，证据只留摘要及机制状态。

准备租约与原生绑定是受限准备事实，资金预留、输入／模型执行、发送lease、自动重试、账户价格、token fit、请求体、人工及原子快照资格仍false。合成不授生产资格。后续完整请求预检、实际序列化、费用预留／发送／结算、Worker运输仍独立验收；正常预览与Word保留。
