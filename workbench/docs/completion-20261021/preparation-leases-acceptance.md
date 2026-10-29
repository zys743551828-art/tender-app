# 完整图文准备租约与owned材料读取验收

专用Worker以准确job和批准profile取得受限准备租约，原生记录generation／单调fence及服务器到期时间。未过期不换主，过期重认领后旧主不能心跳或读取材料；原claim与心跳历史不重写。见[契约](../../packages/contracts/material-preparation-leases.md)、[权限审查](preparation-leases-permission-review.md)及[回执](evidence/preparation-leases/receipt.json)。

最终Linux103项178.96秒：21原生、25协议／批量内容反例、45隔离、12编排。宿主70项14.27秒与其重叠；真实宿主另12项305.30秒。原生suite真实PG与回环GET、显式模拟派生；真实宿主受限Compose另验，不冒真实人工或生产输入资格。

profile固定Worker LOGIN／OID、准确原job profile及摘要、origin、接口／SQL、数据库身份、有效期和1—120秒租期。共同锁及Worker／job配置、证据head和完整来源／审核／新旧case行锁内核当前状态。旧job.profile_current包含登记者session身份，Worker不跨用途复用它；独立复核实际登记主体、profile／修订／时效／数据库／方法和不可变记录，再核原请求、续验、完整槽位与输入／报价根。

同claim command恢复旧事实不续期，新nonce不能抢占活跃租约。过期后新claim fence递增，旧主inspect仍可读历史，但owned读取及新心跳拒绝。心跳独立命令追加不可变回执后更新states到期时间，重放不延长；generation／fence、账号epoch、权限／方法／数据库／origin／时效、撤销／来源变化实际核。四连接同command只有一份claim，返回方法不符整笔回滚，不留states孤儿。

owned_context只取本任务完整context及原material_input metadata，核原生对象SHA、完整摘要、冻结方法和旧binding，固定原输入不改；这只是受限投影，不是绕过原serializer验证的typedMaterialContext。owned_assets一次取全部去重页图／裁片，按SHA C顺序，不收调用方子集；最多384对象、单32MiB、总64MiB，服务端与客户端均核完整数量、顺序、每份SHA／长度及总量。截断／置换／替换和非图对象拒绝，owned_asset保留补读。没有任意原PDF、其他对象或历史标签读取权限。

首轮未含批量的原生102通过。复查发现逐张读取会反复核整个存储包，加入一次性二进制整组取件并保留同等边界。第一次真实链跨越该源码修改，11通过／1失败：缓存的旧五RPC模块被新六RPC权限守卫以PREPARATION_DEFINER_EXECUTE_PRIVILEGE拒绝；此轮不是最终证据。保留本地原失败，固定源码后最终103及真实宿主12通过，没有授私有EXEC或放宽守卫。

实际宿主扩展原场景，在已经真实渲染／核验／登记／续验的同一job上认领、完整context比较、整组及单张PNG取件、非图对象拒绝、心跳和重开。全部owned字节SHA与此前实际渲染匹配，仍为全场24GET／16不同容器且全部停止／PID0，ownership无新增GET／渲染，不虚增场景数。七读取／程序连接在I/O边界idle；准备事务退出后才外部I/O。证据仅留摘要，不导出正文／图片。

七文件格式／静态、一实现Linux类型及两实现安全门通过；十源码／30证据与Git原字节匹配，全部旧方法、审计器和BASE37保持。5188为1276输入／68实际资源，登录／会话及三服务健康；正常库design136，无十可选schema／十九验证组。临时库／LOGIN／十九组0、端口／bridge清理，检查／渲染停止，正常Word保留。无公开HTTP或前端改动，开发源挂载观察不冒不可变发布；浏览器视觉缺口保留。

preparation_lease_created和native_binding只说明受控准备事实。资金预留、输入／模型执行、发送lease、自动重试、账户价格、token fit、请求体、人工／原子快照资格仍false，业务／模型／付费0。完整请求预检、原serializer适配、费用预留／发送／结算及Worker实际运输继续独立验收，真实效果缺配对资料不重复索要。
