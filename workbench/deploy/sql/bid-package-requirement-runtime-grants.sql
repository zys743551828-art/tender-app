-- roles.sql grants base API writes in bulk; frozen requirement history is append-only.
BEGIN;
REVOKE UPDATE ON design.bid_package_requirement_inventories,
 design.bid_package_requirements,
 design.bid_package_coverage_attempts,
 design.bid_package_coverage_results FROM tender_api;
-- Only bid_package_requirement_heads may advance through its CAS/identity trigger.
-- No additional Worker, scoring or research capabilities are introduced here.
COMMIT;
