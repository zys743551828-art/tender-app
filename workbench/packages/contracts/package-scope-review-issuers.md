# 独立审核主体原生声明

`package_scope_review_issuers.py` 只认证已配置主体对准确报告所作的声明，并提供独立读取，不负责来源重取、内容语义、正向输入或发送许可。`package_material_scope_findings.py` 校验完整声明与证据，`package_scope_findings_store.py` 持久化私有结论；主体与任务配置由可选初始化 SQL 管理，运行时不得创建账号、切换角色或修复授权。

两类独立非 owner LOGIN 分别且仅继承 `tender_scope_review_issuer`、`tender_scope_review_verify` NOLOGIN 组。前者仅可调用 `scope_review_issuer.attest(uuid,uuid,jsonb)`，后者仅可调用 `scope_review_issuer.read(uuid,uuid,text)`；无表／列／序列权限、schema／数据库 CREATE 或其他业务 SECURITY DEFINER 入口。内部 `role_policy` 无 PUBLIC 或运行主体 EXECUTE。递归有效授权在原生 RPC 内再核对，不能绕过 Python 直接放宽身份。Python 另核实际三个函数正文、owner、语言、执行方式、固定 search_path／UTC，owner 须与配置表及 schema 相同。

不可变 profile 固定 LOGIN、主体 UUID、来源类型（human／controlled_program／external_receipt）、来源模式（synthetic_mechanism／current_prebid）、权限政策摘要、报告及存储方法、数据库名称／OID、有效期。可撤销 profile head 保存当前配置和版本。不可变 case 固定 profile、待核验材料登记 ID／摘要、准确 context／review 摘要和有效期，另有可撤销 case head。所有配置由初始化 owner 提供，请求不能自选身份、来源模式或资格。来源类型描述配置，不代替实际人工阅读、外部密码学签名或平台认证。当前仅配置合成测试主体。

`stage_command` 从完整清单和私有清单固定摘要重读、复验全部结论，先保存准确命令到私有 CAS。命令固定 case、command、bid、scope 与引用；引用字段闭合为版本和六份摘要：context、review、findings、findings_commit、findings_method、findings_store_method。`attest` 只接收已保存命令，使用调用连接的实际 session_user、原生 UUID 和时间；先核全部配置及准确材料登记，再保存不可变回执。profile／case 摘要用固定 UTC 的原生规范 JSON 计算，跨会话时区不改变身份。

写入口要求空闲连接并自行拥有 READ COMMITTED／READ WRITE 事务、5 秒语句超时；读取要求空闲连接并自行拥有 REPEATABLE READ／READ ONLY 事务。结果校验发生在提交前，无效结果回滚。相同命令采用事务 advisory lock，准确重放只返回原回执；同命令不同主体／任务／引用冲突。写结果不确定时，独立读取者以 bid、command、引用摘要查回，可另固定回执摘要，无须先知道随机回执 ID。

读取保留原 profile／case／回执，另外返回当前配置和任务是否启用、有效期、head 版本、当前观察时间。撤销、替换或越权不重写旧事实；旧命令可重放，新的命令须重新通过配置检查。当前状态是一次观察，不能作为跨事务有效性租约，也不表示已复核业务当前来源。源文件或解析变化仍须由来源端口核对，执行前还须有独立屏障。

`native_issuer_record_identity_verified` 或 `configured_issuer_identity_verified` 只说明经独立原生连接验证了记录或配置主体。`current_business_sources_rechecked`、`necessary_scope_verified`、`native_binding_verified`、`input_authority_granted`、`execution_authorized` 固定 false。身份真实不等于声明内容正确；全部确认的合成报告不能进入真实正式评分。

可选 SQL 只初始化全新独立检查库，不加入 BASE 或正常业务库；测试结束清理数据库、独立 LOGIN 和六类核验组。该端口无 HTTP／UI、模型调用、费用或执行副作用，生产主体配置、真正内容审核、外部签名校验、正向资格和 Worker 尚待后续完成。
