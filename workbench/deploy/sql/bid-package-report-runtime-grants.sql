BEGIN;
REVOKE ALL ON design.bid_package_report_exports,design.bid_package_report_artifacts
 FROM PUBLIC,tender_api,tender_worker;
GRANT SELECT,INSERT ON design.bid_package_report_exports TO tender_api;
GRANT SELECT ON design.bid_package_report_artifacts TO tender_api;
GRANT SELECT ON design.bid_package_report_exports TO tender_worker;
GRANT SELECT,INSERT ON design.bid_package_report_artifacts TO tender_worker;
-- Human tables remain inaccessible to Worker. Only the API-frozen report snapshot is readable.
COMMIT;
