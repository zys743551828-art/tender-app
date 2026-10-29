# 准确冻结context的受信实时派生绑定

`deploy/fusion_context_derivation.py` 是独立可信宿主装配层，不接API／Worker，不读业务env，不从请求接执行回执或资格布尔。接收由调用方独立固定摘要的完整 `MaterialContext`、三个独立空闲原生连接、已固定镜像／源码／硬超时的 `FusionAssetRuntime` 及受控原件端口。先核控制方法和连接，再完整复验、拥有一份context副本；不改原context身份、取得观察、input_as_of或摘要。

从准确冻结的manifest保留每份文档的全部details，固定physical_page、parent_image_digest及rectangle，交给新建的实际受限Compose渲染会话。整页与所有裁片均实际重派生；不能只保留整页、丢弃必要细节或换成新裁片。同一次原生材料流程完成完整原件GET、准确冻结解析／图关系检查，全部渲染容器停止后复查原生来源、当前范围和所有定位，无事务跨GET或渲染。

复用既有逐文档执行回执核验，核镜像／源码／墙钟、实际停止、独立容器及准确原件／manifest。除页图派生观察外，其余完整材料规范字节须相等，新取原件与冻结原件逐字节相等。每份页图先完整校验两个manifest及其全部PNG，再核固定字段与PNG字节完全一致。只将digest、rendered_at、cropped_at及parent_manifest_digest四项观察标识分开保存；裁片的父manifest摘要须能按各自实际渲染时间重建，不能忽略父链接。所有文档、解析、证据块、整页、裁片、坐标、方法、限制及资格字段均不能改变，不截断、不追取“最新”。

只使用新取的原件和已逐字节核同的实际派生页图，结合旧不可变manifest／取得观察与context元数据重构，再由原有context验证器完整复验到同一根。这不声称本次在旧时间渲染；新manifest及真实派生时间完整保留在独立映射中，并固定旧manifest摘要、稳定内容摘要和实际PNG相等事实。新鲜material摘要可以不同，旧context及其material摘要和全部资格位不改。总观察上限4MiB，方法固定源码、依赖方法及容量，运行前后复核方法和运行参数。

`LiveDerivedContext` 中 `trusted_derivation_bound`、`exact_frozen_context_preserved`、`frozen_detail_crops_preserved` 只说明这次受控实时流程已将实际派生与准确context绑定。它不是可凭JSON反序列化或构造dataclass而自行授信的权威凭证，持久化后仍须由独立原生登记及主体配置承接。实际视觉可读性、必要范围、原生binding、正向输入、执行、历史存在、原子快照及发送租约均false。

固定宿主检查入口 `deploy/fusion_material_checks.py` 同时复跑原7项原生派生用例和准确context／裁片新用例，结果写入被忽略的 `.local/context-derivation`；现有Compose组、随机127.0.0.1检查端口和临时bridge的还原清理流程保持。不安装新运行时、不启动旧Claude容器、不改变正常Word。所有材料和配置均合成，真实人工审核／正式评分／费用／Worker另验。
