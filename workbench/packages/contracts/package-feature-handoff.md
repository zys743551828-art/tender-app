# 研究用私有特征交接 /1

`package-history-feature-handoff/1` 是本地文件协议，不是公开 HTTP、数据库原生登记、模型执行授权或训练协议。生产者复用 [整包特征 /2](package-technical-features.md)，不接受 `/3` 完整材料的隐式转换。

生产接口为现有 `deploy/package_history_worker.py` 的 `feature-freeze`；`feature-read` 返回无正文的复验回执，`package_feature_handoff.load` 返回复验后的独立数据副本。方法摘要绑定交接实现、既有特征方法和其依赖身份。软件方法变化后，旧文件保留但不能冒用当前方法读取。

封套字段固定为 `version`、`command_id`、`origin`、`purpose`、`projection_digest`、`binding_digest`、`feature_method_digest`、`handoff_method_digest`、`projection`、`result`、`training_eligible`、`metrics_eligible`、`formal_prediction_eligible`、`provider_requests`、`paid_calls`。`purpose=research_feature_handoff_only`；三个资格值恒 false，调用／费用恒 0。`origin` 只允许显式的 `synthetic_mechanism` 或 `unqualified_research`，该自述标签不证明真实性。

`projection` 和 `result` 分别保留原 `/2` 封闭输入和既有计算输出，不能插入官方标签、修补缺槽或重定义模型／条款身份。只有每条规则均具有三个有效槽位、完整特征时才发布交接；partial 保持原输入待处理，不生成可交接记录。`raw_numeric_total`、`formal_prediction` 仍为 null。所有训练、指标与正式预测资格仍不可用。

调用方必须另行提供预期投影摘要、完整 binding 摘要、特征方法摘要、交接方法摘要、command ID 和来源。重读还须提供原回执的文件摘要。预期值不得由收到的任意文件自算后当作原生权威。协议只核对这些显式冻结身份；当前在线范围、原始字节、真实供应商回执、视觉可读和数据准入仍由各自独立权威负责。

文件使用既有 canonical JSON：UTF-8、排序键、紧凑分隔符，无浮点、重复键或不安全整数。投影最多 16 MiB；整个交接最多 32 MiB。artifact 摘要是确切文件字节的 SHA-256，没有可自改后授予资格的内部摘要。重读除核对该摘要外，还重新计算特征、重建完整封套并比较确切字节，额外字段或篡改结果即使重算文件哈希仍拒绝。

在当前 UID 所有的既有 0700 目录中，以固定 command UUID 命名 0600 普通文件。原子无覆盖发布；同命令同字节幂等，不同字节冲突。私有目录与文件权限不会由读写操作自动放宽或修复，最终路径符号链接和非普通文件拒绝。并发、发布前失败、发布后 ACK 丢失均不能覆盖已有结果。文件对应用不可覆盖，不声称能阻止文件所有者手工修改；摘要和重算会发现不匹配。

此协议不授予任何新 SQL/ACL 权限。旧 native train/evaluate 模式明确拒绝特征文件参数，不能用本地文件绕过原有原生研究、标签隔离和暴露协议。
