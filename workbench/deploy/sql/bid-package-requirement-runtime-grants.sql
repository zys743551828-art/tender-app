-- roles.sql grants base API writes in bulk; frozen requirement history is append-only.
BEGIN;
REVOKE UPDATE ON design.bid_package_requirement_inventories,
 design.bid_package_requirements,
 design.bid_package_coverage_attempts,
 design.bid_package_coverage_results FROM tender_api;
REVOKE INSERT,UPDATE ON design.bid_package_requirement_extraction_runs FROM tender_api;
GRANT SELECT ON design.bid_package_requirement_extraction_runs TO tender_api,tender_worker;
GRANT INSERT ON design.bid_package_requirement_extraction_runs TO tender_worker;
GRANT SELECT ON design.bid_packages,design.bid_package_revisions TO tender_worker;
GRANT EXECUTE ON FUNCTION design.package_canonical_json(jsonb),
 design.package_json_keys(jsonb,text[]) TO tender_worker;
-- Only bid_package_requirement_heads may advance through its CAS/identity trigger.
-- Worker may append exact extraction receipts and read frozen package identity;
-- it cannot create or revise packages. Scoring/research privileges stay unchanged.
COMMIT;
