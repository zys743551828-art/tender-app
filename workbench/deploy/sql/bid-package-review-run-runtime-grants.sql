-- API creates immutable run commands. Only the worker publishes their derived results.
BEGIN;
REVOKE ALL ON design.bid_package_review_runs,design.bid_package_review_results FROM PUBLIC,tender_api,tender_worker;
GRANT SELECT,INSERT ON design.bid_package_review_runs TO tender_api;
GRANT SELECT ON design.bid_package_review_runs TO tender_worker;
GRANT SELECT ON design.bid_package_review_results TO tender_api;
GRANT SELECT,INSERT ON design.bid_package_review_results TO tender_worker;
REVOKE ALL ON design.bid_package_dependency_plan_command_receipts FROM PUBLIC,tender_api,tender_worker;
GRANT SELECT ON design.bid_package_dependency_plan_command_receipts TO tender_api,tender_worker;
GRANT EXECUTE ON FUNCTION design.bid_scope_review_execution_key(jsonb) TO tender_api;
GRANT SELECT ON design.bid_package_requirement_inventories,design.bid_package_requirements,
 design.bid_package_requirement_heads,design.bid_package_coverage_attempts,
 design.bid_package_coverage_results TO tender_worker;
GRANT SELECT ON design.bid_package_heads,design.bid_package_members,
 design.bidders,design.bid_rounds,design.engineering_projects TO tender_worker;
GRANT EXECUTE ON FUNCTION design.identity_snapshot_v2(uuid),design.identity_association_v2(uuid),
 design.bid_requirement_source_snapshot(uuid,uuid) TO tender_worker;
COMMIT;
