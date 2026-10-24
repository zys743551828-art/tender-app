# 当前原件的受限定位观察

`package_current_original.observe`使用明确的项目、scope ID及摘要、文档ID、原件摘要和预期方法摘要。它自行拥有repeatable-read／read-only事务；已有事务拒绝。独立LOGIN只继承`tender_current_original_verify`及`tender_current_scope_verify`，无业务表列读取、写入、CREATE、管理角色或其他SECURITY DEFINER权限。共用审计检查实际有效权限，过权拒绝，不切换角色或补权。

`deploy/sql/package-current-original-runtime.sql`是可选全新初始化SQL，依赖当前scope扩展，不入BASE。`current_technical_original.locate(uuid,uuid,text,uuid,text)`只允许上述新能力组执行，PUBLIC不可执行，search_path固定为pg_catalog／design／pg_temp。控制器先验证两项RPC的确切正文、语言、返回类型、执行模式、search_path及直接／继承owner分离，再调用原生入口。

入口首先复用当前scope检查，核对项目身份、阶段、目标及依据包head、清单和规则。原件必须恰好出现在原scope的登记文件清单，摘要及长度匹配实际blob，类型为source_original或bid_body。全部来源根由两包的准确文档及冻结解析重新计算；完整祖先闭包、原生来源类型／用途／项目／摘要、head修订／发布状态／有效期均与冻结值逐项比较。任何来源撤回、过期、未生效、缺失、额外祖先或闭包变化均拒绝，不改旧scope。

限制为32MiB原件、4096 UTF-8字节定位、20000来源节点／边／闭包行和64层；超限或循环拒绝，不截断。单条SQL限时5秒。读取是同次数据库快照，不是持续访问资格或发送租约。

`OriginalLocatorObservation`将对象key放在不参与repr的私有字段`locator`，只供受控读取进程消费。公开metadata含精确身份、长度、介质类型、来源快照摘要、观察时间、方法及两项原生正文摘要、locator的SHA-256及整体摘要；不含对象key、签名URL或正文。原生异常统一转为安全码并丢弃异常上下文。实现不加载业务环境、不创建连接、不发现凭据或生成签名URL。

只有`native_current_original_locator_checked=true`。原件字节、必要范围、输入权威、执行与历史存在性均不授予。后续现有`original_bytes`端口必须独立完整GET核对长度和SHA-256；该传输回执的`native_permission_verified`仍为false，两份观察不能自封正式binding。

本次授权只覆盖已有Compose检查组的全新独立库及合成对象，结束删除检查库、临时LOGIN和能力组；正常业务库、API／模型Worker账号、真实OSS凭据及真实标书读取不在安装范围。没有HTTP接口或前端变更。真实独立输入登记、必要范围、发送前CAS／lease及正式执行仍须分别实现和验收。
