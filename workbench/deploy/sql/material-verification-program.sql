-- Optional fresh isolated extension: authenticated program facts, no input grants.
BEGIN;
CREATE ROLE tender_material_verification_program NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE TABLE material_verification.program_results(
 id uuid PRIMARY KEY,command_row_id uuid NOT NULL UNIQUE REFERENCES material_verification.commands(id),
 actor name NOT NULL,actor_oid oid NOT NULL,bid_id uuid NOT NULL,
 observation jsonb NOT NULL,document jsonb NOT NULL,digest design.sha256 NOT NULL,
 CHECK(octet_length(observation::text)<=8388608 AND octet_length(document::text)<=16384)
);
CREATE TRIGGER immutable_verification_program_result BEFORE UPDATE OR DELETE ON material_verification.program_results
 FOR EACH ROW EXECUTE FUNCTION design.append_only();

CREATE FUNCTION material_verification.program_state(target_command uuid,expected_command_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,material_verification,design,pg_temp SET TimeZone='UTC'
AS $verification_program_state$
DECLARE task material_verification.commands;c material_verification.cases;p material_verification.profiles;
 h material_verification.profile_heads;ch material_verification.case_heads;r material_registration.records;
 a scope_review_issuer.attestations;rc scope_review_issuer.cases;rp scope_review_issuer.profiles;
 rh scope_review_issuer.profile_heads;rch scope_review_issuer.case_heads;done material_verification.program_results;
 at timestamptz;target_identity boolean;program_active boolean;case_active boolean;review_active boolean;
BEGIN
 SELECT * INTO task FROM material_verification.commands WHERE command_id=target_command AND digest=expected_command_digest;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO c FROM material_verification.cases WHERE id=task.case_id;
 SELECT * INTO p FROM material_verification.profiles WHERE id=c.profile_id;
 SELECT * INTO h FROM material_verification.profile_heads WHERE target_login=p.target_login;
 SELECT * INTO ch FROM material_verification.case_heads WHERE case_id=c.id;
 SELECT * INTO r FROM material_registration.records WHERE id=c.registration_id AND digest=c.registration_digest;
 SELECT * INTO a FROM scope_review_issuer.attestations WHERE id=c.review_attestation_id AND digest=c.review_attestation_digest;
 SELECT * INTO rc FROM scope_review_issuer.cases WHERE id=a.case_id;
 SELECT * INTO rp FROM scope_review_issuer.profiles WHERE id=rc.profile_id;
 SELECT * INTO rh FROM scope_review_issuer.profile_heads WHERE login_name=rp.login_name;
 SELECT * INTO rch FROM scope_review_issuer.case_heads WHERE case_id=rc.id;
 SELECT * INTO done FROM material_verification.program_results WHERE command_row_id=task.id;
 at:=clock_timestamp();
 target_identity:=coalesce(p.target_login=session_user AND p.target_login_oid=(SELECT oid FROM pg_roles WHERE rolname=session_user),false);
 program_active:=coalesce(target_identity AND h.profile_id=p.id AND h.enabled AND h.revision::text=task.document->>'profile_head_revision'
  AND at>=p.valid_from AND at<p.valid_until AND p.database_name=current_database()
  AND p.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database()),false);
 case_active:=coalesce(ch.enabled AND ch.revision::text=task.document->>'case_head_revision' AND at>=c.valid_from AND at<c.valid_until
  AND EXISTS(SELECT FROM pg_roles WHERE oid=c.request_login_oid AND rolname=c.request_login AND rolcanlogin)
  AND scope_review_issuer.role_policy(c.request_login,'tender_material_verification_commands',ARRAY['material_verification.begin_command(uuid,uuid,text)','material_verification.read_command(uuid,uuid,text)']),false);
 review_active:=coalesce(r.id IS NOT NULL AND a.id IS NOT NULL AND rc.id IS NOT NULL AND rp.id IS NOT NULL
  AND rh.profile_id=rp.id AND rh.enabled AND rch.enabled AND at>=rc.valid_from AND at<rc.valid_until
  AND at>=rp.valid_from AND at<rp.valid_until AND rp.database_name=current_database()
  AND rp.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND a.document->>'version'='package-native-evidence-attestation/2' AND r.document->>'version'='package-native-material-registration/2'
  AND a.document->>'registration_id'=r.id::text AND a.document->>'registration_digest'=r.digest::text
  AND scope_review_issuer.role_policy(rp.login_name,'tender_native_evidence_issuer',ARRAY['scope_review_issuer.attest_native(uuid,uuid,jsonb)']),false);
 RETURN jsonb_build_object('command',jsonb_build_object('document',task.document,'digest',task.digest::text),
  'configuration',jsonb_build_object('profile_id',p.id::text,'case_id',c.id::text,'target_login',p.target_login::text,
   'target_login_oid',p.target_login_oid::bigint,'origin',p.origin,'controller_method_digest',p.controller_method_digest::text,
   'authority_policy_digest',p.authority_policy_digest::text),
  'review_arguments',jsonb_build_object('registration_command_id',r.command_id::text,'expected_registration_packet_digest',r.document->>'packet_digest',
   'expected_registration_digest',r.digest::text,'issuer_command_id',a.command_id::text,
   'expected_issuer_reference_digest',encode(sha256(convert_to(design.package_canonical_json(a.document->'reference'),'UTF8')),'hex'),
   'expected_issuer_digest',a.digest::text,'expected_context_digest',task.document->>'context_digest',
   'bid_id',task.bid_id::text,'scope_id',task.document->>'scope_id','expected_scope_digest',task.document->>'scope_digest'),
  'current',jsonb_build_object('observed_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'target_identity_matches',target_identity,
   'program_configuration_current',program_active,'case_current',case_active,'review_current',review_active,
   'profile_head_revision',h.revision,'case_head_revision',ch.revision,'review_profile_head_revision',rh.revision,
   'review_case_head_revision',rch.revision,'program_runtime_authenticated',true,'necessary_scope_verified',false,
   'native_binding_verified',false,'input_authority_granted',false,'execution_authorized',false),
  'result',CASE WHEN done.id IS NULL THEN NULL ELSE jsonb_build_object('document',done.document,'digest',done.digest::text,'observation',done.observation) END);
