# 当前包与冻结范围事实

`package_current_scope.observe`接收owned控制器冻结的项目ID、scope ID、scope摘要及明确预期方法摘要。独立LOGIN只能调用`current_technical_scope.observe(uuid,uuid,text)`，不能直接读取业务表；当前范围表、审计、实交、官方成绩、RAG均拒绝。调用前检查实际LOGIN／唯一能力角色、PUBLIC和继承的表／列权限、CREATE及其他SECURITY DEFINER入口；过权拒绝，不修复权限。

可选初始化文件`deploy/sql/package-current-scope-runtime.sql`创建独立schema、NOLOGIN能力组和单一SECURITY DEFINER函数，撤销PUBLIC执行，固定search_path和参数。原生函数在读取时拒绝非独立LOGIN或非repeatable-read／read-only事务。客户端核对实际函数的完整正文、语言、返回类型、执行模式、search_path与owner分离；不执行被替换的正文。方法绑定端口源码、初始化SQL及canonical源码，执行前后重核。

原生查询核对冻结scope准确摘要、当前项目阶段及提交存在性、已确认当前身份、目标包head、依据包head、当前要求清单及规则集。提交存在性只作当前事前用途阻断，不返回提交、成绩或事后正文。scope／两包／清单在读取前逐项限8MiB，组合结果再限8MiB；每条SQL有5秒超时。超限拒绝，不分页、省略或截断。

`package-current-scope-facts/1`包含完整原scope、目标包／依据包及各自身份、要求清单、当前身份与数据库观察时间。Python端保留以上内容，加方法／原生正文摘要和结果内容摘要。原人工排除、部分覆盖、未证明必要范围及原件“登记时核验”回执原样保留；登记时核验不能当作当前对象字节重核。

只有`native_current_facts_checked=true`。`necessary_scope_verified/original_bytes_reverified/input_authority_granted/execution_authorized/historical_existence_verified`均false，不产生正式核验binding。当前head或身份变化拒绝新观察，旧包／scope／报告及回执保持原值。同次只读快照不是持续有效性或发送租约；后续还需全部当前来源、必要范围权威、对象字节、独立原生登记及发送前CAS／lease。

此扩展不入BASE、不开放HTTP，不为正常API或模型Worker补权限，不把已有范围选择或评分分母声明升级为业务完整性证明。

有效角色／表列／窄接口权限复用纯`read_purpose`固定策略。窄RPC的owner分离包含直接及继承角色：核验LOGIN即使只通过所属能力组拥有RPC，也拒绝。当前范围方法绑定共用审计源码；旧观察不回填，新执行必须冻结新方法身份。
