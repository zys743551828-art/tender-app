# 原生输入封存权限审查

只在全新独立检查库可选初始化material_input_seal及tender_material_input_seal，不加入BASE37、正常业务数据库、API／Worker／HTTP或前端。实际封存LOGIN和OID与请求者、目标核验程序及独立核验者分别配置，只继承封存purpose，只有seal／read两RPC，无表／列／序列／私有函数权限，也不扩大其对独立核验schema的USAGE。

初始化者发布不可变profile，固定账号epoch、准确核验政策ID与摘要、origin、封存接口方法及实际安装四个SQL函数正文／owner／配置原生指纹、旧MaterialInput/3／context／存储方法、数据库身份／有效期。profile head单独可撤销或更换；运行时不创建或修复授权，不接受自报方法、正文、图像、输入metadata或资格布尔。

写入口独占RC／RW，治理→bid→图→固定命令互斥后再读，封存profile、独立政策、程序／审核head及两包完整来源head行锁内核当前状态。独立核验的实际主体／OID／purpose、政策及其修订、批准指纹、程序事实年龄、完整报告和来源仍须有效；已撤销再启用或过期不会仅靠旧核验通过值放行。服务器从准确核验和原生存储生成旧输入metadata，客户端提交前按固定引用与方法核对，异常回滚。

当前存储记录、packet、context／报告及所有页图／裁片对象集合联结逐项闭合，核每个对象实际字节摘要及长度，不只看记录存在。复用私有存储，不复制或日志化正文。只返回不可变原生封存身份、输入／存储根和旧引用metadata，不能从JSON恢复活的I/O证书。

同command准确重放保留旧事实，其他内容冲突，同核验／profile／修订只一事实；未知结果可断开重查，无HTTP或渲染重试。read独占RR／RO、只读取本实际LOGIN／OID的记录，旧事实与当前profile／核验／存储及来源状态分开，时效及撤销不能改旧回执；旧通过不等发送lease或跨I/O原子快照。

运行时检查递归角色、PUBLIC误授权、实际入口／两个私有函数及独立核验五个函数正文／owner／UTC／search_path和caller EXEC，交叉schema检查通过pg_catalog，不调用运行账号无权调用的helper。静态PG错误仅映射固定协议，不输出正文、定位符、密钥或连接串。模拟对象链接损坏仅在全新临时fixture中由初始化者注入并原样恢复，不在业务库停用触发器。

合成origin的software_input_sealed及原生绑定可以为true，正式输入／执行、原始发送、正式预测／历史样本／人工真值／lease／原子快照仍false；旧MaterialInput/3引用metadata全部旧资格保持false。当前生产配置、原生任务绑定、成本／发送及Worker继续分别实现。临时库／LOGIN／十五组及宿主端口／bridge须清理，保留正常预览与Word。
