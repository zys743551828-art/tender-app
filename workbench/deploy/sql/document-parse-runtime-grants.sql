BEGIN;
REVOKE ALL ON design.document_parse_requests,design.document_parse_results FROM PUBLIC,tender_api,tender_worker;
GRANT SELECT,INSERT ON design.document_parse_requests TO tender_api;
GRANT SELECT ON design.document_parse_results TO tender_api;
GRANT SELECT ON design.document_parse_requests TO tender_worker;
GRANT SELECT,INSERT ON design.document_parse_results TO tender_worker;
COMMIT;
