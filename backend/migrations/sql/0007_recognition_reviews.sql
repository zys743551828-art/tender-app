ALTER TABLE parses ADD CONSTRAINT parses_identity_project_file UNIQUE(id,project_id,file_version_id);
ALTER TABLE evidence ADD CONSTRAINT evidence_identity_project_file_parse UNIQUE(id,project_id,file_version_id,parse_id);
CREATE TABLE recognition_reviews (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, file_version_id TEXT NOT NULL,
 parent_parse_id TEXT NOT NULL, result_parse_id TEXT NOT NULL UNIQUE,
 source_evidence_id TEXT NOT NULL, result_evidence_id TEXT NOT NULL,
 decision TEXT NOT NULL CHECK(decision IN ('accept','correct','reject')),
 reason TEXT NOT NULL CHECK(length(trim(reason))>0), actor_id TEXT NOT NULL REFERENCES members(id),
 reviewed_original BOOLEAN NOT NULL CHECK(reviewed_original), reviewed_numbers BOOLEAN NOT NULL,
 evidence_map_json JSONB NOT NULL CHECK(jsonb_typeof(evidence_map_json)='object'), created_at TIMESTAMPTZ NOT NULL,
 CHECK(parent_parse_id<>result_parse_id), CHECK(source_evidence_id<>result_evidence_id),
 FOREIGN KEY(parent_parse_id,project_id,file_version_id) REFERENCES parses(id,project_id,file_version_id),
 FOREIGN KEY(result_parse_id,project_id,file_version_id) REFERENCES parses(id,project_id,file_version_id),
 FOREIGN KEY(source_evidence_id,project_id,file_version_id,parent_parse_id) REFERENCES evidence(id,project_id,file_version_id,parse_id),
 FOREIGN KEY(result_evidence_id,project_id,file_version_id,result_parse_id) REFERENCES evidence(id,project_id,file_version_id,parse_id)
);
CREATE INDEX recognition_reviews_file ON recognition_reviews(file_version_id,created_at DESC,id DESC);
CREATE TRIGGER immutable_recognition_reviews BEFORE UPDATE OR DELETE ON recognition_reviews FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_recognition_reviews_truncate BEFORE TRUNCATE ON recognition_reviews FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
GRANT SELECT,INSERT ON recognition_reviews TO app_api;
GRANT SELECT ON recognition_reviews TO app_worker;
