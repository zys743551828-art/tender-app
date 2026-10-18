# 整包存储的受限运行账号

新空库顺序为 core、domain、bid-packages、retrieval、worker-functions、roles，再执行专项运行授权。包函数先于 roles 建立，由 roles 统一撤销 PUBLIC 的执行权；不将包脚本作为 roles 后的任意扩展运行。`bootstrap_fresh` 和 `initialize_database` 使用一致顺序，不能对原业务库热补。

API 继承既有 `tender_api` 能力，创建资料包并执行 canonical／源身份检查。不可变触发器仍拒绝修订、成员、逻辑部分和绑定的更新。包接口的项目成员授权、CSRF、幂等与当前身份重核由后续接口负责，表权限测试不代替这些检查。

解析 Worker 仅新增 `bid_package_parse_bindings` 的 SELECT：写原页或证据的冻结触发器需要读取它。Worker 不得创建包、修订、成员、部分、头或工程标段。未冻结解析允许正常追加原页；冻结后实际触发器拒绝追加。解析记录原有 append-only 约束保留。

`tests/test_bid_package_acl.py` 在显式 `FUSION_PACKAGE_ACL_DSN` 的 `fusion_package_acl` 临时库执行实际基础初始化顺序，创建独立非 owner API／Worker LOGIN。五项检查覆盖实际 API 保存／读取及不可变记录、Worker 包写入拒绝、未冻结与已冻结原页追加、PUBLIC 函数权限／SECURITY DEFINER、初始化顺序。没有调用模型、连接业务库或注册 HTTP 包接口；完整预算 SQL 不在本批执行范围。
