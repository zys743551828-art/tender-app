# FR011 candidate02：官方结果来源权威修复

本候选修复架构 MET01；candidate01 原 manifest、冻结副本及架构原始两个反例均保留，不改写为已通过。本候选只改 metrics 独立包、独立路由与独立测试，不增加 SQL/权限，不使用 owner 执行业务，不发模型、OSS、研究或付费请求。

## 正向来源权威

`packages.metrics.sources.inspect` 是登记/查询、核验、统计和重放复用的数据库检查。正式核验需要本项目 `source_original`、官方角色、原件 blob 摘要相符的 canonical original root；每条逐字引文须属于所选原件的精确 parse、可用物理页和 text evidence，正文摘要相符，并有 canonical parse→original 直接边。原件缺图、缺头、精确解析未登记和未知来源全部失败关闭，不把空结果视作有效。

对 root 和每个精确 parse 的完整祖先闭包，检查 canonical document 身份、同项目官方原件角色和 blob 摘要、用途 official_label、已发布 head 及 revision。每个来源 known_at/valid_from 必须不晚于服务器当前时刻、查询 as_of 和业务结果 known_at；valid_until 必须在这三个时刻之后。结果的 announced_at/known_at/实交时间关系仍由原登记协议核对。仅登记的人工结果可保留 pending，但来源失效或缺失的官方记录不可作为已核实分母。

技术成绩在 FR011 的走势/在线误差投影也调用相同检查，并从已保存 outcome 决定提取 evidence IDs 逐一绑定原件/解析/物理页。此修复不更改研究模块自身的核验写口或授予新生产者资格。

## 事务与时序

核验事务强制 READ COMMITTED。初始 result 只用于找 bid，随后统一 **bid → advisory(90127,1) → 按 source_id 排序的祖先 heads FOR UPDATE**；等待后重读当前结果头和来源资格，直到追加核验 audit 与提交才释放。与现有 reviews/source_effectivity/RAG/A2/knowledge 使用同一锁序。无网络或模型运算进入锁事务。

核验事件额外保存服务器构造的 `official-source-authority/v1`：root、精确证据摘要、完整闭包 heads、完整 edges 及统一 digest。authority 不接受客户端输入。缺 authority 的历史 verified 记录仍是历史核验，但当前 usable=false；显式重新核验才可产生新的权威，不根据今天的信息补造旧资格。任意 head revision 或闭包/证据变化使原 authority 当前失效；不回退旧结果头。

GET 使用一致 RR 读取。当前有效性同时考虑真正的当前时刻，因此历史 as_of 不会恢复已撤回/已过期来源的当前可用性；这里不声明已实现完整历史 source head 重建。

## 幂等重放

Command 保存的 operation/result identity 和审计内容不改写、不追加第二次 effect。重放先按相同 bid→graph 顺序取得来源观察保护，再从原 result_id 重投影当前结果与来源资格、返回当前头 ETag 和 Idempotent-Replayed:true。已经更正/冲突/撤回的原成功响应不会缓存永久 usable=true；历史 verification 字段与当前 usable 字段分别保留。

## 自测与范围

保留原19项机制回归。新增18项用例：候选、未来 known_at、晚于业务 cutoff、未来生效、过期、撤回、缺 canonical/头/精确 parse、错误解析证据、候选祖先；已核实后撤回、revision 和闭包变化的登记/核验同 key 重放；最终核验等待撤回；持 bid 的事务仍可取 graph（真实非owner PG 反序等待防回归）；缺 authority 历史决定显式重核；技术成绩使用同一正向守卫。

所有原件、角色、证据、结果与预测数据均为自建隔离 PG 的合成机制夹具。通过测试不表示真实官方资料或预测质量通过，不授模型资格；有效真实在线配对仍为0。主 API 接线、完整用户旅程及独立测试/架构验收归各 Owner。本次没有远端调用或收费。
