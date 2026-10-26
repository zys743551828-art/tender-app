# 阶段：完整材料请求预检与原生恢复衔接

## 本阶段交付

新增 `packages/model_governance/material_request_preflight.py`，将现有原生准备租约与原完整图文 `/3` 序列化器实际串联。原准备租约、原输入、原序列化器、原供应商端口及 SQL 文件均不改写，不重新解释历史方法或旧输入资格。

此前 Worker 可读完整 `owned_context` 和 PNG 集合，但它们不是 `MaterialContext`，不能直接转换成有完整来源证明的模型输入。本阶段保留原验证链：`material.verify_input` 继续核对完整来源、原 PDF 字节、解析、整页和裁片，再对照准备租约所授予的原生投影与实际图片字节。JSON 类型包装、相同摘要或已领取的任务均不能替代这一验证。

### 1. 全部纳入规则的完整请求预检

`preflight(connection, bundle, ...)` 依次执行：

1. 核对固定方法、序列化器和准备方法，并要求连接没有在途事务。
2. 通过现有窄 RPC 读取当前租约，拒绝过期或已失效的准备权。
3. 调用原完整输入验证器；读取同任务的完整原生 context／input metadata，逐字核对。
4. 一次读取全部去重 PNG，逐份核对完整集合及真实字节。缺图、替换图像、跨任务或不同来源不能继续。
5. 对**每条纳入规则**实际调用原 `prepare_request` 与请求校验器，沿用完整文字、全部页图／裁片、请求大小及图像限制。不按预算或大小截断规则、删页或缩放。
6. 每次计算后只保留请求摘要与长度等元数据，丢弃请求正文，不在内存积累最多 400 份大型请求。
7. 全部完成后重新读取完整投影和当前租约。证据 revision、来源或租约发生变化时整批拒绝；成功回执不代表两个观察之间原子有效。

回执包含准确 job／quote／input／context、generation／fence、证据 revision、全部规则请求摘要、每轮请求字节数、核验时点与到期时间。它不包含原文、原件、图片、凭据或请求体。

### 2. 按原回执重建单条请求

`prepare_rule_request(connection, bundle, checked, rule_id, ...)` 先验证原预检摘要，再重新核当前租约、完整输入和图片集合，调用原序列化器重建这一条规则的请求，逐字段比较原请求回执并在末尾再次核对来源。

三次判断复用同一条规则的完全相同字节。槽位、attempt 和前次答案不进入模型输入。排除的规则、未预检规则、伪造／不完整回执、过期租约和不同输入均拒绝。此函数只返回有界请求，不执行发送或自动重试。

### 3. 可执行的原生恢复入口

异步入口 `restore_and_preflight` 已调用现有 `package_native_material_recovery.restore`，不要求调用方自行伪造或拼接 `MaterialInput`：

- 准备 Worker、私有证据读取、当前范围、原件定位、准确解析使用五个独立连接。
- 以当前准备投影固定 context、项目与 scope，调用方明确提供既有存储 command／packet／record 摘要。
- 沿用原恢复流程重新读取全部当前原件并核对解析和来源，准备 Worker 不新增原 PDF 或私有存储权限。
- 恢复出的 context 必须与原生投影逐字相同，再用服务器原封存的 binding 重建准确旧输入。
- 外部原件读取前后全部连接没有在途事务；恢复完成后重新走全部准备权和完整请求预检。

调用顺序：

```python
bundle, checked = await restore_and_preflight(
    preparation_connection,
    store_connection,
    scope_connection,
    original_connection,
    parse_connection,
    **explicit_frozen_references,
)
request = prepare_rule_request(
    preparation_connection,
    bundle,
    checked,
    selected_rule_id,
    expected_preflight_digest=checked.metadata["digest"],
    expected_method_digest=method_digest(),
)
```

`explicit_frozen_references` 必须由安装者明确固定准确租约、输入、方法及存储引用。入口不会探测配置、自动续期、选择最新输入、启动消费者或创建收费任务。长批次超过现有准备租约时间会拒绝，由独立协调器明确续期并重做预检。

## 验证

测试使用明确合成资料。新模块未调用付费供应商，没有业务写入、数据库权限扩展、API 或前端装配。

| 验证范围 | 结果 |
| --- | --- |
| 新预检机制、既有准备协议和原完整材料／序列化器组合 | **93 项通过，24.05 秒，0 跳过** |
| Ruff 检查与格式 | 新实现及两份测试文件通过 |
| Mypy | 新实现通过 |
| Bandit | 新实现通过 |
| 原生 PostgreSQL 17.11／原件恢复专项 | **4 项通过，98.55 秒，0 跳过**；1 条既有 Starlette／AnyIO 弃用警告 |

新纯测试覆盖全部纳入规则、三槽完全相同字节、原 PDF 篡改、原生投影／图片替换、请求容量、当前事务拒绝、租约过期／中途撤销、证据 revision 改变、方法漂移、排除规则、重散列伪造权限和恢复期间撤销。原生测试另外覆盖真实非 owner RPC、完整恢复入口和序列化期间配置撤销。

原生专项在本轮隔离 PG17.11＋pgvector 0.8.7 中新建 `fusion_package_requirements_api`，沿用既有完整封存／续验／任务／准备租约链与独立 LOGIN。实际执行同租约全规则预检、三槽原请求字节比较、五连接原生恢复后预检、准备配置撤销与原件篡改拒绝。原件恢复使用真实回环 HTTP，前后及 I/O 边界五连接均 idle；上游受限派生为明确合成适配器，不宣称本轮运行过生产转换沙箱。测试结束后临时数据库与 `fusion_*` 测试 LOGIN 清理为空。

执行命令（管理员 DSN 由独立测试环境预先注入，不写入仓库）：

```sh
FUSION_MATERIAL_REQUEST_PREFLIGHT_PG=1 .venv/bin/python -m pytest -q tests/test_material_request_preflight_pg.py
```

开发中一次 93 项组合运行取得 92 通过／1 失败：测试执行期间为 Mypy 增加实现类型注解，末次方法核验准确拒绝变化。停止编辑并固定源码后重跑 93 项通过；没有放宽方法守卫。多规则测试初轮的合成 lease 未同步新输入摘要也被正确拒绝，修正合成夹具后通过。

## 尚未授予的能力

预检回执中的 `fee_ledger_reserved`、`send_lease_granted`、`execution_authorized`、`model_token_limit_verified`、`account_prices_verified`、`visual_readability_verified`、`atomic_snapshot_verified`、`formal_prediction_eligible` 均为 `false`。

完整请求字节通过不表示 token 容量、供应商账户价格或视觉可读性已证明。下一阶段仍需将固定请求接入独立费用预留、发送租约、实际 Worker 运输、原始响应持久化与费用核清；真实评分准确率、受控发布和生产验收另行记录。本阶段不安装可选数据库结构到普通业务库，不把模拟测试或源代码调用入口当作正式业务环境交付。
