-- Frozen input records are append-only; ordinary workers may read, never create.
BEGIN;
REVOKE UPDATE ON design.bid_package_review_inputs FROM tender_api;
GRANT SELECT ON design.bid_package_review_inputs TO tender_worker;
GRANT EXECUTE ON FUNCTION design.bid_review_fact_serial_guard() TO tender_worker;
COMMIT;
