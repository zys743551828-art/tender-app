BEGIN;
REVOKE ALL ON design.bid_package_execution_inputs FROM PUBLIC,tender_api,tender_worker;
GRANT SELECT,INSERT ON design.bid_package_execution_inputs TO tender_api;
GRANT SELECT ON design.bid_package_execution_inputs TO tender_worker;
COMMIT;
