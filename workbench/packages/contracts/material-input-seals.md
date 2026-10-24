# 原生完整输入封存

封存账号与请求者、核验目标程序和独立核验者分purpose及实际LOGIN／OID。初始化者固定封存账号epoch、准确独立核验政策ID／摘要、origin、封存接口与实际SQL指纹、旧MaterialInput/3／context及证据存储方法、数据库身份和有效期，profile head另存当前修订。运行账号不接收或修改这些批准值。

seal只接原生核验ID／摘要、封存profile ID／摘要及固定command，不接正文、图像、MaterialInput或资格布尔。锁内重核独立核验的当前政策／程序／审核／来源及时间窗口、实际核验者身份与purpose，并对原生存储记录和完整对象闭合集合重核摘要／长度。准确context、报告和全部原件派生页图／裁片已有私有存储，封存只登记引用，不复制正文或允许请求方替换输入。

服务器从准确核验UUID／回执摘要与context生成binding/3，按旧MaterialInput/3的引用格式构造输入metadata及其digest，与原生存储／核验／批准profile绑定。旧输入metadata的native_binding_verified／input_authority_granted／execution_authorized仍false；原生封存另提供独立事实，后续Worker须使用原生记录及当前观察，不能信任请求方传入的metadata布尔。JSON不还原LiveMaterial或I/O证书。

同command准确重放优先，其他内容冲突，同核验／profile／head修订只一封存。read只查本实际封存者与OID的不可变记录，并分别观察现在的profile、独立核验、完整存储及来源是否仍有效；撤销、修订、过期不能改旧事实，也不能把曾经封存当现在可执行。合成origin可证明软件封存与原生绑定，正式输入／执行、原始判断发送、数值／预测／训练／历史样本／人工真值、lease和原子快照均不因此授予。后续任务、成本／发送与Worker另实现。

仅全新独立检查库可选初始化，不进默认BASE、正常业务数据库、公开HTTP或前端。