END;
$verification_program_state$;
REVOKE ALL ON FUNCTION material_verification.program_state(uuid,text) FROM PUBLIC;

CREATE FUNCTION material_verification.program_context(target_command uuid,expected_command_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_verification,design,pg_temp SET TimeZone='UTC'
AS $verification_program_context$
DECLARE state jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on' THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_OWNED_READ_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_verification_program',ARRAY['material_verification.program_context(uuid,text)','material_verification.record_program_result(uuid,text,jsonb)']) THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 state:=material_verification.program_state(target_command,expected_command_digest);
 IF state IS NULL THEN RAISE EXCEPTION 'VERIFICATION_PROGRAM_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 IF state#>'{current,target_identity_matches}' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_TARGET_IDENTITY_MISMATCH' USING ERRCODE='42501'; END IF;
 RETURN state;
END;
$verification_program_context$;

CREATE FUNCTION material_verification.record_program_result(target_command uuid,expected_command_digest text,observation jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_verification,design,pg_temp SET TimeZone='UTC'
AS $verification_program_record$
DECLARE state jsonb;task material_verification.commands;old material_verification.program_results;
 c material_verification.cases;p material_verification.profiles;r material_registration.records;
 a scope_review_issuer.attestations;rc scope_review_issuer.cases;rp scope_review_issuer.profiles;
 scope design.bid_package_technical_scopes;own design.bid_package_revisions;authority design.bid_package_revisions;
 inventory design.bid_package_requirement_inventories;stored technical_material_store.records;
 capsule jsonb;initial_review jsonb;final_review jsonb;live jsonb;report jsonb;value jsonb;field text;
 identifier uuid;at timestamptz;result jsonb;checksum text;expected_status text;final_observed_at timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off' THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_verification_program',ARRAY['material_verification.program_context(uuid,text)','material_verification.record_program_result(uuid,text,jsonb)']) THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 IF observation IS NULL OR jsonb_typeof(observation)<>'object' OR octet_length(observation::text)>8388608
 OR NOT design.package_json_keys(observation,ARRAY['version','command_id','command_digest','program_method_digest','port_method_digest',
  'policy_digest','controller_method_digest','byte_profile','verified_material','digest'])
 OR observation->>'version' IS DISTINCT FROM 'material-verification-execution/1'
 OR observation->>'command_id' IS DISTINCT FROM target_command::text OR observation->>'command_digest' IS DISTINCT FROM expected_command_digest THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 FOREACH field IN ARRAY ARRAY['command_digest','program_method_digest','port_method_digest','policy_digest','controller_method_digest','digest'] LOOP
  IF jsonb_typeof(observation->field) IS DISTINCT FROM 'string' OR observation->>field !~ '^[0-9a-f]{64}$' OR observation->>field=repeat('0',64) THEN
   RAISE EXCEPTION 'VERIFICATION_PROGRAM_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 IF encode(sha256(convert_to(design.package_canonical_json(observation-'digest'),'UTF8')),'hex') IS DISTINCT FROM observation->>'digest' THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 SELECT * INTO task FROM material_verification.commands WHERE command_id=target_command AND digest=expected_command_digest;
 IF NOT FOUND THEN RAISE EXCEPTION 'VERIFICATION_PROGRAM_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 SELECT * INTO c FROM material_verification.cases WHERE id=task.case_id;
 SELECT * INTO p FROM material_verification.profiles WHERE id=c.profile_id;
 IF p.target_login IS DISTINCT FROM session_user OR p.target_login_oid IS DISTINCT FROM (SELECT oid FROM pg_roles WHERE rolname=session_user) THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_TARGET_IDENTITY_MISMATCH' USING ERRCODE='42501'; END IF;
 SELECT * INTO old FROM material_verification.program_results WHERE command_row_id=task.id;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user) OR old.observation<>observation THEN
   RAISE EXCEPTION 'VERIFICATION_PROGRAM_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text,'observation',old.observation);
 END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 PERFORM design.lock_worker_bid(task.bid_id);
 PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(hashtextextended('material_verification_result:'||target_command::text,0));
 SELECT * INTO old FROM material_verification.program_results WHERE command_row_id=task.id;
 IF FOUND THEN
  IF old.actor<>session_user OR old.actor_oid<>(SELECT oid FROM pg_roles WHERE rolname=session_user) OR old.observation<>observation THEN
   RAISE EXCEPTION 'VERIFICATION_PROGRAM_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text,'observation',old.observation);
 END IF;
 PERFORM 1 FROM material_verification.profile_heads WHERE target_login=p.target_login FOR SHARE;
 PERFORM 1 FROM material_verification.case_heads WHERE case_id=c.id FOR SHARE;
 SELECT * INTO a FROM scope_review_issuer.attestations WHERE id=c.review_attestation_id AND digest=c.review_attestation_digest;
 SELECT * INTO rc FROM scope_review_issuer.cases WHERE id=a.case_id;
 SELECT * INTO rp FROM scope_review_issuer.profiles WHERE id=rc.profile_id;
 PERFORM 1 FROM scope_review_issuer.profile_heads WHERE login_name=rp.login_name FOR SHARE;
 PERFORM 1 FROM scope_review_issuer.case_heads WHERE case_id=rc.id FOR SHARE;
 state:=material_verification.program_state(target_command,expected_command_digest);
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_verification_program',ARRAY['material_verification.program_context(uuid,text)','material_verification.record_program_result(uuid,text,jsonb)'])
 OR state#>'{current,target_identity_matches}' IS DISTINCT FROM 'true'::jsonb
 OR state#>'{current,program_configuration_current}' IS DISTINCT FROM 'true'::jsonb
 OR state#>'{current,case_current}' IS DISTINCT FROM 'true'::jsonb OR state#>'{current,review_current}' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_CONFIGURATION_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 IF observation->>'controller_method_digest' IS DISTINCT FROM p.controller_method_digest::text
 OR observation->>'policy_digest' IS DISTINCT FROM p.authority_policy_digest::text
 OR (p.origin='synthetic_mechanism' AND observation->>'byte_profile' IS DISTINCT FROM 'development_s3')
 OR (p.origin='current_prebid' AND observation->>'byte_profile' IS DISTINCT FROM 'oss_hangzhou') THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_POLICY_MISMATCH' USING ERRCODE='P0001'; END IF;
 capsule:=observation->'verified_material';
 IF jsonb_typeof(capsule) IS DISTINCT FROM 'object' OR NOT design.package_json_keys(capsule,ARRAY[
  'version','method_digest','context_digest','findings_digest','initial_current_review','live_derivation','final_current_review','status',
  'actual_current_derivation_and_review_combined','trusted_derivation_bound','issuer_state_unchanged_across_all_stages',
  'exact_frozen_context_and_report_preserved','actual_human_reading_verified','necessary_scope_verified','native_binding_verified',
  'input_authority_granted','execution_authorized','historical_existence_verified','atomic_snapshot_verified','send_lease_granted','digest'])
 OR capsule->>'version' IS DISTINCT FROM 'fusion-live-verified-material/1'
 OR capsule->>'method_digest' IS DISTINCT FROM p.controller_method_digest::text THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 FOREACH field IN ARRAY ARRAY['actual_current_derivation_and_review_combined','trusted_derivation_bound','issuer_state_unchanged_across_all_stages','exact_frozen_context_and_report_preserved'] LOOP
  IF capsule->field IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'VERIFICATION_PROGRAM_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 FOREACH field IN ARRAY ARRAY['actual_human_reading_verified','necessary_scope_verified','native_binding_verified','input_authority_granted','execution_authorized','historical_existence_verified','atomic_snapshot_verified','send_lease_granted'] LOOP
  IF capsule->field IS DISTINCT FROM 'false'::jsonb THEN RAISE EXCEPTION 'VERIFICATION_PROGRAM_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 initial_review:=capsule->'initial_current_review';final_review:=capsule->'final_current_review';live:=capsule->'live_derivation';
 IF jsonb_typeof(final_review#>'{current_recovery,observed_at}') IS DISTINCT FROM 'string'
 OR length(final_review#>>'{current_recovery,observed_at}')>40
 OR final_review#>>'{current_recovery,observed_at}' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*(Z|[+-][0-9]{2}:[0-9]{2})$' THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 BEGIN
  final_observed_at:=(final_review#>>'{current_recovery,observed_at}')::timestamptz;
 EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_OBSERVATION_INVALID' USING ERRCODE='P0001';
 END;
 IF final_observed_at IS NULL OR final_observed_at>clock_timestamp()+interval '5 seconds'
 OR final_observed_at<clock_timestamp()-interval '120 seconds' THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_OBSERVATION_STALE' USING ERRCODE='P0001'; END IF;
 FOR value IN SELECT * FROM jsonb_array_elements(jsonb_build_array(capsule,initial_review,final_review,live,
  initial_review->'issuer_before',initial_review->'issuer_after',final_review->'issuer_before',final_review->'issuer_after')) LOOP
  IF jsonb_typeof(value) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'VERIFICATION_PROGRAM_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
  IF value->>'digest' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(value-'digest'),'UTF8')),'hex') THEN
   RAISE EXCEPTION 'VERIFICATION_PROGRAM_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 SELECT * INTO r FROM material_registration.records WHERE id=c.registration_id AND digest=c.registration_digest;
 SELECT * INTO stored FROM technical_material_store.records WHERE id=(r.document#>>'{packet,storage_record_id}')::uuid
  AND digest=r.document#>>'{packet,storage_record_digest}';
 BEGIN
  SELECT convert_from(data,'UTF8')::jsonb INTO report FROM technical_material_store.objects
   WHERE sha=stored.document#>>'{packet,findings_object,sha256}';
 EXCEPTION WHEN invalid_text_representation OR character_not_in_repertoire THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_MATERIAL_MISMATCH' USING ERRCODE='P0001';
 END;
 expected_status:=CASE WHEN report->'scope_changes_requested'='true'::jsonb THEN 'scope_changes_requested'
  WHEN report->'all_findings_claimed_confirmed'='false'::jsonb THEN 'review_incomplete'
  WHEN a.document->>'issuer_origin'='synthetic_mechanism' THEN 'synthetic_review_only' ELSE 'configured_review_confirmed' END;
 IF stored.id IS NULL OR report IS NULL OR p.origin IS DISTINCT FROM a.document->>'issuer_origin'
 OR capsule->>'context_digest' IS DISTINCT FROM task.document->>'context_digest'
 OR capsule->>'findings_digest' IS DISTINCT FROM r.document#>>'{packet,findings_digest}'
 OR capsule->>'findings_digest' IS DISTINCT FROM report->>'digest'
 OR capsule->>'status' IS DISTINCT FROM expected_status
 OR live->>'version' IS DISTINCT FROM 'fusion-exact-context-derivation/1'
 OR live->>'context_digest' IS DISTINCT FROM capsule->>'context_digest'
 OR live->>'context_method_digest' IS DISTINCT FROM r.document#>>'{packet,context_method_digest}'
 OR live->'trusted_derivation_bound' IS DISTINCT FROM 'true'::jsonb
 OR live->'fresh_native_facts_checked_after_all_render_sessions' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_MATERIAL_MISMATCH' USING ERRCODE='P0001'; END IF;
 FOR value IN SELECT * FROM jsonb_array_elements(jsonb_build_array(initial_review,final_review)) LOOP
  IF value->>'version' IS DISTINCT FROM 'package-native-current-review/1'
  OR value->>'context_digest' IS DISTINCT FROM capsule->>'context_digest'
  OR value->>'registration_digest' IS DISTINCT FROM c.registration_digest::text
  OR value->>'scope_digest' IS DISTINCT FROM task.document->>'scope_digest'
  OR value->>'status' IS DISTINCT FROM expected_status
  OR value->'all_findings_claimed_confirmed' IS DISTINCT FROM report->'all_findings_claimed_confirmed'
  OR value->'scope_changes_requested' IS DISTINCT FROM report->'scope_changes_requested'
  OR value->'current_native_sources_rechecked' IS DISTINCT FROM 'true'::jsonb
  OR value->'input_authority_granted' IS DISTINCT FROM 'false'::jsonb THEN
   RAISE EXCEPTION 'VERIFICATION_PROGRAM_MATERIAL_MISMATCH' USING ERRCODE='P0001'; END IF;
 END LOOP;
 FOR value IN SELECT * FROM jsonb_array_elements(jsonb_build_array(initial_review->'issuer_before',initial_review->'issuer_after',final_review->'issuer_before',final_review->'issuer_after')) LOOP
  IF value->'record' IS DISTINCT FROM jsonb_build_object('document',a.document,'digest',a.digest::text)
  OR value#>'{current,issuer_active}' IS DISTINCT FROM 'true'::jsonb OR value#>'{current,case_active}' IS DISTINCT FROM 'true'::jsonb
  OR value#>'{current,profile_head_revision}' IS DISTINCT FROM state#>'{current,review_profile_head_revision}'
  OR value#>'{current,case_head_revision}' IS DISTINCT FROM state#>'{current,review_case_head_revision}'
  OR ((value->'current')-'observed_at') IS DISTINCT FROM ((initial_review#>'{issuer_before,current}')-'observed_at') THEN
   RAISE EXCEPTION 'VERIFICATION_PROGRAM_REVIEW_STATE_CHANGED' USING ERRCODE='P0001'; END IF;
 END LOOP;
 SELECT * INTO scope FROM design.bid_package_technical_scopes WHERE id=(task.document->>'scope_id')::uuid
  AND bid_id=task.bid_id AND digest=task.document->>'scope_digest';
 SELECT * INTO own FROM design.bid_package_revisions WHERE id=scope.revision_id;
 SELECT * INTO inventory FROM design.bid_package_requirement_inventories WHERE id=scope.inventory_id;
 SELECT * INTO authority FROM design.bid_package_revisions WHERE id=inventory.authority_revision_id;
 PERFORM 1 FROM retrieval.source_heads sh WHERE sh.source_id IN(
  SELECT n.id FROM retrieval.source_nodes n WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(own.id,authority.id))
  UNION SELECT ancestors.ancestor_id FROM retrieval.source_ancestors ancestors JOIN retrieval.source_nodes n ON n.id=ancestors.source_id
   WHERE n.document_version_id IN(SELECT document_version_id FROM design.bid_package_members WHERE revision_id IN(own.id,authority.id))
 ) ORDER BY sh.source_id FOR SHARE OF sh;
 IF scope.id IS NULL OR own.id IS NULL OR authority.id IS NULL OR inventory.id IS NULL
 OR NOT EXISTS(SELECT FROM design.bid_profiles WHERE bid_id=task.bid_id AND archived_at IS NULL AND phase NOT IN('submitted','closed','terminated') AND current_rule_set_id=inventory.rule_set_id)
 OR EXISTS(SELECT FROM design.submission_heads WHERE bid_id=task.bid_id)
 OR own.identity_digest::text IS DISTINCT FROM design.identity_snapshot_v2(task.bid_id)->>'digest'
 OR design.identity_snapshot_v2(task.bid_id)->>'binding_status' IS DISTINCT FROM 'confirmed'
 OR authority.identity_digest IS DISTINCT FROM own.identity_digest
 OR NOT EXISTS(SELECT FROM design.bid_package_heads WHERE package_id=own.package_id AND revision_id=own.id AND digest=own.digest)
 OR NOT EXISTS(SELECT FROM design.bid_package_heads WHERE package_id=authority.package_id AND revision_id=authority.id AND digest=authority.digest)
 OR NOT EXISTS(SELECT FROM design.bid_package_requirement_heads WHERE target_revision_id=own.id AND inventory_id=inventory.id AND digest=inventory.digest)
 OR inventory.manifest->'source_snapshot' IS DISTINCT FROM design.bid_requirement_source_snapshot(own.id,authority.id) THEN
  RAISE EXCEPTION 'VERIFICATION_PROGRAM_CURRENT_SOURCE_CHANGED' USING ERRCODE='P0001'; END IF;
 identifier:=gen_random_uuid();at:=clock_timestamp();
 result:=jsonb_build_object('version','material-verification-program-result/1','result_id',identifier::text,
  'command_row_id',task.id::text,'command_id',task.command_id::text,'command_digest',task.digest::text,
  'profile_id',p.id::text,'case_id',c.id::text,'origin',p.origin,'bid_id',task.bid_id::text,
  'scope_id',task.document->>'scope_id','scope_digest',task.document->>'scope_digest','context_digest',capsule->>'context_digest',
  'findings_digest',report->>'digest','registration_id',r.id::text,'registration_digest',r.digest::text,
  'review_attestation_id',a.id::text,'review_attestation_digest',a.digest::text,
  'recorded_by',session_user::text,'recorded_by_oid',(SELECT oid::bigint FROM pg_roles WHERE rolname=session_user),
  'recorded_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'observation_digest',observation->>'digest',
  'program_method_digest',observation->>'program_method_digest','port_method_digest',observation->>'port_method_digest',
  'controller_method_digest',p.controller_method_digest::text,'policy_digest',p.authority_policy_digest::text,
  'status','program_verification_recorded','review_status',expected_status,'program_runtime_authenticated',true,
  'necessary_scope_verified',false,'native_binding_verified',false,'input_authority_granted',false,'execution_authorized',false,
  'actual_human_reading_verified',false,'historical_existence_verified',false,'atomic_snapshot_verified',false,'send_lease_granted',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_verification.program_results VALUES(identifier,task.id,session_user,(SELECT oid FROM pg_roles WHERE rolname=session_user),task.bid_id,observation,result,checksum);
 RETURN jsonb_build_object('document',result,'digest',checksum,'observation',observation);
END;
$verification_program_record$;
REVOKE ALL ON FUNCTION material_verification.program_context(uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION material_verification.record_program_result(uuid,text,jsonb) FROM PUBLIC;
GRANT USAGE ON SCHEMA material_verification TO tender_material_verification_program;
GRANT EXECUTE ON FUNCTION material_verification.program_context(uuid,text),material_verification.record_program_result(uuid,text,jsonb) TO tender_material_verification_program;
COMMIT;
