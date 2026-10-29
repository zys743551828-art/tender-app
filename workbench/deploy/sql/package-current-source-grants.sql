-- Optional initialization-only purpose grants. Not part of BASE or business repair.
BEGIN;
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='tender_current_source_verify') THEN
  CREATE ROLE tender_current_source_verify NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
 END IF;
 IF EXISTS(SELECT FROM pg_roles WHERE rolname='tender_current_source_verify' AND
  (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
 OR EXISTS(SELECT FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='tender_current_source_verify')) THEN
  RAISE EXCEPTION 'current_source_group_not_independent';
 END IF;
END $$;
GRANT USAGE ON SCHEMA design,retrieval TO tender_current_source_verify;
GRANT SELECT(id,bid_id,blob_id,artifact_kind) ON design.document_versions TO tender_current_source_verify;
GRANT SELECT(id,digest,byte_size,media_type) ON design.blobs TO tender_current_source_verify;
GRANT SELECT ON design.parse_runs,design.pages,design.evidence_blocks,
 retrieval.source_nodes,retrieval.source_heads,retrieval.lineage_edges TO tender_current_source_verify;
COMMIT;
