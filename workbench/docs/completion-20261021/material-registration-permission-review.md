# 待核验材料登记权限边界

实现只在显式独立检查库的新初始化中安装 `deploy/sql/package-material-registration.sql`，不进入 BASE、正常业务库或完整运行配置。新增 `tender_material_registration` NOLOGIN 组与独立测试 LOGIN，不继承 API、Worker、来源、原件、scope、研究或 owner 角色。登记 LOGIN 只获得专用 schema USAGE 及两个固定 RPC EXECUTE，没有任何业务表或登记表直接 SELECT／DML、路径、bucket 或标签权限。

写 RPC 只将固定 context／恢复清单／观察／方法摘要引用保存为 `awaiting_independent_verification` 的不可变记录；读 RPC 只能按项目、准确命令 UUID、期望 packet 摘要读取同一实际 LOGIN 的记录。作用不是授予输入资格。`native_binding_verified`、`necessary_scope_verified`、`input_authority_granted`、`execution_authorized` 均由服务器固定 false，不接受请求布尔。引用形状及 SQL 中的冻结 scope 对应检查不能代替内容核验，记录也不证明发送时仍有效。

独立端口复用现有有效权限审计逻辑，只开放代码固定的一写一读 RPC；写事务明确由该端口拥有，不能把它当作只读观察端口。两函数的实际正文、owner 继承隔离、语言、返回类型和固定 search_path 都与受控源码核对。调用方不能借 owner 初始化修复权限，也不切角色。

登记前先将完整固定引用命令保存到私有 CAS；命令 UUID 按实际 LOGIN 和完整请求重放，相同命令不同内容拒绝。结果不确定时可只凭已保存命令查询／重放原记录，无需以新重核时点替换原 packet。实际数据库时间、随机记录 ID 与记录摘要由服务器产生；UPDATE／DELETE 有不可变触发器，调用角色无对应权限。登记表没有正文、私有原件、定位、签名 URL、密钥或官方标签。

测试只使用现有 tender-fusion Compose 检查组、专用数据库与合成材料。owner 只做新库初始化、测试夹具和受控权限反例；记录由独立 LOGIN 实际写读。结束清理数据库、新 LOGIN 与 NOLOGIN 组，停止检查服务，保留正常预览与业务 Word。正常业务库安装、真实资格登记、必要范围审核、正式评分执行及授予其他角色读取均在范围外。
