# 三范围聚合预算真实机制检查

`tests/test_assistant_budget_aggregate.py` 在独立 PG17 `fusion_budget_aggregate` 库运行，16 项通过；结束后确认自建 design schema 已清理。没有业务资料、供应商调用、真实价格配置或部署。

使用当前源码中真实五张预算表及 normalize/obligation/reserve 三函数逐字摘录，不执行完整归档初始化。job/member/native 等依赖使用最小合成表；`assistant_check_target` 是唯一明确的资格 no-op，不验证五事实、身份或来源效力。未安装完整角色/append-only/其他业务 schema，因此不授权限、配置变更API或完整助手链资格。

已验证：

- global/member/project 各自将上限设置为30、单次最坏预留20，双真实连接同时 reserve 仅一项成功，另一项预算不足，obligation=20且只产生一条预留。
- global 合并不同成员和项目；project 合并不同成员；member 合并不同项目。不同成员/项目各自限额不错误互相占用。
- 新窗口仍累计旧窗口 unknown 的原20预留；不足额度继续拒绝，没有清零。
- 缺少 member 限额或币种不一致均暂停受理。
- general与项目目标在 REPEATABLE READ / SERIALIZABLE 下直接调用 reserve，均由现有SQL入口拒绝；无新增预留或事件，既有intent不变。有效general在 READ COMMITTED 正常预留，防止负例仅因目标本身无效而通过。本片未修改生产隔离守卫。

目标对象和成员均为自建合成记录。资格 no-op意味着这些用例只证明预算会计边界，不证明自由填写ID可以成为独立真实问题；正式 target guard 保持待验。

## 摘录指纹

本片运行时完整 intent-budget.sql SHA256 为 `2ecee09f615b88f3f100e5eafb4303fe466aba851723aa52bdd6c3b8dcfdcc51`。后续身份 guard 修订可能改变整文件，以下逐字摘录指纹用于确定本片实际输入，不把 moving source 冒称原 SHA：

| 对象 | SHA256 |
| --- | --- |
| assistant_price_versions | 5370da760be2954e203616150e4d08e23a54719c1d3363f1dfbbdeec69ab0ef8 |
| assistant_budget_versions | f35b46632987d05bf4eef83ac669b9b995df5f561285ae56b2a99f1456484f68 |
| assistant_logical_intents | 23583a4fb47e951fdd88785a094f48938eed790242afbbba785297c4cff16f33 |
| assistant_budget_reservations | 240ad8acff6f0793a5f53f56a2bb7a3fd1580bb48ed73e8c2c2bea322c4922ca |
| assistant_budget_events | 792234a42f294668ec21bdafcbddddec049342e1d9dda4e67050508c3fcec26d |
| assistant_normalize_question | 03395129fe69019458c964183da033d6a15f264705f4889a5463a0ffd07300d0 |
| assistant_budget_obligation | 132cda3420af541c3f2f82bf9a3246eae91241e8541c0ef89f25ff409c214e65 |
| assistant_reserve_budget | 33e9b1abbf463409f82d3de1841ea223ae9c22ce875a99a1fd72c63506d9d696 |
