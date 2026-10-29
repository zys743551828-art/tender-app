-- Fresh additive Word -> Rich candidate extension. Optional Word intake is
-- checked at use time; BASE_SQL remains installable before that capability.
BEGIN;
SET search_path=design,public;

CREATE TABLE authoring_word_imports (
 id uuid PRIMARY KEY, bid_id uuid NOT NULL, draft_id uuid NOT NULL,
 source_document_version_id uuid NOT NULL,
 base_draft_revision bigint NOT NULL CHECK(base_draft_revision>0),
 base_snapshot_id uuid NOT NULL,
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 created_by uuid NOT NULL REFERENCES members(id),
 manifest jsonb NOT NULL CHECK(jsonb_typeof(manifest)='object'),
 digest sha256 NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(bid_id,draft_id) REFERENCES drafts(bid_id,id),
 FOREIGN KEY(bid_id,source_document_version_id) REFERENCES document_versions(bid_id,id),
 FOREIGN KEY(bid_id,draft_id,base_snapshot_id) REFERENCES draft_snapshots(bid_id,draft_id,id),
 UNIQUE(bid_id,draft_id,id),
 CHECK(octet_length(convert_to(package_canonical_json(manifest),'UTF8'))<=16777216),
 CHECK(encode(sha256(convert_to(package_canonical_json(manifest),'UTF8')),'hex')=digest)
);
CREATE INDEX authoring_word_import_history ON authoring_word_imports(bid_id,draft_id,created_at DESC,id DESC);

