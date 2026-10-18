-- Word 原件、转换回执、实际 PDF 与采用决定分别追加保存。
CREATE TABLE word_conversions (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, source_version_id TEXT NOT NULL,
 job_id TEXT NOT NULL, attempt INTEGER NOT NULL CHECK(attempt>0),
 state TEXT NOT NULL CHECK(state IN ('converted','needs_review','failed')),
 report_json JSONB NOT NULL CHECK(jsonb_typeof(report_json)='object'),
 pdf_version_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(job_id,attempt), UNIQUE(id,project_id),
 FOREIGN KEY(source_version_id,project_id) REFERENCES file_versions(id,project_id),
 FOREIGN KEY(pdf_version_id,project_id) REFERENCES file_versions(id,project_id),
 FOREIGN KEY(job_id,project_id) REFERENCES jobs(id,project_id),
 CHECK((state='failed')=(pdf_version_id IS NULL))
);
CREATE TABLE word_pdf_links (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, source_version_id TEXT NOT NULL, pdf_version_id TEXT NOT NULL,
 method TEXT NOT NULL CHECK(method IN ('controlled_render','user_declared')),
 conversion_id TEXT, created_by TEXT REFERENCES members(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(pdf_version_id), UNIQUE(id,project_id,source_version_id,pdf_version_id),
 FOREIGN KEY(source_version_id,project_id) REFERENCES file_versions(id,project_id),
 FOREIGN KEY(pdf_version_id,project_id) REFERENCES file_versions(id,project_id),
 FOREIGN KEY(conversion_id,project_id) REFERENCES word_conversions(id,project_id),
 CHECK(source_version_id<>pdf_version_id), CHECK((method='controlled_render')=(conversion_id IS NOT NULL))
);
CREATE TABLE word_pdf_adoptions (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, source_version_id TEXT NOT NULL, pdf_version_id TEXT NOT NULL, link_id TEXT NOT NULL,
 actor_id TEXT REFERENCES members(id), reason TEXT NOT NULL CHECK(length(trim(reason))>0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 FOREIGN KEY(link_id,project_id,source_version_id,pdf_version_id) REFERENCES word_pdf_links(id,project_id,source_version_id,pdf_version_id)
);
CREATE INDEX idx_word_conversions_source ON word_conversions(source_version_id,created_at DESC,id DESC);
CREATE INDEX idx_word_adoptions_source ON word_pdf_adoptions(source_version_id,created_at DESC,id DESC);
ALTER TABLE upload_sessions ADD COLUMN source_word_version_id TEXT;
ALTER TABLE upload_sessions ADD FOREIGN KEY(source_word_version_id,project_id) REFERENCES file_versions(id,project_id);
ALTER TABLE input_snapshots ADD COLUMN word_sources_json JSONB NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(word_sources_json)='array');
CREATE TRIGGER immutable_word_conversions BEFORE UPDATE OR DELETE ON word_conversions FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_word_conversions_truncate BEFORE TRUNCATE ON word_conversions FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_word_pdf_links BEFORE UPDATE OR DELETE ON word_pdf_links FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_word_pdf_links_truncate BEFORE TRUNCATE ON word_pdf_links FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_word_pdf_adoptions BEFORE UPDATE OR DELETE ON word_pdf_adoptions FOR EACH ROW EXECUTE FUNCTION forbid_change();
CREATE TRIGGER immutable_word_pdf_adoptions_truncate BEFORE TRUNCATE ON word_pdf_adoptions FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
GRANT SELECT,INSERT ON word_conversions,word_pdf_links,word_pdf_adoptions TO app_api,app_worker;
GRANT INSERT ON files,file_versions TO app_worker;
