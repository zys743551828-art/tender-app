-- Explicit fresh-schema extension; no mutation of existing material/body pointers.
BEGIN;
SET search_path=design,public;
CREATE TABLE document_parse_requests (
 id uuid PRIMARY KEY,bid_id uuid NOT NULL,document_version_id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES members(id),command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 operation_id uuid NOT NULL UNIQUE,input_manifest jsonb NOT NULL,input_digest sha256 NOT NULL,
 reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 1000),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(bid_id,document_version_id) REFERENCES document_versions(bid_id,id),
 FOREIGN KEY(bid_id,operation_id) REFERENCES operations(bid_id,id),
 UNIQUE(bid_id,id,operation_id,document_version_id),
 CHECK(encode(sha256(convert_to(package_canonical_json(input_manifest),'UTF8')),'hex')=input_digest)
);
CREATE INDEX document_parse_directory ON document_parse_requests(bid_id,document_version_id,id);
CREATE INDEX document_parse_same_input ON document_parse_requests(bid_id,input_digest,created_at,id);
CREATE TABLE document_parse_results (
 request_id uuid PRIMARY KEY,bid_id uuid NOT NULL,operation_id uuid NOT NULL UNIQUE,
 document_version_id uuid NOT NULL,parse_run_id uuid NOT NULL UNIQUE,
 manifest jsonb NOT NULL,digest sha256 NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(bid_id,request_id,operation_id,document_version_id)
 REFERENCES document_parse_requests(bid_id,id,operation_id,document_version_id),
 FOREIGN KEY(bid_id,parse_run_id,document_version_id) REFERENCES parse_runs(bid_id,id,document_version_id),
 CHECK(encode(sha256(convert_to(package_canonical_json(manifest),'UTF8')),'hex')=digest)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON document_parse_requests
 FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON document_parse_results
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE FUNCTION document_parse_request_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE m jsonb; doc design.document_versions; blob design.blobs; version design.document_file_versions;
 file design.document_files; op design.operations; cmd design.commands; expected_payload jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'document_parse_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 m:=NEW.input_manifest;
 SELECT * INTO doc FROM design.document_versions WHERE bid_id=NEW.bid_id AND id=NEW.document_version_id;
 SELECT * INTO blob FROM design.blobs WHERE id=doc.blob_id;
 SELECT * INTO version FROM design.document_file_versions WHERE bid_id=NEW.bid_id AND version_id=doc.id;
 SELECT * INTO file FROM design.document_files WHERE bid_id=NEW.bid_id AND id=version.file_id;
 IF doc.id IS NULL OR file.id IS NULL OR blob.media_type<>'application/pdf' OR blob.byte_size NOT BETWEEN 1 AND 104857600
 OR doc.artifact_kind NOT IN('source_original','bid_body') OR file.role NOT IN('body','tender','supplement','drawing','boq')
 OR NOT design.package_json_keys(m,ARRAY['protocol','bid_id','document_version_id','document','qualification','source','method','current_body_changed','automatically_started_review','word_coverage_claimed'])
 OR m->>'protocol' IS DISTINCT FROM 'document-parse-context/1' OR m->>'bid_id' IS DISTINCT FROM NEW.bid_id::text
 OR m->>'document_version_id' IS DISTINCT FROM doc.id::text
 OR m->'document' IS DISTINCT FROM jsonb_build_object('sha256',blob.digest,'byte_size',blob.byte_size,'media_type',blob.media_type,
 'filename',doc.original_name,'file_id',file.id,'file_revision',version.revision,'role',file.role,'artifact_kind',doc.artifact_kind,
 'locator_digest',encode(sha256(convert_to(blob.object_key,'UTF8')),'hex'))
 OR m->'current_body_changed' IS DISTINCT FROM 'false'::jsonb OR m->'automatically_started_review' IS DISTINCT FROM 'false'::jsonb
 OR m->'word_coverage_claimed' IS DISTINCT FROM 'false'::jsonb
 OR NOT design.package_json_keys(m->'method',ARRAY['protocol','mode','parser_digest','config_digest','implementation_digest','max_bytes','max_pages'])
 OR m#>>'{method,protocol}' IS DISTINCT FROM 'document-parse-method/1'
 OR (m#>>'{method,mode}' IN('physical_text_only','configured_local')) IS NOT TRUE
 OR m#>'{method,max_bytes}' IS DISTINCT FROM '104857600'::jsonb OR m#>'{method,max_pages}' IS DISTINCT FROM '1000'::jsonb
 OR coalesce(m#>>'{method,parser_digest}','') !~ '^[a-f0-9]{64}$'
 OR coalesce(m#>>'{method,config_digest}','') !~ '^[a-f0-9]{64}$'
 OR coalesce(m#>>'{method,implementation_digest}','') !~ '^[a-f0-9]{64}$'
 OR NOT design.package_json_keys(m->'qualification',ARRAY['kind','identity_digest'])
 OR (m#>>'{qualification,kind}' IN('verified_upload','adopted_generated')) IS NOT TRUE
 OR coalesce(m#>>'{qualification,identity_digest}','') !~ '^[a-f0-9]{64}$'
 OR NOT design.package_json_keys(m->'source',ARRAY['root_id','state','authority_digest'])
 OR coalesce(m#>>'{source,root_id}','') !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
 OR (m#>>'{source,state}' IN('unregistered','published')) IS NOT TRUE
 OR coalesce(m#>>'{source,authority_digest}','') !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'document_parse_input_binding' USING ERRCODE='23514'; END IF;
 IF m#>>'{qualification,kind}'='verified_upload' AND (
 (SELECT count(*) FROM design.uploads u WHERE u.bid_id=NEW.bid_id AND u.verified_version_id=doc.id
 AND u.state='verified' AND u.role=file.role AND u.declared_digest=blob.digest AND u.declared_size=blob.byte_size)<>1
 OR NOT EXISTS(SELECT 1 FROM design.uploads u WHERE u.bid_id=NEW.bid_id AND u.verified_version_id=doc.id
 AND u.state='verified' AND u.role=file.role AND u.declared_digest=blob.digest AND u.declared_size=blob.byte_size
 AND m#>>'{qualification,identity_digest}'=encode(sha256(convert_to(design.package_canonical_json(
 jsonb_build_object('id',u.id,'role',u.role,'declared_digest',u.declared_digest,'declared_size',u.declared_size)),'UTF8')),'hex'))) THEN
  RAISE EXCEPTION 'document_parse_upload_qualification' USING ERRCODE='23514'; END IF;
 -- The application repeats the complete current authoring authority at capture
 -- and under the final graph lock. SQL also requires a real exact-file receipt;
 -- artifact_kind alone never substitutes for qualification.
 IF m#>>'{qualification,kind}'='adopted_generated' AND NOT EXISTS(
 SELECT 1 FROM design.build_outputs b JOIN design.audit_entries a ON a.bid_id=b.bid_id
 WHERE b.bid_id=NEW.bid_id AND b.document_version_id=doc.id AND b.format='pdf' AND b.state='succeeded'
 AND a.event_type='authoring.output_qualified' AND a.payload#>>'{proof,bid_id}'=NEW.bid_id::text
 AND a.payload#>>'{proof,build_id}'=b.build_id::text AND a.payload#>>'{proof,document_version_id}'=doc.id::text
 AND a.payload#>>'{proof,sha256}'=blob.digest AND a.payload#>'{proof,byte_size}'=to_jsonb(blob.byte_size)
 AND a.payload->>'proof_digest'=encode(sha256(convert_to(design.package_canonical_json(a.payload->'proof'),'UTF8')),'hex')) THEN
  RAISE EXCEPTION 'document_parse_generated_qualification' USING ERRCODE='23514'; END IF;
 IF (m#>>'{source,state}'='unregistered' AND (
 m#>>'{source,authority_digest}' IS DISTINCT FROM encode(sha256(convert_to('[]','UTF8')),'hex')
 OR EXISTS(SELECT 1 FROM retrieval.source_nodes n WHERE n.id=(m#>>'{source,root_id}')::uuid)))
 OR (m#>>'{source,state}'='published' AND NOT EXISTS(
 SELECT 1 FROM retrieval.source_nodes n JOIN retrieval.source_heads h ON h.source_id=n.id
 WHERE n.id=(m#>>'{source,root_id}')::uuid AND n.document_version_id=doc.id AND n.kind='document'
 AND n.policy_class='prebid_content' AND n.digest=blob.digest AND h.status='published')) THEN
  RAISE EXCEPTION 'document_parse_source_binding' USING ERRCODE='23514'; END IF;
 SELECT * INTO op FROM design.operations WHERE bid_id=NEW.bid_id AND id=NEW.operation_id;
 SELECT * INTO cmd FROM design.commands WHERE id=NEW.command_id;
 IF op.id IS NULL OR op.command_id IS DISTINCT FROM NEW.command_id OR op.kind IS DISTINCT FROM 'parse-document'
 OR op.handler_version IS DISTINCT FROM 'document-parse/1' OR op.state IS DISTINCT FROM 'queued' OR op.input_digest IS DISTINCT FROM NEW.input_digest
 OR (SELECT count(*) FROM design.operation_steps WHERE operation_id=op.id)<>1
 OR NOT EXISTS(SELECT 1 FROM design.operation_steps s WHERE s.operation_id=op.id AND s.step_key='parse-document'
 AND s.handler_version=op.handler_version AND s.input_digest=op.input_digest AND s.required AND cardinality(s.depends_on)=0)
 OR NOT EXISTS(SELECT 1 FROM design.outbox x WHERE x.operation_id=op.id AND x.topic='tender.task.document.v1'
 AND x.payload->>'payload_ref'=NEW.id::text AND x.payload->>'step_key'='parse-document'
 AND x.payload->>'handler_version'='document-parse/1' AND x.payload->>'input_digest'=NEW.input_digest) THEN
  RAISE EXCEPTION 'document_parse_atomic_job' USING ERRCODE='23514'; END IF;
 IF cmd.id IS NULL OR cmd.actor_id IS DISTINCT FROM NEW.actor_id OR cmd.command_kind IS DISTINCT FROM 'document-parse-start'
 OR cmd.target_id IS DISTINCT FROM NEW.document_version_id
 OR cmd.request_digest IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(jsonb_build_object('body',
 jsonb_build_object('bid_id',NEW.bid_id,'context_digest',NEW.input_digest,'reason',NEW.reason),'if_match',NULL)),'UTF8')),'hex')
 OR cmd.response->>'status' IS DISTINCT FROM '202' OR cmd.response#>>'{body,protocol}' IS DISTINCT FROM 'document-parse-start/1'
 OR cmd.response#>>'{body,actor_id}' IS DISTINCT FROM NEW.actor_id::text
 OR cmd.response#>>'{body,command_id}' IS DISTINCT FROM NEW.command_id::text
 OR cmd.response#>>'{body,request_digest}' IS DISTINCT FROM cmd.request_digest
 OR cmd.response#>'{body,reused}' IS DISTINCT FROM 'false'::jsonb
 OR cmd.response#>>'{body,request,id}' IS DISTINCT FROM NEW.id::text
 OR cmd.response#>>'{body,request,bid_id}' IS DISTINCT FROM NEW.bid_id::text
 OR cmd.response#>>'{body,request,document_version_id}' IS DISTINCT FROM NEW.document_version_id::text
 OR cmd.response#>'{body,request,context}' IS DISTINCT FROM m
 OR cmd.response#>>'{body,request,context_digest}' IS DISTINCT FROM NEW.input_digest
 OR cmd.response#>>'{body,request,operation,id}' IS DISTINCT FROM NEW.operation_id::text THEN
  RAISE EXCEPTION 'document_parse_command_ack' USING ERRCODE='23514'; END IF;
 expected_payload:=jsonb_build_object('request_id',NEW.id,'document_version_id',NEW.document_version_id,'operation_id',NEW.operation_id,'context_digest',NEW.input_digest);
 IF NOT EXISTS(SELECT 1 FROM design.audit_entries a WHERE a.bid_id=NEW.bid_id AND a.actor_id=NEW.actor_id
 AND a.command_id=NEW.command_id AND a.event_type='document.parse_requested' AND a.payload=expected_payload) THEN
  RAISE EXCEPTION 'document_parse_audit' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER document_parse_request_complete AFTER INSERT ON document_parse_requests
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION document_parse_request_guard();

CREATE FUNCTION document_parse_result_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE r design.document_parse_requests;p design.parse_runs;m jsonb;output jsonb;pages_count bigint;evidence_count bigint;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'document_parse_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 SELECT * INTO r FROM design.document_parse_requests WHERE id=NEW.request_id AND bid_id=NEW.bid_id AND operation_id=NEW.operation_id;
 SELECT * INTO p FROM design.parse_runs WHERE id=NEW.parse_run_id AND bid_id=NEW.bid_id AND document_version_id=NEW.document_version_id;
 m:=NEW.manifest;
 SELECT count(*) INTO pages_count FROM design.pages WHERE bid_id=NEW.bid_id AND parse_id=p.id;
 SELECT count(*) INTO evidence_count FROM design.evidence_blocks WHERE bid_id=NEW.bid_id AND parse_id=p.id;
 IF r.id IS NULL OR p.id IS NULL OR NOT design.package_json_keys(m,ARRAY['parse_run_id','document_version_id','source_digest','parser_digest','config_digest','parsed_digest','coverage','page_count','evidence_count','gaps','gap_count','word_coverage_claimed'])
 OR m->>'parse_run_id' IS DISTINCT FROM p.id::text OR m->>'document_version_id' IS DISTINCT FROM p.document_version_id::text
 OR m->>'source_digest' IS DISTINCT FROM r.input_manifest#>>'{document,sha256}'
 OR m->>'parser_digest' IS DISTINCT FROM p.parser_digest OR p.parser_digest IS DISTINCT FROM r.input_manifest#>>'{method,parser_digest}'
 OR m->>'config_digest' IS DISTINCT FROM p.config_digest OR p.config_digest IS DISTINCT FROM r.input_manifest#>>'{method,config_digest}'
 OR m->>'coverage' IS DISTINCT FROM p.coverage OR m->'page_count' IS DISTINCT FROM to_jsonb(p.page_count)
 OR p.page_count<>pages_count OR m->'evidence_count' IS DISTINCT FROM to_jsonb(evidence_count)
 OR coalesce(m->>'parsed_digest','') !~ '^[a-f0-9]{64}$'
 OR m->'word_coverage_claimed' IS DISTINCT FROM 'false'::jsonb
 OR m->'gap_count' IS DISTINCT FROM to_jsonb(jsonb_array_length(p.gaps))
 OR jsonb_typeof(m->'gaps') IS DISTINCT FROM 'array' OR jsonb_array_length(m->'gaps')>100
 OR (r.input_manifest#>>'{method,mode}'='physical_text_only' AND p.coverage='complete')
 OR EXISTS(SELECT 1 FROM design.pages g WHERE g.parse_id=p.id AND g.physical_page>p.page_count)
 OR EXISTS(SELECT 1 FROM design.evidence_blocks e WHERE e.parse_id=p.id AND e.digest<>encode(sha256(convert_to(e.text_content,'UTF8')),'hex'))
 OR (p.coverage='complete' AND (p.page_count<1 OR p.gaps<>'[]'::jsonb OR EXISTS(SELECT 1 FROM design.pages g WHERE g.parse_id=p.id AND (g.quality<>'usable' OR g.gaps<>'[]'::jsonb))))
 OR NOT EXISTS(SELECT 1 FROM design.operations o WHERE o.id=NEW.operation_id AND o.bid_id=NEW.bid_id
 AND o.state='succeeded' AND o.kind='parse-document' AND o.handler_version='document-parse/1' AND o.input_digest=r.input_digest) THEN
  RAISE EXCEPTION 'document_parse_result_binding' USING ERRCODE='23514'; END IF;
 SELECT s.output INTO output FROM design.step_receipts s WHERE s.operation_id=NEW.operation_id AND s.step_key='parse-document'
 AND s.input_digest=r.input_digest AND s.state='succeeded';
 IF output IS NULL OR output->>'request_id' IS DISTINCT FROM NEW.request_id::text
 OR output->>'document_version_id' IS DISTINCT FROM NEW.document_version_id::text
 OR output->>'parse_run_id' IS DISTINCT FROM NEW.parse_run_id::text OR output->>'result_digest' IS DISTINCT FROM NEW.digest
 OR output->'current_body_changed' IS DISTINCT FROM 'false'::jsonb OR output->'automatically_started_review' IS DISTINCT FROM 'false'::jsonb
 OR NOT EXISTS(SELECT 1 FROM design.effect_receipts e WHERE e.operation_id=NEW.operation_id AND e.effect_key='parse-document' AND e.result=output) THEN
  RAISE EXCEPTION 'document_parse_fenced_receipt' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER document_parse_result_complete AFTER INSERT ON document_parse_results
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION document_parse_result_guard();

-- A completed parse is already an immutable output even before a package selects
-- it. Serialize appenders with the parse row so a concurrent publisher cannot
-- leave a successful result receipt referring to a different evidence set.
CREATE FUNCTION document_parse_content_insert_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'document_parse_content_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM id FROM design.parse_runs WHERE id=NEW.parse_id AND bid_id=NEW.bid_id FOR UPDATE;
 IF EXISTS(SELECT 1 FROM design.document_parse_results WHERE parse_run_id=NEW.parse_id AND bid_id=NEW.bid_id) THEN
  RAISE EXCEPTION 'document_parse_output_closed' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER document_parse_pages_closed BEFORE INSERT ON pages
 FOR EACH ROW EXECUTE FUNCTION document_parse_content_insert_guard();
CREATE TRIGGER document_parse_evidence_closed BEFORE INSERT ON evidence_blocks
 FOR EACH ROW EXECUTE FUNCTION document_parse_content_insert_guard();
CREATE FUNCTION document_parse_result_lock() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
BEGIN
 PERFORM id FROM design.parse_runs WHERE id=NEW.parse_run_id AND bid_id=NEW.bid_id FOR UPDATE;
 RETURN NEW;
END $$;
CREATE TRIGGER document_parse_close_output BEFORE INSERT ON document_parse_results
 FOR EACH ROW EXECUTE FUNCTION document_parse_result_lock();
REVOKE ALL ON FUNCTION document_parse_request_guard(),document_parse_result_guard(),
 document_parse_content_insert_guard(),document_parse_result_lock() FROM PUBLIC;
COMMIT;
