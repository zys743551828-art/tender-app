# 助手五事实 live 资格切片协议

本片在 identity/2 与预算会计守卫之上追加实际事实来源资格。新增资格进入正式 reserve/dispatch 两条 SQL 边界；没有资格依据时保守拒绝，不根据时间回推旧 proof，不改写旧确认审计。

## 共同依据与规范字节

Python 对每个五 typed fact 在既有 `confirmed_fact` 成功后冻结：原 `human.decision_recorded.payload.basis`（fact_identity 与 evidence.references/source_closure_digest）、当前完整 `source_closure` 数组，以及原 decision/fact/evidence 身份。沿用事实须保留原 decision 及 `facts.set_replaced` 的原生 carryovers，不另建资格登记表。

`fact_identity` 继续采用现有 fact_sets.identity：subject/scope/name/value/unit/evidence_ids，证据ID去重后按字符串排序。源闭包数组排序维持现有 source_closure 的 source_id、ancestor id；字段为 source_id/id/document_version_id/kind/policy_class/known_at/digest/revision/status/valid_from/valid_until。

闭包 JSON **逐字沿用 Python clean/sha 产生的字符串表示**。SQL用已有 package_canonical_json 对冻结 JSON 计算规范摘要，与原 basis.source_closure_digest 比较；同时逐条将冻结字段与当前DB值比较，时间字符串显式转换 timestamptz 与DB时间相等。不把PG自动输出的时间小数尾零格式重新冒充Python原字节。所有键均为现有封闭字段，来源闭包无浮点数。

audit basis 必须存在并与冻结 basis 完全相同；fact_identity 与当前真实字段重算一致；evidence references 必须逐一覆盖原事实证据，不能通过新引用或来源摘要替换原确认。carryover 必须有原生审计映射、相同 decision、相同等价 basis 摘要、相同 fact identity，拒绝缺链、循环、跨bid与未来采用时间。

## 实时资格

SQL独立核当前 fact head/decision head、真实证据→原页→解析→文件及blob、引用版本/来源revision、最新解析、当前材料角色。所有来源及完整祖先必须是当前bid允许的document/prebid_content，已发布、已知且仍在有效期；缺来源头或缺祖先闭包拒绝。只撤回源/祖先或产生新解析而不变五事实头，也必须拒绝旧 proof。

上述document/prebid_content与当前资料角色范围直接沿用 `packages/authoring/repository.py:assert_sources`，该函数本来就是 `fact_sets.evidence_basis` / `knowledge.bridge.confirmed_fact` 的资格依据；不是将所有通用知识来源缩窄为document。此片不额外增加原事实确认没有的page quality门槛，也不新增carryover深度上限；循环与缺链仍拒绝。

内部 SECURITY DEFINER helper 仅接受不可变job/原生fact/proof身份，固定search_path，不授权Worker原始事实表或任意查询。API受理与Worker发送前都使用同一SQL资格核验，Python原有 confirmed_fact 不被削弱。

实际接口为内部 `assistant_assert_live_fact(bid,proof)` 与 `assistant_assert_job_authority(job)`，创建事务内立即REVOKE PUBLIC，无API/Worker直接EXECUTE。后者委托既有identity/2 target核验再核五事实，只有正式reserve/dispatch RPC调用它。新fresh顺序为 BASE_SQL → assistant.sql → live-facts.sql → intent-budget.sql；不允许省略live helper后运行新预算RPC。

## 事务偏序

目标bid及需要保护的既有业务bid排序锁 → project operation/receipt或global run执行锁 → graph90127与祖先来源头排序锁 → budget90129 → native call/预留写行。SQL进入预算锁之前核目标与来源；持预算锁后只允许重复已持权威锁，不能首次补取bid/graph。

global Worker 在锁run之前从已验证冻结job锁目标bid；project路径沿既有bid/op顺序。一般general无五事实，但上下文已有来源守卫不省略。RPC保留READ COMMITTED要求，拒绝RR/SERIALIZABLE。撤回与发送争用同一来源图和头锁，资格在dispatch提交前保持有效；时间到期在最终门重新检查，不因等待锁而复用旧时钟。

五事实各自核验完成后，再对全部冻结闭包已锁祖先取同一个最终clock重查known/valid期限；这是提交前资格授权瞬间。第一事实的短期来源即使在后四事实核验期间到期，也必须在此集中门拒绝，不把逐事实早期clock当最终统一授权。

## 验证门

使用独立fresh PG17+pgvector实际core/domain/package/identity/retrieval/助手schema及当前预算SQL，不替身target、basis、来源或预算资格。以原生事实确认与carryover生成正例，完整target/reserve/dispatch均验证；负例包括缺basis、改proof/closure、源/祖先撤回、最新解析、角色/期限改变、等价沿用链破坏、跨bid、旧绑定。受理拒绝无预留/事件，发送拒绝保持held与原金额且零模型调用。

回归三类旧锁环，并补global run与targetbid顺序竞争、撤回/dispatch并发、等待期间过期。机制通过不授真实模型、正式评分或生产部署资格；收费消费者始终关闭。
