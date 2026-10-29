-- 新空库包表在 roles.sql 前建立，PUBLIC 函数权限由该脚本统一撤销。
-- 解析 Worker 的冻结守卫仅需读取绑定，不能创建或改写资料包。
BEGIN;
REVOKE UPDATE ON design.engineering_lots FROM tender_api;
GRANT SELECT ON design.bid_package_parse_bindings TO tender_worker;
COMMIT;
