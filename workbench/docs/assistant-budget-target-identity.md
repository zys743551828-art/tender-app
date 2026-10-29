# 预算目标与稳定标段身份同源

`assistant_check_target` 的项目目标现在直接调用 `design.identity_snapshot_v2(bid)`，要求返回 `bid-identity/2`、当前 confirmed 状态及冻结 proof 的相同 authority ID。不再复制“round/bidder/project ID相等”的独立子集判定。

原生 identity/2 函数同时核完整关联字段、稳定 lot_id、主体登记及当前 identity.bound 审计；同ID主体改名、工程名称/地区/类型变化、轮次/标段文本变化、同名标段换稳定 ID，均会使旧确认 pending并拒绝旧 target。旧v1或缺版本绑定不自动升级，也不从时间推算冻结身份。

初始化依赖增加 `bid-packages.sql` 与 `identity/sql/stable-lot-identity.sql`，两者均须在 roles 的统一函数权限处理前执行，预算 SQL 排在其后。本片不改 fresh helper / 初始化入口或角色 ACL。

## 实际验证

`tests/test_assistant_budget_target_identity.py` 在专用合成 PG17 `fusion_budget_target` 库提取并运行真实 canonical_json、identity_association_v2、identity_snapshot_v2、normalize_question、assistant_check_target。最小表含项目、主体、轮次、审计及五事实；没有对 target 或 identity helper 使用 no-op。14 项通过，fixture整体回滚：

- 当前v2稳定身份及五事实可通过。
- 旧v1、缺版本、authority缺/错lot ID、当前lot NULL、同round换同名lot ID均拒绝。
- 主体同ID改名、工程标题/地区/类型变更、标段显示名/轮次变化拒绝。
- 成员私有 general 目标保持可用，不强制伪造项目身份。

首轮真实执行发现原函数 `name` PL/pgSQL 变量与 `fact_items.name` 列冲突（13失败、general 1通过）。已将循环变量明确改为 `identity_fact_name`，没有调整 PostgreSQL variable_conflict 规则；同一14项随后全部通过。这个失败说明之前以no-op替代target的叶RPC测试不能授实际target路径资格。

本片只闭合身份同源。五事实不可变确认basis、carryover、原页/当前解析及来源祖先live效力仍未在target SQL中闭合；测试不创建这些来源表，不冒称通过来源资格、完整schema ACL或ASGI/Worker链。预算整体正式费用与部署阻塞继续保留。
