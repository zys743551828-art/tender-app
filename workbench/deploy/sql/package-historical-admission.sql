-- Optional native package history authority. Static review -> fresh isolated DB only.
-- Requires complete BASE and model-governance.sql; never execute the old WIP
-- retrospective-research.sql. No old sample, online metric or model route writes.
BEGIN;
CREATE SCHEMA package_historical_research;
REVOKE ALL ON SCHEMA package_historical_research FROM PUBLIC;
CREATE ROLE tender_package_history_verify NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE tender_package_history_train NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE tender_package_history_evaluate NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE tender_package_history_test_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA package_historical_research TO tender_api,tender_package_history_verify,tender_package_history_train,tender_package_history_evaluate;

CREATE TABLE package_historical_research.test_environments(
 database_oid oid PRIMARY KEY,database_name text NOT NULL UNIQUE,
 isolation text NOT NULL CHECK(isolation='dedicated_disposable_mechanism_database'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(database_name~'^fusion_package_history_mechanism_[a-z0-9]{8}$')
);
-- Operator configuration is not a historical qualification decision. The issuer
-- must independently be able to attest the named source semantics. No business
-- role can register/enable a key, and a signature alone does not prove a claim.
CREATE TABLE package_historical_research.adapters(
 id uuid PRIMARY KEY,method text NOT NULL CHECK(method='signed-source-evidence/1'),
 name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 300),
 origin text NOT NULL CHECK(origin IN('synthetic','external_evidence')),
 public_key_hex text NOT NULL CHECK(public_key_hex~'^[a-f0-9]{64}$'),
 source_prefix text NOT NULL CHECK(length(btrim(source_prefix)) BETWEEN 5 AND 4000),
 source_semantics text NOT NULL CHECK(length(btrim(source_semantics)) BETWEEN 20 AND 8000),
 valid_from timestamptz NOT NULL,valid_until timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(valid_until IS NULL OR valid_until>valid_from)
);
CREATE TABLE package_historical_research.adapter_revocations(
 adapter_id uuid PRIMARY KEY REFERENCES package_historical_research.adapters(id),
 reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 4000),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE package_historical_research.proofs(
 id uuid PRIMARY KEY,adapter_id uuid NOT NULL REFERENCES package_historical_research.adapters(id),
 scope_id uuid NOT NULL REFERENCES design.bid_package_technical_scopes(id),
 submission_id uuid NOT NULL REFERENCES design.bid_package_submission_bindings(submission_id),
 outcome_id uuid NOT NULL REFERENCES design.outcomes(id),
 receipt_id text NOT NULL,origin text NOT NULL CHECK(origin IN('synthetic','external_evidence')),
 native_context jsonb NOT NULL,context_digest design.sha256 NOT NULL,
 envelope jsonb NOT NULL,envelope_digest design.sha256 NOT NULL,
 normalized jsonb NOT NULL,normalized_digest design.sha256 NOT NULL,
 verified_by name NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(adapter_id,receipt_id),
 CHECK(design.package_technical_digest(native_context)=context_digest),
 CHECK(design.package_technical_digest(envelope)=envelope_digest),
 CHECK(design.package_technical_digest(normalized)=normalized_digest),
 CHECK(octet_length(envelope::text)<=33554432 AND octet_length(native_context::text)<=33554432)
);
CREATE TABLE package_historical_research.admissions(
 id uuid PRIMARY KEY,proof_id uuid NOT NULL UNIQUE REFERENCES package_historical_research.proofs(id),
 bid_id uuid NOT NULL REFERENCES design.bids(id),scope_id uuid NOT NULL REFERENCES design.bid_package_technical_scopes(id),
 submission_id uuid NOT NULL REFERENCES design.bid_package_submission_bindings(submission_id),
 outcome_id uuid NOT NULL REFERENCES design.outcomes(id),
 origin text NOT NULL CHECK(origin IN('synthetic','external_evidence')),
 document jsonb NOT NULL,digest design.sha256 NOT NULL,
 created_by uuid NOT NULL REFERENCES design.members(id),command_id uuid NOT NULL UNIQUE REFERENCES design.commands(id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(design.package_technical_digest(document)=digest)
);
-- Materialized only from the verified native proof, never from an API grouping
-- choice. Indexed shared keys make full registered closure bounded and exact.
CREATE TABLE package_historical_research.admission_keys(
 admission_id uuid NOT NULL REFERENCES package_historical_research.admissions(id),
 kind text NOT NULL CHECK(kind IN('submission','project','body','text','template','near_duplicate')),
 identity text NOT NULL CHECK(length(identity)>0),PRIMARY KEY(admission_id,kind,identity)
);
CREATE INDEX admission_keys_related ON package_historical_research.admission_keys(kind,identity,admission_id);
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['test_environments','adapters','adapter_revocations','proofs','admissions','admission_keys'] LOOP
  EXECUTE format('CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_historical_research.%I FOR EACH ROW EXECUTE FUNCTION design.append_only()',tab);
 END LOOP;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA package_historical_research FROM PUBLIC,tender_api,tender_worker,tender_research_worker,tender_research_read,tender_score_read,tender_model_train,tender_model_evaluate,tender_model_score,tender_package_history_verify,tender_package_history_train,tender_package_history_evaluate,tender_package_history_test_api;

CREATE FUNCTION package_historical_research.assert_role(purpose text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE allowed text; forbidden text; who record;
BEGIN
 allowed:=CASE purpose WHEN 'api' THEN 'tender_api' WHEN 'verify' THEN 'tender_package_history_verify' WHEN 'train' THEN 'tender_package_history_train' WHEN 'evaluate' THEN 'tender_package_history_evaluate' END;
 SELECT * INTO who FROM pg_roles WHERE rolname=session_user;
 IF allowed IS NULL OR who.rolsuper OR who.rolbypassrls OR who.rolcreatedb OR who.rolcreaterole OR who.rolreplication
 OR NOT who.rolcanlogin OR NOT pg_has_role(session_user,allowed,'MEMBER')
 OR EXISTS(SELECT FROM pg_class WHERE relowner=who.oid AND relnamespace IN(to_regnamespace('design'),to_regnamespace('retrieval'),to_regnamespace('package_historical_research')))
 THEN RAISE EXCEPTION 'package_history_role_denied' USING ERRCODE='42501'; END IF;
 FOREACH forbidden IN ARRAY ARRAY['tender_api','tender_worker','tender_research_worker','tender_research_read','tender_score_read','tender_model_train','tender_model_evaluate','tender_model_score','tender_package_history_verify','tender_package_history_train','tender_package_history_evaluate'] LOOP
  IF forbidden<>allowed AND pg_has_role(session_user,forbidden,'MEMBER') THEN RAISE EXCEPTION 'package_history_mixed_role_denied' USING ERRCODE='42501'; END IF;
 END LOOP;
 IF purpose<>'api' AND (has_table_privilege(session_user,'design.outcomes','SELECT') OR has_table_privilege(session_user,'design.evidence_blocks','SELECT') OR has_table_privilege(session_user,'design.sessions','SELECT') OR has_table_privilege(session_user,'package_historical_research.proofs','SELECT')) THEN
  RAISE EXCEPTION 'package_history_raw_access_denied' USING ERRCODE='42501';
 END IF;
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'package_history_read_committed_required' USING ERRCODE='55000'; END IF;
END $$;

CREATE FUNCTION package_historical_research.assert_origin(origin text,api boolean DEFAULT false) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
BEGIN
 IF origin='synthetic' AND (NOT EXISTS(SELECT FROM package_historical_research.test_environments e JOIN pg_database d ON d.oid=e.database_oid AND d.datname=e.database_name WHERE d.datname=current_database() AND d.datname~'^fusion_package_history_mechanism_[a-z0-9]{8}$')
  OR (api AND NOT pg_has_role(session_user,'tender_package_history_test_api','MEMBER'))) THEN
  RAISE EXCEPTION 'package_history_synthetic_environment_denied' USING ERRCODE='42501';
 ELSIF origin NOT IN('synthetic','external_evidence') THEN RAISE EXCEPTION 'package_history_origin_invalid' USING ERRCODE='23514'; END IF;
END $$;

CREATE FUNCTION package_historical_research.adapter_current(target uuid) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
 SELECT EXISTS(SELECT FROM package_historical_research.adapters a WHERE a.id=target AND a.valid_from<=clock_timestamp() AND (a.valid_until IS NULL OR a.valid_until>clock_timestamp()) AND NOT EXISTS(SELECT FROM package_historical_research.adapter_revocations r WHERE r.adapter_id=a.id))
$$;

CREATE FUNCTION package_historical_research.native_context(target_scope uuid,target_submission uuid,target_outcome uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,design,retrieval,pg_temp AS $$
DECLARE s design.bid_package_technical_scopes; sub design.submission_records; binding design.bid_package_submission_bindings; outcome design.outcomes; decision design.decisions;
 p jsonb; identity jsonb; proof jsonb; official jsonb; original_ids uuid[]; roots uuid[]; authority_roots uuid[];
 value jsonb; row_doc record; row_source record; expected jsonb; originals jsonb; label_doc record; result jsonb; target_files jsonb; rules jsonb; row_parse record;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'package_history_read_committed_required' USING ERRCODE='55000'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT * INTO s FROM design.bid_package_technical_scopes WHERE id=target_scope;
 IF NOT FOUND THEN RAISE EXCEPTION 'package_history_scope_missing' USING ERRCODE='P0002'; END IF;
 PERFORM design.lock_worker_bid(s.bid_id);
 PERFORM pg_advisory_xact_lock(90127,1);
 SELECT * INTO sub FROM design.submission_records WHERE id=target_submission AND bid_id=s.bid_id;
 SELECT * INTO binding FROM design.bid_package_submission_bindings WHERE submission_id=target_submission AND bid_id=s.bid_id;
 SELECT * INTO outcome FROM design.outcomes WHERE id=target_outcome AND submission_id=target_submission AND bid_id=s.bid_id;
 IF sub.id IS NULL OR binding.submission_id IS NULL OR outcome.id IS NULL THEN RAISE EXCEPTION 'package_history_exact_subject_missing' USING ERRCODE='P0002'; END IF;
 p:=s.manifest#>'{preview,manifest}'; identity:=binding.manifest->'package_identity';
 IF sub.subject_kind<>'bid_package' OR sub.body_version_id IS NOT NULL
 OR NOT EXISTS(SELECT FROM design.submission_heads WHERE bid_id=s.bid_id AND submission_id=sub.id)
 OR s.package_id<>binding.package_id OR s.revision_id<>binding.revision_id OR s.inventory_id IS DISTINCT FROM binding.inventory_id
 OR p#>>'{basis,authority_revision_id}' IS DISTINCT FROM binding.authority_revision_id::text
 OR p#>>'{basis,package_digest}' IS DISTINCT FROM binding.manifest#>>'{subject,package_digest}'
 OR p#>>'{basis,authority_digest}' IS DISTINCT FROM binding.manifest#>>'{selection,authority,digest}'
 OR p#>>'{basis,inventory_digest}' IS DISTINCT FROM binding.manifest#>>'{selection,inventory,digest}'
 OR p#>>'{basis,identity_digest}' IS DISTINCT FROM identity->>'digest'
 OR identity IS DISTINCT FROM binding.manifest#>'{selection,target,identity}'
 OR identity IS DISTINCT FROM binding.manifest#>'{selection,authority,identity}'
 OR identity IS DISTINCT FROM design.identity_snapshot_v2(s.bid_id)
 OR identity->>'binding_status' IS DISTINCT FROM 'confirmed'
 OR s.digest IS DISTINCT FROM design.package_technical_digest(s.manifest)
 OR s.manifest#>>'{preview,digest}' IS DISTINCT FROM design.package_technical_digest(p)
 OR binding.digest IS DISTINCT FROM design.package_technical_digest(binding.manifest)
 OR (binding.manifest->>'submitted_at')::timestamptz IS DISTINCT FROM sub.submitted_at
 OR sub.submitted_at>clock_timestamp() OR sub.created_at>clock_timestamp()
 THEN RAISE EXCEPTION 'package_history_exact_scope_mismatch' USING ERRCODE='55000'; END IF;
 IF EXISTS(SELECT FROM jsonb_array_elements(p->'rules') r WHERE r->>'selection'='unclassified')
 OR NOT EXISTS(SELECT FROM jsonb_array_elements(p->'rules') r WHERE r->>'selection'='include')
 OR EXISTS(SELECT FROM jsonb_array_elements(p->'rules') r WHERE r->>'selection'='include' AND (jsonb_array_length(r->'part_ids')=0 OR r#>>'{rule_snapshot,provenance_status}' IS DISTINCT FROM 'effective'))
 THEN RAISE EXCEPTION 'package_history_required_range_unclassified' USING ERRCODE='55000'; END IF;
 FOR value IN SELECT * FROM jsonb_array_elements(p->'documents') LOOP
  SELECT v.*,b.digest,b.byte_size INTO row_doc FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.id=(value->>'document_version_id')::uuid AND v.bid_id=s.bid_id;
  SELECT * INTO row_parse FROM design.parse_runs WHERE id=(value#>>'{parse,parse_run_id}')::uuid AND bid_id=s.bid_id AND document_version_id=row_doc.id;
  IF row_doc.id IS NULL OR row_doc.digest::text IS DISTINCT FROM value->>'file_digest' OR row_doc.byte_size IS DISTINCT FROM (value->>'byte_size')::bigint
  OR row_doc.artifact_kind NOT IN('source_original','bid_body') OR value#>>'{parse,status}' IS DISTINCT FROM 'frozen'
  OR row_parse.id IS NULL OR row_parse.coverage<>'complete' OR row_parse.gaps<>'[]'::jsonb OR row_parse.page_count<>(value->>'page_count')::integer
  OR row_parse.parser_digest::text IS DISTINCT FROM value#>>'{parse,parser_digest}' OR row_parse.config_digest::text IS DISTINCT FROM value#>>'{parse,config_digest}'
  OR design.package_technical_digest(design.package_parse_evidence_manifest(row_parse.id)) IS DISTINCT FROM value#>>'{parse,evidence_digest}'
  THEN RAISE EXCEPTION 'package_history_exact_original_parse_changed' USING ERRCODE='55000'; END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('physical_page',physical_page,'quality',quality,'gaps',gaps) ORDER BY physical_page),'[]'::jsonb) INTO expected FROM design.pages WHERE bid_id=s.bid_id AND parse_id=row_parse.id;
  IF expected IS DISTINCT FROM value->'pages' OR jsonb_array_length(expected)<>row_parse.page_count OR EXISTS(SELECT FROM jsonb_array_elements(expected) pg WHERE pg->>'quality'<>'usable' OR pg->'gaps'<>'[]'::jsonb) THEN RAISE EXCEPTION 'package_history_full_pages_changed' USING ERRCODE='55000'; END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'physical_page',physical_page,'ordinal',ordinal,'kind',kind,'text_content',text_content,'digest',digest,'bbox_json',bbox::text,'structure_json',structure::text) ORDER BY physical_page,ordinal,id),'[]'::jsonb) INTO expected FROM design.evidence_blocks WHERE bid_id=s.bid_id AND parse_id=row_parse.id;
  IF expected IS DISTINCT FROM value->'blocks' OR EXISTS(SELECT FROM design.evidence_blocks e WHERE e.parse_id=row_parse.id AND e.digest::text<>encode(sha256(convert_to(e.text_content,'UTF8')),'hex')) THEN RAISE EXCEPTION 'package_history_full_evidence_changed' USING ERRCODE='55000'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT FROM design.bid_package_requirement_inventories inv JOIN design.rule_sets rs ON rs.id=inv.rule_set_id AND rs.bid_id=inv.bid_id WHERE inv.id=s.inventory_id AND inv.digest::text=p#>>'{basis,inventory_digest}' AND inv.rule_set_id::text=p#>>'{basis,rule_set_id}' AND rs.digest::text=p#>>'{basis,rule_set_digest}')
 OR EXISTS(SELECT FROM design.bid_package_requirements q LEFT JOIN design.rule_items r ON r.id=q.rule_id AND r.bid_id=q.bid_id LEFT JOIN design.decision_heads h ON h.bid_id=r.bid_id AND h.object_kind='rule' AND h.object_id=r.id LEFT JOIN design.rule_carryovers carry ON carry.new_rule_id=r.id WHERE q.inventory_id=s.inventory_id AND (r.id IS NULL OR (to_jsonb(r)||jsonb_build_object('max_points',r.max_points::text)) IS DISTINCT FROM q.payload->'rule_snapshot' OR coalesce(h.decision_id,carry.from_decision_id) IS DISTINCT FROM q.decision_id))
 THEN RAISE EXCEPTION 'package_history_rule_authority_changed' USING ERRCODE='55000'; END IF;
 SELECT array_agg(DISTINCT id ORDER BY id) INTO roots FROM (
  SELECT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-original:'||document_version_id::text) id FROM design.bid_package_members WHERE revision_id IN(s.revision_id,binding.authority_revision_id)
  UNION SELECT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-parse:'||parse_run_id::text) FROM design.bid_package_members WHERE revision_id IN(s.revision_id,binding.authority_revision_id) AND parse_run_id IS NOT NULL
 ) q;
 SELECT array_agg(DISTINCT id ORDER BY id) INTO authority_roots FROM (
  SELECT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-original:'||document_version_id::text) id FROM design.bid_package_members WHERE revision_id=binding.authority_revision_id
  UNION SELECT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-parse:'||parse_run_id::text) FROM design.bid_package_members WHERE revision_id=binding.authority_revision_id AND parse_run_id IS NOT NULL
 ) q;
 PERFORM h.source_id FROM retrieval.source_heads h WHERE h.source_id IN(SELECT ancestor_id FROM retrieval.source_ancestors WHERE source_id=ANY(roots)) ORDER BY h.source_id FOR SHARE OF h;
 IF roots IS NULL OR roots IS DISTINCT FROM (SELECT array_agg(DISTINCT (v->>'source_id')::uuid ORDER BY (v->>'source_id')::uuid) FROM jsonb_array_elements(p->'source_snapshot')v)
 OR (SELECT jsonb_agg(jsonb_build_array(a.source_id,a.ancestor_id) ORDER BY a.source_id,a.ancestor_id) FROM retrieval.source_ancestors a WHERE a.source_id=ANY(roots)) IS DISTINCT FROM (SELECT jsonb_agg(jsonb_build_array((v->>'source_id')::uuid,(v->>'ancestor_id')::uuid) ORDER BY (v->>'source_id')::uuid,(v->>'ancestor_id')::uuid) FROM jsonb_array_elements(p->'source_snapshot')v)
 OR EXISTS(SELECT FROM unnest(roots) id WHERE NOT EXISTS(SELECT FROM retrieval.source_ancestors a WHERE a.source_id=id AND a.ancestor_id=id))
 THEN RAISE EXCEPTION 'package_history_full_ancestor_closure_changed' USING ERRCODE='55000'; END IF;
 FOR value IN SELECT * FROM jsonb_array_elements(p->'source_snapshot') LOOP
  SELECT n.*,h.revision,h.status,h.valid_from,h.valid_until,v.bid_id,b.digest AS original_digest INTO row_source FROM retrieval.source_nodes n JOIN retrieval.source_heads h ON h.source_id=n.id JOIN design.document_versions v ON v.id=n.document_version_id JOIN design.blobs b ON b.id=v.blob_id WHERE n.id=(value->>'ancestor_id')::uuid;
  IF row_source.id IS NULL OR row_source.bid_id<>s.bid_id OR row_source.kind<>'document' OR row_source.policy_class<>'prebid_content' OR row_source.status<>'published'
  OR row_source.digest<>row_source.original_digest OR row_source.known_at>clock_timestamp() OR row_source.valid_from>clock_timestamp() OR row_source.valid_until<=clock_timestamp()
  OR row_source.document_version_id::text IS DISTINCT FROM value->>'document_version_id' OR row_source.digest::text IS DISTINCT FROM value->>'digest'
  OR row_source.revision IS DISTINCT FROM (value->>'revision')::bigint OR row_source.known_at IS DISTINCT FROM (value->>'known_at')::timestamptz
  OR row_source.valid_from IS DISTINCT FROM (value->>'valid_from')::timestamptz OR row_source.valid_until IS DISTINCT FROM (value->>'valid_until')::timestamptz
  THEN RAISE EXCEPTION 'package_history_source_withdrawn_or_changed' USING ERRCODE='55000'; END IF;
 END LOOP;
 IF EXISTS(SELECT FROM design.bid_package_members m WHERE m.revision_id IN(s.revision_id,binding.authority_revision_id) AND NOT EXISTS(SELECT FROM retrieval.lineage_edges e WHERE e.child_id=public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-parse:'||m.parse_run_id::text) AND e.parent_id=public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-original:'||m.document_version_id::text))) THEN RAISE EXCEPTION 'package_history_parse_original_edge_missing' USING ERRCODE='55000'; END IF;
 SELECT array_agg(DISTINCT n.document_version_id ORDER BY n.document_version_id) INTO original_ids FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.ancestor_id WHERE a.source_id=ANY(roots);
 SELECT jsonb_agg(jsonb_build_object('document_version_id',v.id,'digest',b.digest,'byte_size',b.byte_size,'artifact_kind',v.artifact_kind,'obtained_at',v.obtained_at,'recorded_at',v.created_at,'requires_effective_proof',EXISTS(SELECT FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.ancestor_id WHERE a.source_id=ANY(authority_roots) AND n.document_version_id=v.id)) ORDER BY v.id) INTO originals FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.id=ANY(original_ids) AND v.bid_id=s.bid_id;
 IF jsonb_array_length(originals) IS DISTINCT FROM cardinality(original_ids) THEN RAISE EXCEPTION 'package_history_original_missing' USING ERRCODE='55000'; END IF;
 SELECT d.* INTO decision FROM design.decision_heads h JOIN design.decisions d ON d.id=h.decision_id AND d.bid_id=h.bid_id WHERE h.bid_id=s.bid_id AND h.object_kind='outcome' AND h.object_id=outcome.id;
 IF decision.id IS NULL OR decision.decision<>'verified' OR NOT EXISTS(SELECT FROM design.outcome_heads h WHERE h.bid_id=s.bid_id AND h.submission_id=sub.id AND h.outcome_id=outcome.id AND h.revision=decision.object_revision)
 OR outcome.score_kind<>'technical_total' OR outcome.value IS NULL OR outcome.maximum IS NULL OR outcome.maximum<=0 OR outcome.value<0 OR outcome.value>outcome.maximum
 OR outcome.value IN('NaN','Infinity','-Infinity') OR outcome.maximum IN('NaN','Infinity','-Infinity') OR outcome.known_at<sub.submitted_at OR outcome.known_at>clock_timestamp()
 THEN RAISE EXCEPTION 'package_history_verified_official_technical_label_required' USING ERRCODE='55000'; END IF;
 BEGIN proof:=decision.reason::jsonb; EXCEPTION WHEN invalid_text_representation THEN RAISE EXCEPTION 'package_history_official_verification_unproven' USING ERRCODE='55000'; END;
 IF proof->>'version' IS DISTINCT FROM 'package-outcome-verification-record/1' OR proof->>'binding_digest' IS DISTINCT FROM binding.digest::text OR proof->'package_identity' IS DISTINCT FROM identity
 OR proof#>'{request,identity}' IS DISTINCT FROM jsonb_build_object('project_id',identity->'engineering_project_id','lot_id',identity->'lot_id','round_id',identity->'round_id','bidder_id',identity->'bidder_id','package_id',s.package_id,'revision_id',s.revision_id,'package_digest',p#>'{basis,package_digest}','binding_digest',binding.digest,'identity_digest',identity->'digest')
 OR proof#>'{request,authority}' IS DISTINCT FROM jsonb_build_object('package_id',binding.manifest#>'{selection,authority,manifest,package_id}','revision_id',binding.authority_revision_id,'digest',p#>'{basis,authority_digest}','identity_digest',identity->'digest')
 OR proof#>>'{request,state}' IS DISTINCT FROM 'verified' OR (proof#>>'{request,published_at}')::timestamptz<sub.submitted_at OR (proof#>>'{request,published_at}')::timestamptz>outcome.known_at
 OR jsonb_typeof(proof#>'{request,published_at}') IS DISTINCT FROM 'string' OR jsonb_typeof(proof->'checked_at') IS DISTINCT FROM 'string'
 OR jsonb_typeof(proof#>'{request,evidence_refs}') IS DISTINCT FROM 'array' OR length(btrim(proof#>>'{request,aggregation}'))=0
 OR proof#>>'{official_source_proof,digest}' IS DISTINCT FROM design.package_technical_digest(proof#>'{official_source_proof,snapshot}')
 OR proof#>>'{authority_proof,digest}' IS DISTINCT FROM design.package_technical_digest(proof#>'{authority_proof,snapshot}')
 OR (proof->>'checked_at')::timestamptz>clock_timestamp()
 THEN RAISE EXCEPTION 'package_history_official_verification_unproven' USING ERRCODE='55000'; END IF;
 official:=proof#>'{official_source_proof,snapshot}';
 IF official->>'schema' IS DISTINCT FROM 'official-source-authority/v2' OR official->>'root_id' IS DISTINCT FROM public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-original:'||outcome.source_version_id::text)::text THEN RAISE EXCEPTION 'package_history_official_source_unproven' USING ERRCODE='55000'; END IF;
 SELECT v.id,b.digest,b.byte_size,v.obtained_at INTO label_doc FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.id=outcome.source_version_id AND v.bid_id=s.bid_id AND v.artifact_kind='source_original';
 IF label_doc.id IS NULL OR label_doc.obtained_at>outcome.known_at OR NOT EXISTS(SELECT FROM design.material_assignments a WHERE a.bid_id=s.bid_id AND a.document_version_id=label_doc.id AND a.role='official_result') AND NOT EXISTS(SELECT FROM design.document_file_versions fv JOIN design.document_files f ON f.id=fv.file_id WHERE fv.version_id=label_doc.id AND f.bid_id=s.bid_id AND f.role='official_result') THEN RAISE EXCEPTION 'package_history_official_original_unproven' USING ERRCODE='55000'; END IF;
 FOR value IN SELECT * FROM jsonb_array_elements(proof#>'{request,evidence_refs}') LOOP
  IF NOT EXISTS(SELECT FROM design.evidence_blocks e JOIN design.parse_runs p ON p.id=e.parse_id AND p.bid_id=e.bid_id JOIN design.pages pg ON pg.parse_id=p.id AND pg.physical_page=e.physical_page
   WHERE e.id=(value->>'evidence_id')::uuid AND e.bid_id=s.bid_id AND p.document_version_id=outcome.source_version_id AND value->>'document_version_id'=outcome.source_version_id::text AND e.physical_page=(value->>'physical_page')::integer
   AND p.coverage='complete' AND p.gaps='[]'::jsonb AND pg.quality='usable' AND pg.gaps='[]'::jsonb AND position(value->>'quote' IN e.text_content)>0 AND e.digest::text=encode(sha256(convert_to(e.text_content,'UTF8')),'hex')
   AND EXISTS(SELECT FROM jsonb_array_elements(official->'evidence') frozen(leaf) WHERE leaf->>'id'=e.id::text AND leaf->>'parse_id'=p.id::text AND leaf->>'digest'=e.digest::text AND (leaf->>'physical_page')::integer=e.physical_page AND leaf->>'quote_digest'=encode(sha256(convert_to(value->>'quote','UTF8')),'hex')))
  THEN RAISE EXCEPTION 'package_history_official_evidence_changed' USING ERRCODE='55000'; END IF;
 END LOOP;
 IF jsonb_array_length(proof#>'{request,evidence_refs}')=0 OR (SELECT array_agg(DISTINCT (r->>'evidence_id')::uuid ORDER BY (r->>'evidence_id')::uuid) FROM jsonb_array_elements(proof#>'{request,evidence_refs}')r) IS DISTINCT FROM (SELECT array_agg(id ORDER BY id) FROM unnest(decision.evidence_ids)id) THEN RAISE EXCEPTION 'package_history_official_evidence_missing' USING ERRCODE='55000'; END IF;
 SELECT array_agg(DISTINCT (v->>'source_id')::uuid ORDER BY (v->>'source_id')::uuid) INTO roots FROM jsonb_array_elements(official->'heads')v;
 IF roots IS DISTINCT FROM (SELECT array_agg(id ORDER BY id) FROM (SELECT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-original:'||outcome.source_version_id::text) id UNION SELECT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-parse:'||e.parse_id::text) FROM design.evidence_blocks e WHERE e.id=ANY(decision.evidence_ids) AND e.bid_id=s.bid_id) canonical_roots) THEN RAISE EXCEPTION 'package_history_official_canonical_roots_missing' USING ERRCODE='55000'; END IF;
 PERFORM h.source_id FROM retrieval.source_heads h WHERE h.source_id IN(SELECT ancestor_id FROM retrieval.source_ancestors WHERE source_id=ANY(roots)) ORDER BY h.source_id FOR SHARE OF h;
 IF roots IS NULL OR (SELECT jsonb_agg(jsonb_build_array(a.source_id,a.ancestor_id) ORDER BY a.source_id,a.ancestor_id) FROM retrieval.source_ancestors a WHERE a.source_id=ANY(roots)) IS DISTINCT FROM (SELECT jsonb_agg(jsonb_build_array((v->>'source_id')::uuid,(v->>'id')::uuid) ORDER BY (v->>'source_id')::uuid,(v->>'id')::uuid) FROM jsonb_array_elements(official->'heads')v)
 OR official->'edges' IS DISTINCT FROM (SELECT coalesce(jsonb_agg(jsonb_build_object('child_id',child_id,'parent_id',parent_id) ORDER BY child_id,parent_id),'[]') FROM retrieval.lineage_edges WHERE child_id IN(SELECT ancestor_id FROM retrieval.source_ancestors WHERE source_id=ANY(roots)))
 THEN RAISE EXCEPTION 'package_history_official_ancestor_closure_changed' USING ERRCODE='55000'; END IF;
 FOR value IN SELECT * FROM jsonb_array_elements(official->'heads') LOOP
  SELECT n.*,h.revision,h.status,h.valid_from,h.valid_until,v.bid_id,b.digest AS original_digest INTO row_source FROM retrieval.source_nodes n JOIN retrieval.source_heads h ON h.source_id=n.id JOIN design.document_versions v ON v.id=n.document_version_id JOIN design.blobs b ON b.id=v.blob_id WHERE n.id=(value->>'id')::uuid;
  IF row_source.id IS NULL OR row_source.bid_id<>s.bid_id OR row_source.kind<>'document' OR row_source.policy_class<>'official_label' OR row_source.status<>'published' OR row_source.digest<>row_source.original_digest
  OR row_source.known_at>outcome.known_at OR row_source.valid_from>clock_timestamp() OR row_source.valid_until<=clock_timestamp()
  OR row_source.document_version_id::text IS DISTINCT FROM value->>'document_version_id' OR row_source.digest::text IS DISTINCT FROM value->>'digest' OR row_source.revision IS DISTINCT FROM (value->>'revision')::bigint
  OR row_source.known_at IS DISTINCT FROM (value->>'known_at')::timestamptz OR row_source.valid_from IS DISTINCT FROM (value->>'valid_from')::timestamptz OR row_source.valid_until IS DISTINCT FROM (value->>'valid_until')::timestamptz
  THEN RAISE EXCEPTION 'package_history_official_source_withdrawn_or_changed' USING ERRCODE='55000'; END IF;
 END LOOP;
 SELECT jsonb_agg(jsonb_build_object('digest',m.file_digest,'byte_size',b.byte_size) ORDER BY m.file_digest,b.byte_size,m.member_id) INTO target_files FROM design.bid_package_members m JOIN design.document_versions v ON v.id=m.document_version_id JOIN design.blobs b ON b.id=v.blob_id WHERE m.revision_id=s.revision_id;
 SELECT jsonb_agg(jsonb_build_object('rule_id',r->>'rule_id','maximum',r#>>'{rule_snapshot,max_points}') ORDER BY r->>'rule_id') INTO rules FROM jsonb_array_elements(p->'rules')r WHERE r->>'selection'='include';
 IF EXISTS(SELECT FROM jsonb_array_elements(rules)r WHERE r->>'maximum' IS NULL OR (r->>'maximum')::numeric<=0 OR (r->>'maximum')::numeric IN('NaN','Infinity','-Infinity')) THEN RAISE EXCEPTION 'package_history_applicable_rule_scale_unknown' USING ERRCODE='55000'; END IF;
 result:=jsonb_build_object('schema','native-package-history-context/1','scope',jsonb_build_object('id',s.id,'digest',s.digest,'frozen_at',s.manifest->'frozen_at'),
  'submission',jsonb_build_object('id',sub.id,'submitted_at',sub.submitted_at,'recorded_at',sub.created_at,'binding_digest',binding.digest),
  'bid_id',s.bid_id,'identity',identity,'basis',p->'basis','documents',p->'documents','source_snapshot',p->'source_snapshot','originals',originals,'target_files',target_files,
  'technical_part_ids',(SELECT jsonb_agg(v ORDER BY v) FROM jsonb_array_elements(p#>'{request,technical_part_ids}')v),
  'rule_scopes',(SELECT jsonb_agg(r-ARRAY['reason'] ORDER BY r->>'rule_id') FROM jsonb_array_elements(p#>'{request,rule_scopes}')r),'applicable_rules',rules,
  'label',jsonb_build_object('id',outcome.id,'value',outcome.value::text,'maximum',outcome.maximum::text,'known_at',outcome.known_at,'published_at',proof#>'{request,published_at}','decision_id',decision.id,'decision_digest',design.package_technical_digest(proof),'source_version_id',outcome.source_version_id,'file_digest',label_doc.digest,'byte_size',label_doc.byte_size,'source_proof',official),
  'target_text_digest',design.package_technical_digest((SELECT jsonb_agg(regexp_replace(e->>'text_content','\s+',' ','g') ORDER BY d->>'member_id',(e->>'physical_page')::integer,(e->>'ordinal')::integer) FROM jsonb_array_elements(p->'documents')d CROSS JOIN LATERAL jsonb_array_elements(d->'blocks')e WHERE d->>'package_role'='target')));
 RETURN result;
END $$;

CREATE FUNCTION package_historical_research.verification_material(target_scope uuid,target_submission uuid,target_outcome uuid,adapter uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE key package_historical_research.adapters; context jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('verify');
 SELECT * INTO key FROM package_historical_research.adapters WHERE id=adapter;
 IF key.id IS NULL OR NOT package_historical_research.adapter_current(adapter) THEN RAISE EXCEPTION 'package_history_proof_adapter_unavailable' USING ERRCODE='55000'; END IF;
 PERFORM package_historical_research.assert_origin(key.origin);
 context:=package_historical_research.native_context(target_scope,target_submission,target_outcome);
 RETURN jsonb_build_object('adapter',to_jsonb(key),'context',context,'context_digest',design.package_technical_digest(context),'observed_at',clock_timestamp());
END $$;

CREATE FUNCTION package_historical_research.record_proof(target_scope uuid,target_submission uuid,target_outcome uuid,adapter uuid,envelope jsonb,normalized jsonb,expected_context design.sha256) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,design,pg_temp AS $$
DECLARE material jsonb; ctx jsonb; identity uuid:=gen_random_uuid(); prior package_historical_research.proofs; origin text; resource jsonb; item jsonb;
BEGIN
 material:=package_historical_research.verification_material(target_scope,target_submission,target_outcome,adapter); ctx:=material->'context'; origin:=material#>>'{adapter,origin}';
 IF expected_context::text IS DISTINCT FROM material->>'context_digest' OR normalized->>'context_digest' IS DISTINCT FROM expected_context::text OR envelope#>>'{payload,context_digest}' IS DISTINCT FROM expected_context::text
 OR normalized->>'schema' IS DISTINCT FROM 'package-history-normalized-evidence/1' OR normalized->>'adapter_id' IS DISTINCT FROM adapter::text OR normalized->>'origin' IS DISTINCT FROM origin
 OR normalized->>'adapter_method' IS DISTINCT FROM 'signed-source-evidence/1' OR normalized->>'receipt_id' IS DISTINCT FROM envelope#>>'{payload,receipt_id}'
 OR normalized->>'envelope_digest' IS DISTINCT FROM design.package_technical_digest(envelope) OR normalized->'research_only' IS DISTINCT FROM 'true'::jsonb OR normalized->>'formal_eligibility' IS DISTINCT FROM 'unavailable'
 OR normalized->'strict_prebid_eligible' IS DISTINCT FROM 'false'::jsonb OR normalized->'online_metrics_eligible' IS DISTINCT FROM 'false'::jsonb
 OR (normalized->>'historical_as_of')::timestamptz IS DISTINCT FROM (ctx#>>'{submission,submitted_at}')::timestamptz
 OR (normalized->>'issued_at')::timestamptz>clock_timestamp() OR normalized#>>'{coverage,scope_digest}' IS DISTINCT FROM ctx#>>'{scope,digest}' OR normalized#>'{coverage,parts}' IS DISTINCT FROM ctx->'technical_part_ids' OR normalized#>'{coverage,rules}' IS DISTINCT FROM ctx->'rule_scopes'
 OR normalized#>>'{actual_submission,identity_digest}' IS DISTINCT FROM ctx#>>'{identity,digest}' OR normalized#>>'{actual_submission,package_digest}' IS DISTINCT FROM ctx#>>'{basis,package_digest}' OR normalized#>'{actual_submission,files}' IS DISTINCT FROM ctx->'target_files'
 OR normalized#>>'{scale,aggregation}' IS DISTINCT FROM 'published_final_technical_total' OR normalized#>>'{scale,scale_description}' IS DISTINCT FROM '未加权原始分'
 OR (normalized#>>'{scale,maximum}')::numeric IS DISTINCT FROM (ctx#>>'{label,maximum}')::numeric
 OR jsonb_array_length(normalized->'historical_facts') IS DISTINCT FROM jsonb_array_length(ctx->'originals')
 THEN RAISE EXCEPTION 'package_history_proof_context_mismatch' USING ERRCODE='23514'; END IF;
 -- The verifier is a dedicated trusted adapter boundary, never an API role.
 -- SQL independently checks exact original bytes and signed resource manifest;
 -- Ed25519 + bounded source semantics are checked by the fixed verifier process.
 FOR resource IN SELECT * FROM jsonb_array_elements(envelope->'resources') LOOP
  IF resource->>'sha256' IS DISTINCT FROM encode(sha256(decode(resource->>'data_base64','base64')),'hex') OR (resource->>'byte_size')::bigint IS DISTINCT FROM octet_length(decode(resource->>'data_base64','base64'))
  OR NOT EXISTS(SELECT FROM jsonb_array_elements(envelope#>'{payload,resources_manifest}')m WHERE m=resource-'data_base64') THEN RAISE EXCEPTION 'package_history_resource_bytes_changed' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR item IN SELECT * FROM jsonb_array_elements(ctx->'originals') LOOP
  IF NOT EXISTS(SELECT FROM jsonb_array_elements(normalized->'historical_facts')f WHERE f->>'document_version_id'=item->>'document_version_id' AND f#>>'{exists,original_sha256}'=item->>'digest' AND f#>>'{acquired,original_sha256}'=item->>'digest' AND (f#>>'{acquired,at}')::timestamptz=(item->>'obtained_at')::timestamptz AND (f#>>'{exists,at}')::timestamptz<=(f#>>'{acquired,at}')::timestamptz AND (f#>>'{exists,recorded_at}')::timestamptz<=(ctx#>>'{submission,submitted_at}')::timestamptz AND (f#>>'{acquired,recorded_at}')::timestamptz<=(ctx#>>'{submission,submitted_at}')::timestamptz)
  OR NOT EXISTS(SELECT FROM jsonb_array_elements(envelope->'resources')r WHERE r->>'kind'='original_bytes' AND r->>'sha256'=item->>'digest' AND (r->>'byte_size')::bigint=(item->>'byte_size')::bigint) THEN RAISE EXCEPTION 'package_history_historical_bytes_unproven' USING ERRCODE='23514'; END IF;
 END LOOP;
 PERFORM pg_advisory_xact_lock(91503,hashtext(adapter::text||':'||(normalized->>'receipt_id')));
 SELECT * INTO prior FROM package_historical_research.proofs p WHERE p.adapter_id=adapter AND p.receipt_id=record_proof.normalized->>'receipt_id';
 IF FOUND THEN
  IF prior.envelope_digest<>design.package_technical_digest(envelope) OR prior.normalized_digest<>design.package_technical_digest(normalized) OR prior.context_digest<>expected_context THEN RAISE EXCEPTION 'package_history_receipt_conflict' USING ERRCODE='23505'; END IF;
  RETURN prior.id;
 END IF;
 INSERT INTO package_historical_research.proofs VALUES(identity,adapter,target_scope,target_submission,target_outcome,normalized->>'receipt_id',origin,ctx,expected_context,envelope,design.package_technical_digest(envelope),normalized,design.package_technical_digest(normalized),session_user,clock_timestamp());
 INSERT INTO design.audit_entries(id,actor_id,bid_id,event_type,payload) VALUES(gen_random_uuid(),NULL,(ctx->>'bid_id')::uuid,'package-history.proof-recorded',jsonb_build_object('proof_id',identity,'context_digest',expected_context,'adapter_id',adapter,'verifier',session_user,'origin',origin));
 RETURN identity;
END $$;

CREATE FUNCTION package_historical_research.current_proof(target uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE p package_historical_research.proofs; ctx jsonb;
BEGIN
 SELECT * INTO p FROM package_historical_research.proofs WHERE id=target;
 IF NOT FOUND OR NOT package_historical_research.adapter_current(p.adapter_id) THEN RETURN false; END IF;
 PERFORM package_historical_research.assert_origin(p.origin);
 ctx:=package_historical_research.native_context(p.scope_id,p.submission_id,p.outcome_id);
 RETURN p.context_digest=design.package_technical_digest(ctx) AND p.native_context=ctx;
EXCEPTION WHEN SQLSTATE '55000' OR SQLSTATE 'P0002' OR SQLSTATE '23514' THEN RETURN false;
END $$;

CREATE FUNCTION package_historical_research.admission_context(target_scope uuid,target_submission uuid,target_outcome uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE ctx jsonb; gaps jsonb:='[]'; candidates jsonb:='[]'; code text; evidence_count integer;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 BEGIN ctx:=package_historical_research.native_context(target_scope,target_submission,target_outcome);
 EXCEPTION WHEN SQLSTATE '55000' OR SQLSTATE 'P0002' OR SQLSTATE '23514' THEN GET STACKED DIAGNOSTICS code=MESSAGE_TEXT; gaps:=jsonb_build_array(jsonb_build_object('code',upper(code),'message','确切范围、实交、官方技术标签或完整来源未通过核验。')); END;
 IF ctx IS NOT NULL THEN
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',p.id,'origin',p.origin,'adapter_id',p.adapter_id,'verified_at',p.created_at,'context_digest',p.context_digest) ORDER BY p.created_at,p.id),'[]') INTO candidates FROM package_historical_research.proofs p WHERE p.scope_id=target_scope AND p.submission_id=target_submission AND p.outcome_id=target_outcome AND p.context_digest=design.package_technical_digest(ctx) AND package_historical_research.adapter_current(p.adapter_id);
  IF candidates='[]'::jsonb THEN gaps:=gaps||jsonb_build_array(
   jsonb_build_object('code','PACKAGE_HISTORY_ORIGINAL_TIME_PROOF_MISSING','message','缺少逐原始字节在实交前存在、本方取得及依据生效的来源证明。'),
   jsonb_build_object('code','PACKAGE_HISTORY_COMPLETE_VISUAL_RANGE_PROOF_MISSING','message','范围声明不能证明完整图文和必要条款齐备，需独立有据核验。'),
   jsonb_build_object('code','PACKAGE_HISTORY_MAXIMUM_AGGREGATION_PROOF_MISSING','message','需同权威原页明示技术满分和聚合口径，未知不能推测。'));
  END IF;
 END IF;
 SELECT count(*) INTO evidence_count FROM package_historical_research.adapters a WHERE origin='external_evidence' AND package_historical_research.adapter_current(a.id);
 IF evidence_count=0 THEN gaps:=gaps||jsonb_build_array(jsonb_build_object('code','PACKAGE_HISTORY_EXTERNAL_PROOF_ADAPTER_NOT_CONFIGURED','message','真实证明接入来源尚未配置；签名本身不证明事实真实。')); END IF;
 RETURN jsonb_build_object('schema','package-historical-admission-context/1','scope_id',target_scope,'submission_id',target_submission,'outcome_id',target_outcome,'context_digest',CASE WHEN ctx IS NULL THEN NULL ELSE design.package_technical_digest(ctx) END,
  'official_technical_value',ctx#>'{label,value}','official_maximum',ctx#>'{label,maximum}','historical_as_of',ctx#>'{submission,submitted_at}','scope_frozen_at',ctx#>'{scope,frozen_at}','label_known_at',ctx#>'{label,known_at}',
  'proofs',candidates,'blockers',gaps,'research_only',true,'formal_eligibility','unavailable','strict_prebid_eligible',false,'online_metrics_eligible',false,'formal_sample_created',false,'observed_at',clock_timestamp());
END $$;

CREATE FUNCTION package_historical_research.admit(proof uuid,actor uuid,command uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,design,pg_temp AS $$
DECLARE p package_historical_research.proofs; old package_historical_research.admissions; identity uuid:=gen_random_uuid(); doc jsonb; at timestamptz:=clock_timestamp();
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT * INTO p FROM package_historical_research.proofs WHERE id=proof;
 IF NOT FOUND THEN RAISE EXCEPTION 'package_history_proof_missing' USING ERRCODE='P0002'; END IF;
 PERFORM package_historical_research.assert_origin(p.origin,true);
 IF NOT package_historical_research.current_proof(proof) THEN RAISE EXCEPTION 'package_history_proof_stale' USING ERRCODE='55000'; END IF;
 IF NOT EXISTS(SELECT FROM design.commands c WHERE c.id=command AND c.actor_id=actor AND c.target_id=p.scope_id AND c.command_kind='package-history-admission') THEN RAISE EXCEPTION 'package_history_command_unbound' USING ERRCODE='23514'; END IF;
 SELECT * INTO old FROM package_historical_research.admissions a WHERE a.proof_id=proof;
 IF FOUND THEN RETURN old.document||jsonb_build_object('digest',old.digest); END IF;
 doc:=jsonb_build_object('schema','package-historical-research-admission/1','id',identity,'proof_id',proof,'bid_id',p.native_context->'bid_id','scope_id',p.scope_id,'scope_digest',p.native_context#>'{scope,digest}',
  'submission_id',p.submission_id,'submission_binding_digest',p.native_context#>'{submission,binding_digest}','outcome_id',p.outcome_id,'context_digest',p.context_digest,'proof_digest',p.normalized_digest,'origin',p.origin,
  'state',CASE WHEN p.origin='synthetic' THEN 'mechanism_candidate' ELSE 'retrospective_candidate' END,'historical_as_of',p.native_context#>'{submission,submitted_at}','scope_frozen_at',p.native_context#>'{scope,frozen_at}','label_known_at',p.native_context#>'{label,known_at}',
  'official_technical_value',p.native_context#>'{label,value}','technical_maximum',p.normalized#>'{scale,maximum}','aggregation',p.normalized#>'{scale,aggregation}','evidence_verified_at',p.created_at,'admitted_at',at,
  'research_only',true,'formal_eligibility','unavailable','strict_prebid_eligible',false,'online_metrics_eligible',false,'formal_sample_created',false,'training_selected',false);
 INSERT INTO package_historical_research.admissions VALUES(identity,proof,(p.native_context->>'bid_id')::uuid,p.scope_id,p.submission_id,p.outcome_id,p.origin,doc,design.package_technical_digest(doc),actor,command,at);
 INSERT INTO package_historical_research.admission_keys
 SELECT identity,'submission',p.submission_id::text UNION SELECT identity,'project',p.native_context#>>'{identity,engineering_project_id}'
 UNION SELECT identity,'text',p.native_context->>'target_text_digest'
 UNION SELECT identity,'body',v->>'digest' FROM jsonb_array_elements(p.native_context->'target_files')v
 UNION SELECT identity,'template',v FROM jsonb_array_elements_text(p.normalized#>'{grouping,template_keys}')v
 UNION SELECT identity,'near_duplicate',v FROM jsonb_array_elements_text(p.normalized#>'{grouping,near_duplicate_keys}')v;
 INSERT INTO design.audit_entries(id,actor_id,bid_id,command_id,event_type,payload) VALUES(gen_random_uuid(),actor,(p.native_context->>'bid_id')::uuid,command,'package-history.admitted',jsonb_build_object('admission_id',identity,'proof_id',proof,'origin',p.origin,'formal_sample_created',false));
 RETURN doc||jsonb_build_object('digest',design.package_technical_digest(doc));
END $$;

CREATE FUNCTION package_historical_research.admission_view(target uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE a package_historical_research.admissions;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT * INTO a FROM package_historical_research.admissions WHERE id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'package_history_admission_missing' USING ERRCODE='P0002'; END IF;
 RETURN jsonb_build_object('admission',a.document||jsonb_build_object('digest',a.digest),'current',package_historical_research.current_proof(a.proof_id));
END $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA package_historical_research FROM PUBLIC;
GRANT EXECUTE ON FUNCTION package_historical_research.admission_context(uuid,uuid,uuid),package_historical_research.admit(uuid,uuid,uuid),package_historical_research.admission_view(uuid) TO tender_api;
GRANT EXECUTE ON FUNCTION package_historical_research.verification_material(uuid,uuid,uuid,uuid),package_historical_research.record_proof(uuid,uuid,uuid,uuid,jsonb,jsonb,design.sha256) TO tender_package_history_verify;
COMMIT;
