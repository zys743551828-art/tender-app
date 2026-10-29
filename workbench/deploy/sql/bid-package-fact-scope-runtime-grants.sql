BEGIN;
REVOKE ALL ON design.bid_package_fact_scopes FROM PUBLIC,tender_api,tender_worker;
GRANT SELECT,INSERT ON design.bid_package_fact_scopes TO tender_api;
GRANT SELECT ON design.bid_package_fact_scopes TO tender_worker;
COMMIT;
