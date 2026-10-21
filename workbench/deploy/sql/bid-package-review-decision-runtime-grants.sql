-- Human opinions are API-only; a model worker cannot impersonate a reviewer.
BEGIN;
REVOKE ALL ON design.bid_package_review_decisions,design.bid_package_review_decision_heads
 FROM PUBLIC,tender_api,tender_worker;
GRANT SELECT,INSERT ON design.bid_package_review_decisions TO tender_api;
GRANT SELECT,INSERT ON design.bid_package_review_decision_heads TO tender_api;
GRANT UPDATE(decision_id,digest,sequence_no) ON design.bid_package_review_decision_heads TO tender_api;
COMMIT;
