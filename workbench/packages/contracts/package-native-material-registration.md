# 原生待核验材料登记

本协议保存恢复材料的不可变摘要引用与实际登记主体，不授予正式输入资格。职责由三层分开：原生恢复端口重新读取当前事实；私有命令存储固定待提交内容；独立登记 LOGIN 经窄 RPC 写入／读取待核验记录。没有公开 HTTP、业务 Worker 开关或正式模型调用。

`packet_for` 要求完整恢复 context、独立固定的 context／恢复清单摘要及一致的恢复观察引用。packet 闭合为 `version=package-native-material-registration-packet/1`，加八个非零 SHA-256 字段：`context_digest`、`context_method_digest`、`recovery_commit_digest`、`recovery_method_digest`、`recovery_observation_digest`、`source_observation_digest`、`material_digest`、`registration_method_digest`。它们仅引用材料、来源及方法，不包含正文、私有定位、密钥、标签或资格布尔。

`stage_command` 在首次数据库写入前，将规范 JSON 保存为私有 CAS 清单。闭合字段为 `version=package-material-registration-command/1`、`method_digest`、`bid_id`、`scope_id`、`scope_digest`、`command_id`、`packet`。调用方持有独立固定的命令清单摘要。命令最多 16 KiB，packet 最多 4 KiB。重启后按固定清单重放，不能用新一次原生重核产生的时间或观察摘要替换原 packet。

专用 NOLOGIN 组 `tender_material_registration` 及独立 LOGIN 只有专用 schema USAGE 和固定 RPC：`material_registration.record(uuid,uuid,text,uuid,jsonb)`、`material_registration.read(uuid,uuid,text)`。无登记表／业务表直接 SELECT、INSERT、UPDATE、DELETE、TRUNCATE、CREATE 或其他用途角色继承。两个实际函数的正文、语言、返回类型、owner 继承隔离、volatile 和固定 search_path 必须与受控源码一致。有效权限审计允许这两个固定入口，其中 record 是明确的写入口，不能据共用审计函数名称误称整个端口只读。

record 端口拥有 READ COMMITTED／READ WRITE 事务、五秒 statement_timeout；服务端核 packet 闭合及摘要字段、原冻结 scope 与项目／scope 摘要对应，按命令 UUID 锁定重放。相同实际 LOGIN、命令及完整请求返回同一记录；换主体或内容拒绝。登记 ID、记录时间、实际 session_user 与规范记录摘要由数据库生成。返回结构及绑定在事务提交前核验，非法结果回滚新插入。数据库提交结果不确定时，调用方可使用已保存命令与 packet 摘要查询或重放同一记录，无需重新读取原件。

read 端口拥有 REPEATABLE READ／READ ONLY 事务，只按准确项目、命令 UUID、独立固定的 packet 摘要读取同一实际 LOGIN 的记录；已知记录摘要可再固定核对。无列表、latest 或他人命令读取。旧记录可在项目关闭后查询／重放，表示原事实记录存在，不证明当前材料或提交时仍有资格。

记录 document 闭合为 `version=package-native-material-registration/1`、`registration_id`、`bid_id`、`scope_id`、`scope_digest`、`command_id`、`recorded_by`、`recorded_at`、`packet`、`status=awaiting_independent_verification`，及服务器固定 false 的 `native_binding_verified`、`necessary_scope_verified`、`input_authority_granted`、`execution_authorized`。record 文档最多 16 KiB，数据库禁止 UPDATE／DELETE。端口的 `native_record_identity_verified=true` 仅表示原生记录身份及摘要核对，不能升级为原生核验 binding。

原生 RPC 核对引用形状与已存 scope 对应；声明的摘要本身不证明恢复程序执行、内容权威、必要范围或当时存在。正常控制器先走实际原生恢复再固定命令，绕过该控制器提交的合成引用仍只能得到相同待核验状态。后续独立核验必须重新取得所指对象、验证当前范围及内容证据，追加新决定；不能修改此记录或把它直接转换为可执行 `/3` binding。

权限安装仅限显式全新独立检查库，见[权限边界](../../docs/completion-20261021/material-registration-permission-review.md)。可选 SQL 不进入 BASE 或正常业务库，不安装到现有业务角色。范围外：内容／必要范围审核决定、正向输入权威、正式 binding、发送租约、费用与正式 Worker、真实评分精度及视觉验收。