CREATE TABLE authoring_word_import_resolutions (
 candidate_id uuid PRIMARY KEY,bid_id uuid NOT NULL,draft_id uuid NOT NULL,
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 resolved_by uuid NOT NULL REFERENCES members(id),
 decision text NOT NULL CHECK(decision IN('append','reject')),
 result jsonb NOT NULL CHECK(jsonb_typeof(result)='object'),
 digest sha256 NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(bid_id,draft_id,candidate_id) REFERENCES authoring_word_imports(bid_id,draft_id,id),
 CHECK(encode(sha256(convert_to(package_canonical_json(result),'UTF8')),'hex')=digest)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON authoring_word_imports
 FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON authoring_word_import_resolutions
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE FUNCTION authoring_word_import_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE m jsonb; body jsonb; binding jsonb; expected_digest text; cmd design.commands;
 doc design.document_versions; blob design.blobs; snapshot design.draft_snapshots;
 receipt record; expected_source jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'word_import_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 m:=NEW.manifest;
 IF NOT design.package_json_keys(m,ARRAY['protocol','candidate_id','bid_id','draft_id','source_context',
 'target','method_digest','parsed','sections','staged_images','reason','preparation'])
 OR m->>'protocol' IS DISTINCT FROM 'authoring-word-import-candidate/1'
 OR m->>'candidate_id' IS DISTINCT FROM NEW.id::text
 OR m->>'bid_id' IS DISTINCT FROM NEW.bid_id::text
 OR m->>'draft_id' IS DISTINCT FROM NEW.draft_id::text
 OR m#>>'{source_context,source,document_version_id}' IS DISTINCT FROM NEW.source_document_version_id::text
 OR m#>'{target,base_draft_revision}' IS DISTINCT FROM to_jsonb(NEW.base_draft_revision)
 OR m#>>'{target,base_snapshot_id}' IS DISTINCT FROM NEW.base_snapshot_id::text
 OR jsonb_typeof(m->'sections') IS DISTINCT FROM 'array'
 OR jsonb_typeof(m->'staged_images') IS DISTINCT FROM 'array'
 OR jsonb_array_length(m->'sections')>500 OR jsonb_array_length(m->'staged_images')>200
 OR jsonb_typeof(m#>'{parsed,issues}') IS DISTINCT FROM 'array'
 OR m#>>'{parsed,protocol}' IS DISTINCT FROM 'authoring-docx-import/1'
 OR m->>'method_digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(m#>'{parsed,method}'),'UTF8')),'hex')
 OR m#>>'{parsed,source_digest}' IS DISTINCT FROM m#>>'{source_context,source,digest}'
 OR m#>'{parsed,source_byte_size}' IS DISTINCT FROM m#>'{source_context,source,byte_size}'
 OR jsonb_typeof(m#>'{parsed,can_apply}') IS DISTINCT FROM 'boolean'
 OR coalesce(m#>>'{target,before_digest}','') !~ '^[a-f0-9]{64}$'
 OR jsonb_typeof(m->'reason') IS DISTINCT FROM 'string'
 OR length(btrim(m->>'reason')) NOT BETWEEN 1 AND 1000 THEN
  RAISE EXCEPTION 'word_import_candidate_binding' USING ERRCODE='23514'; END IF;
 SELECT * INTO snapshot FROM design.draft_snapshots WHERE id=NEW.base_snapshot_id
 AND bid_id=NEW.bid_id AND draft_id=NEW.draft_id AND revision=NEW.base_draft_revision;
 IF snapshot.id IS NULL OR NOT EXISTS(SELECT 1 FROM design.drafts d WHERE d.id=NEW.draft_id
 AND d.bid_id=NEW.bid_id AND d.revision=NEW.base_draft_revision) THEN
  RAISE EXCEPTION 'word_import_target_changed' USING ERRCODE='23514'; END IF;
 SELECT * INTO doc FROM design.document_versions WHERE id=NEW.source_document_version_id AND bid_id=NEW.bid_id;
 SELECT * INTO blob FROM design.blobs WHERE id=doc.blob_id;
 IF doc.id IS NULL OR blob.media_type IS DISTINCT FROM 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
 OR blob.byte_size NOT BETWEEN 1 AND 33554432 OR doc.artifact_kind NOT IN('source_original','bid_body')
 OR doc.obtained_at>clock_timestamp() OR EXISTS(SELECT 1 FROM design.material_assignments a
 WHERE a.bid_id=NEW.bid_id AND a.document_version_id=doc.id AND a.role='official_result') THEN
  RAISE EXCEPTION 'word_import_original_scope' USING ERRCODE='23514'; END IF;
 IF to_regclass('design.word_intake_receipts') IS NULL THEN
  RAISE EXCEPTION 'word_import_intake_not_installed' USING ERRCODE='23514'; END IF;
 -- No optional table row type or FK is required at CREATE time. The immutable
 -- received original may still await normal file adoption / PDF conversion.
 SELECT w.upload_id,w.verify_operation_id,w.inspection_digest,w.inspection_report,
 u.role,u.state,u.verified_version_id,u.declared_digest,u.declared_size,
 coalesce(fv.file_id,x.file_id) AS file_id,coalesce(fv.revision,x.expected_file_revision) AS file_revision,
 x.id AS binding_id,f.role AS file_role INTO receipt
 FROM design.word_intake_receipts w JOIN design.uploads u ON u.bid_id=w.bid_id AND u.id=w.upload_id
 JOIN design.upload_transfers t ON t.bid_id=u.bid_id AND t.upload_id=u.id
 JOIN design.upload_bindings x ON x.id=t.current_binding_id AND x.bid_id=u.bid_id AND x.upload_id=u.id
 LEFT JOIN design.document_file_versions fv ON fv.bid_id=w.bid_id AND fv.version_id=w.document_version_id
 JOIN design.document_files f ON f.bid_id=w.bid_id AND f.id=coalesce(fv.file_id,x.file_id)
 WHERE w.bid_id=NEW.bid_id AND w.document_version_id=doc.id;
 IF receipt.upload_id IS NULL OR receipt.state IS DISTINCT FROM 'verified'
 OR receipt.verified_version_id IS DISTINCT FROM doc.id OR receipt.declared_digest IS DISTINCT FROM blob.digest
 OR receipt.declared_size IS DISTINCT FROM blob.byte_size OR receipt.role NOT IN('body','tender','supplement','drawing','boq')
 OR receipt.file_role IS DISTINCT FROM receipt.role
 OR receipt.inspection_report->>'schema' IS DISTINCT FROM 'word-intake-inspection/1'
 OR receipt.inspection_digest IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(receipt.inspection_report),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'word_import_received_identity' USING ERRCODE='23514'; END IF;
 expected_source:=jsonb_build_object('document_version_id',doc.id,'digest',blob.digest,'byte_size',blob.byte_size,
 'media_type',blob.media_type,'filename',doc.original_name,'role',receipt.role,'file_id',receipt.file_id,
 'file_revision',receipt.file_revision,'intake_digest',receipt.inspection_digest);
 IF m#>'{source_context,source}' IS DISTINCT FROM expected_source
 OR m#>'{source_context,receipt}' IS DISTINCT FROM jsonb_build_object('upload_id',receipt.upload_id,
 'verify_operation_id',receipt.verify_operation_id,'inspection_digest',receipt.inspection_digest,'binding_id',receipt.binding_id)
 OR m#>>'{source_context,locator_digest}' IS DISTINCT FROM encode(sha256(convert_to(blob.object_key,'UTF8')),'hex')
 OR NOT EXISTS(SELECT 1 FROM retrieval.source_nodes n JOIN retrieval.source_heads h ON h.source_id=n.id
 WHERE n.id=(m#>>'{source_context,source_id}')::uuid AND n.document_version_id=doc.id AND n.kind='document'
 AND n.digest=blob.digest AND n.policy_class='prebid_content' AND n.known_at=doc.obtained_at
 AND h.status='published' AND h.valid_from<=clock_timestamp() AND (h.valid_until IS NULL OR h.valid_until>clock_timestamp())) THEN
  RAISE EXCEPTION 'word_import_source_proof' USING ERRCODE='23514'; END IF;
 binding:=m->'preparation';
 body:=jsonb_build_object('source_document_version_id',doc.id,'source_digest',blob.digest,'source_byte_size',blob.byte_size,
 'base_draft_revision',NEW.base_draft_revision,'method_digest',m->'method_digest','reason',m->'reason');
 expected_digest:=encode(sha256(convert_to(design.package_canonical_json(jsonb_build_object('body',
 body||jsonb_build_object('bid_id',NEW.bid_id,'draft_id',NEW.draft_id),'if_match',binding->'if_match')),'UTF8')),'hex');
 SELECT * INTO cmd FROM design.commands WHERE id=NEW.command_id;
 IF NOT design.package_json_keys(binding,ARRAY['command_id','actor_id','idempotency_key','request_digest','request','if_match'])
 OR binding->>'command_id' IS DISTINCT FROM NEW.command_id::text
 OR binding->>'actor_id' IS DISTINCT FROM NEW.created_by::text OR binding->'request' IS DISTINCT FROM body
 OR binding->>'if_match' IS DISTINCT FROM ('"draft:'||NEW.draft_id::text||':'||NEW.base_draft_revision::text||'"')
 OR cmd.id IS NULL OR cmd.actor_id IS DISTINCT FROM NEW.created_by OR cmd.command_kind IS DISTINCT FROM 'prepare-authoring-word-import'
 OR cmd.target_id IS DISTINCT FROM NEW.draft_id OR cmd.idempotency_key IS DISTINCT FROM binding->>'idempotency_key'
 OR cmd.request_digest IS DISTINCT FROM expected_digest OR binding->>'request_digest' IS DISTINCT FROM expected_digest
 OR cmd.response->>'status' IS DISTINCT FROM '201'
 OR cmd.response#>>'{body,candidate_id}' IS DISTINCT FROM NEW.id::text
 OR cmd.response#>>'{body,candidate_digest}' IS DISTINCT FROM NEW.digest
 OR cmd.response#>>'{body,bid_id}' IS DISTINCT FROM NEW.bid_id::text
 OR cmd.response#>>'{body,draft_id}' IS DISTINCT FROM NEW.draft_id::text
 OR cmd.response#>'{body,preparation}' IS DISTINCT FROM binding THEN
  RAISE EXCEPTION 'word_import_prepare_ack' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM design.audit_entries a WHERE a.command_id=NEW.command_id
 AND a.actor_id=NEW.created_by AND a.bid_id=NEW.bid_id AND a.event_type='authoring.word_import_candidate_created'
 AND a.payload=jsonb_build_object('candidate_id',NEW.id,'draft_id',NEW.draft_id,'candidate_digest',NEW.digest)) THEN
  RAISE EXCEPTION 'word_import_prepare_audit' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER authoring_word_import_complete AFTER INSERT ON authoring_word_imports
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_word_import_guard();

CREATE FUNCTION authoring_word_import_resolution_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE candidate design.authoring_word_imports; cmd design.commands; snapshot design.draft_snapshots;
 r jsonb; binding jsonb; body jsonb; expected_digest text; section_ids jsonb; warnings jsonb; acknowledged jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'word_import_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 SELECT * INTO candidate FROM design.authoring_word_imports WHERE id=NEW.candidate_id
 AND bid_id=NEW.bid_id AND draft_id=NEW.draft_id;
 r:=NEW.result;binding:=r->'command';body:=binding->'request';
 IF candidate.id IS NULL OR NOT design.package_json_keys(r,ARRAY['bid_id','draft_id','candidate_id','candidate_digest',
 'decision','state','created_section_ids','draft_revision','snapshot_id','snapshot_digest','resolved_at','command'])
 OR r->>'bid_id' IS DISTINCT FROM NEW.bid_id::text OR r->>'draft_id' IS DISTINCT FROM NEW.draft_id::text
 OR r->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text OR r->>'candidate_digest' IS DISTINCT FROM candidate.digest
 OR r->>'decision' IS DISTINCT FROM NEW.decision
 OR r->>'state' IS DISTINCT FROM (CASE NEW.decision WHEN 'append' THEN 'applied' ELSE 'rejected' END)
 OR jsonb_typeof(r->'created_section_ids') IS DISTINCT FROM 'array' OR jsonb_typeof(r->'resolved_at') IS DISTINCT FROM 'string'
 OR NOT design.package_json_keys(binding,ARRAY['command_id','actor_id','idempotency_key','request_digest','request','if_match'])
 OR binding->>'command_id' IS DISTINCT FROM NEW.command_id::text OR binding->>'actor_id' IS DISTINCT FROM NEW.resolved_by::text
 OR NOT design.package_json_keys(body,ARRAY['decision','candidate_digest','acknowledged_issue_ids','reason'])
 OR body->>'decision' IS DISTINCT FROM NEW.decision OR body->>'candidate_digest' IS DISTINCT FROM candidate.digest
 OR jsonb_typeof(body->'acknowledged_issue_ids') IS DISTINCT FROM 'array'
 OR jsonb_typeof(body->'reason') IS DISTINCT FROM 'string'
 OR length(btrim(body->>'reason')) NOT BETWEEN 1 AND 1000 THEN
  RAISE EXCEPTION 'word_import_resolution_binding' USING ERRCODE='23514'; END IF;
 expected_digest:=encode(sha256(convert_to(design.package_canonical_json(jsonb_build_object('body',
 body||jsonb_build_object('bid_id',NEW.bid_id,'draft_id',NEW.draft_id),'if_match',binding->'if_match')),'UTF8')),'hex');
 SELECT * INTO cmd FROM design.commands WHERE id=NEW.command_id;
 IF cmd.id IS NULL OR cmd.actor_id IS DISTINCT FROM NEW.resolved_by OR cmd.command_kind IS DISTINCT FROM 'resolve-authoring-word-import'
 OR cmd.target_id IS DISTINCT FROM NEW.candidate_id OR cmd.idempotency_key IS DISTINCT FROM binding->>'idempotency_key'
 OR cmd.request_digest IS DISTINCT FROM expected_digest OR binding->>'request_digest' IS DISTINCT FROM expected_digest
 OR cmd.response->>'status' IS DISTINCT FROM '200' OR cmd.response->'body' IS DISTINCT FROM r THEN
  RAISE EXCEPTION 'word_import_resolve_ack' USING ERRCODE='23514'; END IF;
 IF NEW.decision='reject' THEN
  IF r->'created_section_ids' IS DISTINCT FROM '[]'::jsonb OR r->'draft_revision' IS DISTINCT FROM 'null'::jsonb
  OR r->'snapshot_id' IS DISTINCT FROM 'null'::jsonb OR r->'snapshot_digest' IS DISTINCT FROM 'null'::jsonb THEN
   RAISE EXCEPTION 'word_import_reject_mutated_draft' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT coalesce(jsonb_agg(item->'section_id' ORDER BY ordinal),'[]'::jsonb) INTO section_ids
  FROM jsonb_array_elements(candidate.manifest->'sections') WITH ORDINALITY e(item,ordinal);
  SELECT coalesce(jsonb_agg(item->'id' ORDER BY item->>'id'),'[]'::jsonb) INTO warnings
  FROM jsonb_array_elements(candidate.manifest#>'{parsed,issues}') e(item) WHERE item->>'severity'='warning';
  SELECT coalesce(jsonb_agg(item ORDER BY item#>>'{}'),'[]'::jsonb) INTO acknowledged
  FROM jsonb_array_elements(body->'acknowledged_issue_ids') e(item);
  IF candidate.manifest#>'{parsed,can_apply}' IS DISTINCT FROM 'true'::jsonb
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(candidate.manifest#>'{parsed,issues}') e(item) WHERE item->>'severity'='blocker')
  OR warnings IS DISTINCT FROM acknowledged OR jsonb_array_length(section_ids)=0
  OR r->'created_section_ids' IS DISTINCT FROM section_ids
  OR r->'draft_revision' IS DISTINCT FROM to_jsonb(candidate.base_draft_revision+1)
  OR binding->>'if_match' IS DISTINCT FROM ('"draft:'||NEW.draft_id::text||':'||candidate.base_draft_revision::text||'"') THEN
   RAISE EXCEPTION 'word_import_append_confirmation' USING ERRCODE='23514'; END IF;
  SELECT * INTO snapshot FROM design.draft_snapshots WHERE id=(r->>'snapshot_id')::uuid
  AND bid_id=NEW.bid_id AND draft_id=NEW.draft_id AND revision=candidate.base_draft_revision+1 AND digest=r->>'snapshot_digest';
  IF snapshot.id IS NULL OR EXISTS(SELECT 1 FROM design.draft_snapshot_sections prior_section
   WHERE prior_section.snapshot_id=candidate.base_snapshot_id AND NOT EXISTS(SELECT 1 FROM design.draft_snapshot_sections fresh
   WHERE fresh.snapshot_id=snapshot.id AND fresh.section_revision_id=prior_section.section_revision_id AND fresh.ordinal=prior_section.ordinal))
  OR (SELECT count(*) FROM design.draft_snapshot_sections WHERE snapshot_id=snapshot.id)<>
   (SELECT count(*) FROM design.draft_snapshot_sections WHERE snapshot_id=candidate.base_snapshot_id)+jsonb_array_length(section_ids)
  OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(section_ids) e(id) WHERE NOT EXISTS(
   SELECT 1 FROM design.draft_snapshot_sections ss JOIN design.section_revisions sr ON sr.id=ss.section_revision_id
   WHERE ss.snapshot_id=snapshot.id AND sr.section_id=e.id::uuid AND sr.revision=1 AND sr.created_by=NEW.resolved_by))
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(snapshot.manifest#>'{authoring_structure,metadata,word_import_sources}') e(proof)
   WHERE proof->>'candidate_id'=candidate.id::text AND proof->>'candidate_digest'=candidate.digest
   AND proof->'section_ids'=section_ids AND proof->'source_context'=candidate.manifest->'source_context'
   AND proof->>'proof_digest'=encode(sha256(convert_to(design.package_canonical_json(proof-'proof_digest'),'UTF8')),'hex')) THEN
   RAISE EXCEPTION 'word_import_append_snapshot' USING ERRCODE='23514'; END IF;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM design.audit_entries a WHERE a.command_id=NEW.command_id AND a.actor_id=NEW.resolved_by
 AND a.bid_id=NEW.bid_id AND a.event_type='authoring.word_import_resolved' AND a.payload=jsonb_build_object(
 'candidate_id',NEW.candidate_id,'draft_id',NEW.draft_id,'decision',NEW.decision,'candidate_digest',candidate.digest)) THEN
  RAISE EXCEPTION 'word_import_resolution_audit' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER authoring_word_import_resolution_complete AFTER INSERT ON authoring_word_import_resolutions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_word_import_resolution_guard();

REVOKE ALL ON authoring_word_imports,authoring_word_import_resolutions
 FROM PUBLIC,tender_api,tender_worker,tender_research_worker,tender_score_read,tender_research_read;
GRANT SELECT,INSERT ON authoring_word_imports,authoring_word_import_resolutions TO tender_api;
-- Worker consumes provenance embedded in immutable core draft snapshots. It
-- receives no candidate-table access, write permission, or editor identities.
REVOKE ALL ON FUNCTION authoring_word_import_guard(),authoring_word_import_resolution_guard() FROM PUBLIC;
COMMIT;
