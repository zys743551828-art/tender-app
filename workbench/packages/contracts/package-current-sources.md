# 独立当前来源观察

`package_current_sources.observe`只消费owned控制器冻结的项目ID、文档列表及明确预期方法摘要。文档项闭包为`document_version_id/source_digest/source_byte_size/parse_run_id/parse_digest/page_count`，不接受调用方的来源状态、历史时间或官方标签。文档最多32份、单份128页／32MiB、合计256页，重复文档、非规范UUID、布尔冒整数及多余字段拒绝。

连接必须是idle的独立非属主LOGIN，除`tender_current_source_verify`外无其他角色继承；核验器拥有repeatable-read、read-only事务，每条SQL有5秒超时。可选初始化授权文件`deploy/sql/package-current-source-grants.sql`不入BASE，不修复业务权限。仅允许八张原件／解析／来源表读取，其中原件表只开放八个元数据列；原件locator、实交、官方成绩、检索chunks及模型调用读取拒绝。有效权限审计包含PUBLIC及继承角色；额外表／元数据列、写权限、schema／database CREATE和可执行SECURITY DEFINER例程导致拒绝，不自动撤权。

原生查询重核项目、PDF元数据、确切parse及全部页／证据身份。先在数据库计算容量，再复用冻结解析算法；最多20000块、2MiB文字及8MiB解析元数据，不截断。原件和解析来源ID遵守既有UUIDv5规则，解析必须直接派生自对应原件；遍历全部祖先，不使用检索结果或旧历史核验器。节点及边分别最多20000，最多64层；缺节点、循环、跨项目、摘要错配、非prebid文档、未发布／撤回／未来／过期拒绝。方法摘要在读取前与独立预期匹配，读取后重核，变化不发布观察。

结果为`package-current-source-observation/1`：数据库观察时间、方法、文档、计数、根／节点／边及内容摘要。结果不含正文、原件locator或凭据；只有`native_parse_and_current_sources_reverified=true`。`original_bytes_reverified/necessary_scope_verified/input_authority_granted/execution_authorized/historical_existence_verified`均false。本结果不是`package-technical-verification-binding/2`，不能代入正式输入回执或发送账本。

repeatable-read保证同次观察内部一致，不能阻止观察后的撤回。正式安装仍需原件字节端口、当前包／身份／规则与必要范围核验、独立原生回执注册及每次发送前的锁／CAS／lease重核。没有任何时间推算的历史原件或解析存在性证明。

有效权限检查由纯`read_purpose`模块执行，角色／可读表列／允许的窄接口是实现中固定的独立策略，不接受请求字段，不加载环境、不建连接、不切角色或修复授权。来源观察方法同时绑定这份共用源码，旧观察保留原方法摘要。
