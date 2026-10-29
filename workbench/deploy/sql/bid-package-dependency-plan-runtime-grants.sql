BEGIN;
REVOKE ALL ON design.bid_package_dependency_plans FROM PUBLIC,tender_api,tender_worker;
GRANT SELECT,INSERT ON design.bid_package_dependency_plans TO tender_api;
GRANT SELECT ON design.bid_package_dependency_plans TO tender_worker;
COMMIT;
