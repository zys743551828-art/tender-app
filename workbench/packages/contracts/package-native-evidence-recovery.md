# 原生私有证据的当前用途恢复

`package_native_material_recovery.py` 通过独立原生证据reader、scope、original、parse四个空闲连接，按调用方固定的bid／scope／scope摘要、command／packet／原生记录／context摘要读取。没有“最新”查找、连接创建、角色切换、权限修复、SQL写入或模型调用。

先固定读取所属原生记录的全部私有对象并核SHA／长度，取得准确旧context、取得观察、PNG及声明；初查当前范围、准确冻结解析／完整来源图，与旧冻结内容逐项比对。重新GET全部原件，核字节与摘要，随后再查解析／来源图、当前范围及全部定位；任何撤回、关闭、修订、原件变化或错配都拒绝整份结果，事务不跨GET。

只用本次新取原件和记录固定的全部图页重建，并由原context验证器完整复验到同一根；旧取得观察／input_as_of／manifest／摘要不改。重建完整范围清单并复验全部报告事项／逐字引用／图页，改范围或无法判断保持声明，不转成确认。记录本身只证明bytes；即使是原生有效、重算过摘要的私有对象，其报告／派生关系不合格仍拒绝。

存储中的派生观察只重新校验结构、所有manifest／父链接、PNG与固定字段一致性、逐文档声明回执及源码／镜像／容器声明的一致性。不执行新渲染，不把读取出的JSON包装成LiveDerivedContext，不替配置主体认证其内容或执行事实。返回 `RecoveredNativeEvidence`，单列stored_derivation_claim，清楚区分当前原生／原件事实与过去存储的声明。

结果保存独立新恢复观察，固定原生记录／packet／context／报告／派生根及本次当前来源观察。`current_native_parse_and_originals_rechecked`、`stored_scope_findings_revalidated`和`stored_derivation_claim_consistent`描述本次检查；`page_assets_rerendered`、`trusted_derivation_freshly_verified`、实际人工阅读、必要范围、原生binding、输入、执行、历史存在、原子快照及发送lease均false。后续原生资格须核经配置的实际生产者／审核主体及当前来源，不能凭恢复类型或布尔自行授信。

无新增SQL／权限／公开HTTP／UI。复用已有八类核验组，检查仅全新独立Compose库，结束清理并停止检查服务、保留正常业务与Word。合成声明的Linux机制测试与真实宿主旧派生／存储后当前恢复分别记录，不混作人工审核或真实评分验收。
