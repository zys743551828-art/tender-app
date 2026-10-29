-- Optional fresh check DB extension. Native evidence refs are not old CAS commits.
BEGIN;
CREATE ROLE tender_native_material_registration NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE FUNCTION material_registration.record_native(target_bid uuid,target_scope uuid,expected_scope text,command uuid,packet jsonb,observation jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_registration,design,pg_temp SET TimeZone='UTC'
AS $native_evidence_registration$
DECLARE old material_registration.records;stored technical_material_store.records;context jsonb;stored_findings jsonb;
 field text;checksum text;identifier uuid;at timestamptz;result jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off' THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_native_material_registration',ARRAY['material_registration.record_native(uuid,uuid,text,uuid,jsonb,jsonb)','material_registration.read_native(uuid,uuid,text)']) THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 IF target_bid IS NULL OR target_scope IS NULL OR command IS NULL OR expected_scope IS NULL OR expected_scope !~ '^[0-9a-f]{64}$'
 OR expected_scope=repeat('0',64) OR packet IS NULL OR jsonb_typeof(packet)<>'object' OR octet_length(packet::text)>4096
 OR observation IS NULL OR jsonb_typeof(observation)<>'object' OR octet_length(observation::text)>8192 THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_PACKET_INVALID' USING ERRCODE='P0001'; END IF;
 IF NOT design.package_json_keys(packet,ARRAY['version','context_digest','context_method_digest','storage_record_id','storage_record_digest',
  'storage_packet_digest','native_recovery_method_digest','native_recovery_observation_digest','source_observation_digest','material_digest',
  'findings_digest','derivation_observation_digest','registration_method_digest'])
 OR packet->>'version' IS DISTINCT FROM 'package-native-material-registration-packet/2'
 OR jsonb_typeof(packet->'storage_record_id') IS DISTINCT FROM 'string'
 OR packet->>'storage_record_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_PACKET_INVALID' USING ERRCODE='P0001'; END IF;
 FOR field IN SELECT key FROM jsonb_each(packet) WHERE key NOT IN('version','storage_record_id') LOOP
  IF jsonb_typeof(packet->field) IS DISTINCT FROM 'string' OR packet->>field !~ '^[0-9a-f]{64}$' OR packet->>field=repeat('0',64) THEN
   RAISE EXCEPTION 'NATIVE_REGISTRATION_PACKET_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 IF NOT design.package_json_keys(observation,ARRAY['version','method_digest','storage_record_id','storage_record_digest','store_command_id',
  'store_packet_digest','context_digest','original_source_observation_digest','stored_findings_digest','stored_derivation_observation_digest',
  'fresh_initial_parse_digest','fresh_final_parse_digest','fresh_final_scope_digest','fresh_original_set_digest','observed_at',
  'native_evidence_bytes_reloaded','exact_frozen_context_recovered','current_native_parse_and_originals_rechecked','stored_scope_findings_revalidated',
  'stored_derivation_claim_consistent','page_assets_rerendered','trusted_derivation_freshly_verified','actual_human_reading_verified',
  'all_findings_claimed_confirmed','scope_changes_requested','necessary_scope_verified','native_binding_verified','input_authority_granted',
  'execution_authorized','historical_existence_verified','atomic_snapshot_verified','send_lease_granted','digest']) THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 FOREACH field IN ARRAY ARRAY['method_digest','storage_record_digest','store_packet_digest','context_digest','original_source_observation_digest',
  'stored_findings_digest','stored_derivation_observation_digest','fresh_initial_parse_digest','fresh_final_parse_digest',
  'fresh_final_scope_digest','fresh_original_set_digest','digest'] LOOP
  IF jsonb_typeof(observation->field) IS DISTINCT FROM 'string' OR observation->>field !~ '^[0-9a-f]{64}$' OR observation->>field=repeat('0',64) THEN
   RAISE EXCEPTION 'NATIVE_REGISTRATION_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 IF jsonb_typeof(observation->'store_command_id') IS DISTINCT FROM 'string'
 OR observation->>'store_command_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
 OR jsonb_typeof(observation->'all_findings_claimed_confirmed') IS DISTINCT FROM 'boolean'
 OR jsonb_typeof(observation->'scope_changes_requested') IS DISTINCT FROM 'boolean'
 OR jsonb_typeof(observation->'observed_at') IS DISTINCT FROM 'string' OR length(observation->>'observed_at')>40
 OR observation->>'observed_at' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*(Z|[+-][0-9]{2}:[0-9]{2})$' THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 BEGIN
  PERFORM (observation->>'observed_at')::timestamptz;
 EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_OBSERVATION_INVALID' USING ERRCODE='P0001';
 END;
 checksum:=encode(sha256(convert_to(design.package_canonical_json(observation-'digest'),'UTF8')),'hex');
 IF observation->>'version' IS DISTINCT FROM 'package-native-material-evidence-recovery/1'
 OR observation->>'digest' IS DISTINCT FROM packet->>'native_recovery_observation_digest' OR checksum IS DISTINCT FROM observation->>'digest'
 OR observation->>'method_digest' IS DISTINCT FROM packet->>'native_recovery_method_digest'
 OR observation->>'storage_record_id' IS DISTINCT FROM packet->>'storage_record_id'
 OR observation->>'storage_record_digest' IS DISTINCT FROM packet->>'storage_record_digest'
 OR observation->>'store_packet_digest' IS DISTINCT FROM packet->>'storage_packet_digest'
 OR observation->>'context_digest' IS DISTINCT FROM packet->>'context_digest'
 OR observation->>'original_source_observation_digest' IS DISTINCT FROM packet->>'source_observation_digest'
 OR observation->>'stored_findings_digest' IS DISTINCT FROM packet->>'findings_digest'
 OR observation->>'stored_derivation_observation_digest' IS DISTINCT FROM packet->>'derivation_observation_digest' THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 FOREACH field IN ARRAY ARRAY['native_evidence_bytes_reloaded','exact_frozen_context_recovered','current_native_parse_and_originals_rechecked',
  'stored_scope_findings_revalidated','stored_derivation_claim_consistent'] LOOP
  IF observation->field IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'NATIVE_REGISTRATION_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 FOREACH field IN ARRAY ARRAY['page_assets_rerendered','trusted_derivation_freshly_verified','actual_human_reading_verified','necessary_scope_verified',
  'native_binding_verified','input_authority_granted','execution_authorized','historical_existence_verified','atomic_snapshot_verified','send_lease_granted'] LOOP
  IF observation->field IS DISTINCT FROM 'false'::jsonb THEN RAISE EXCEPTION 'NATIVE_REGISTRATION_OBSERVATION_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 PERFORM pg_advisory_xact_lock(hashtextextended('material_registration:'||command::text,0));
 SELECT * INTO old FROM material_registration.records WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.bid_id<>target_bid OR old.scope_id<>target_scope OR old.document->>'version'<>'package-native-material-registration/2'
  OR old.document->>'scope_digest'<>expected_scope OR old.document->'packet'<>packet OR old.document->'recovery_observation'<>observation THEN
   RAISE EXCEPTION 'NATIVE_REGISTRATION_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 IF NOT EXISTS(SELECT FROM design.bid_package_technical_scopes WHERE bid_id=target_bid AND id=target_scope AND digest=expected_scope) THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_SCOPE_MISMATCH' USING ERRCODE='P0001'; END IF;
 SELECT * INTO stored FROM technical_material_store.records WHERE id=(packet->>'storage_record_id')::uuid
  AND bid_id=target_bid AND scope_id=target_scope AND digest=packet->>'storage_record_digest';
 IF stored.id IS NULL OR stored.command_id::text IS DISTINCT FROM observation->>'store_command_id'
 OR stored.document->>'scope_digest' IS DISTINCT FROM expected_scope
 OR stored.document->>'packet_digest' IS DISTINCT FROM packet->>'storage_packet_digest'
 OR stored.document#>>'{packet,context_digest}' IS DISTINCT FROM packet->>'context_digest'
 OR stored.document#>>'{packet,context_method_digest}' IS DISTINCT FROM packet->>'context_method_digest'
 OR stored.document#>>'{packet,source_observation_digest}' IS DISTINCT FROM packet->>'source_observation_digest'
 OR stored.document#>>'{packet,findings_digest}' IS DISTINCT FROM packet->>'findings_digest'
 OR stored.document#>>'{packet,derivation_observation_digest}' IS DISTINCT FROM packet->>'derivation_observation_digest' THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_STORAGE_MISMATCH' USING ERRCODE='P0001'; END IF;
 BEGIN
  SELECT convert_from(data,'UTF8')::jsonb INTO context FROM technical_material_store.objects
   WHERE sha=stored.document#>>'{packet,context_object,sha256}';
  SELECT convert_from(data,'UTF8')::jsonb INTO stored_findings FROM technical_material_store.objects
   WHERE sha=stored.document#>>'{packet,findings_object,sha256}';
 EXCEPTION WHEN invalid_text_representation OR character_not_in_repertoire THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_STORAGE_MISMATCH' USING ERRCODE='P0001';
 END;
 IF context->>'source_material_digest' IS DISTINCT FROM packet->>'material_digest' OR context->>'digest' IS DISTINCT FROM packet->>'context_digest' THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_STORAGE_MISMATCH' USING ERRCODE='P0001'; END IF;
 IF observation->'all_findings_claimed_confirmed' IS DISTINCT FROM stored_findings->'all_findings_claimed_confirmed'
 OR observation->'scope_changes_requested' IS DISTINCT FROM stored_findings->'scope_changes_requested' THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_STORAGE_MISMATCH' USING ERRCODE='P0001'; END IF;
 identifier:=gen_random_uuid();at:=clock_timestamp();
 result:=jsonb_build_object('version','package-native-material-registration/2','registration_id',identifier::text,
  'bid_id',target_bid::text,'scope_id',target_scope::text,'scope_digest',expected_scope,'command_id',command::text,
  'recorded_by',session_user::text,'recorded_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'packet',packet,'packet_digest',encode(sha256(convert_to(design.package_canonical_json(packet),'UTF8')),'hex'),
  'recovery_observation',observation,'status','awaiting_independent_verification','necessary_scope_verified',false,
  'native_binding_verified',false,'input_authority_granted',false,'execution_authorized',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_registration.records VALUES(identifier,target_bid,target_scope,command,session_user,result,checksum);
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$native_evidence_registration$;

CREATE FUNCTION material_registration.read_native(target_bid uuid,target_command uuid,expected_packet_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_registration,design,pg_temp SET TimeZone='UTC'
AS $native_evidence_registration_read$
DECLARE stored material_registration.records;
BEGIN
 IF current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on' THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_OWNED_READ_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_native_material_registration',ARRAY['material_registration.record_native(uuid,uuid,text,uuid,jsonb,jsonb)','material_registration.read_native(uuid,uuid,text)']) THEN
  RAISE EXCEPTION 'NATIVE_REGISTRATION_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 SELECT * INTO stored FROM material_registration.records r WHERE r.bid_id=target_bid AND r.command_id=target_command AND r.actor=session_user
  AND r.document->>'version'='package-native-material-registration/2' AND r.document->>'packet_digest'=expected_packet_digest;
 IF NOT FOUND THEN RAISE EXCEPTION 'NATIVE_REGISTRATION_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 RETURN jsonb_build_object('document',stored.document,'digest',stored.digest::text);
END;
$native_evidence_registration_read$;
REVOKE ALL ON FUNCTION material_registration.record_native(uuid,uuid,text,uuid,jsonb,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION material_registration.read_native(uuid,uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA material_registration TO tender_native_material_registration;
GRANT EXECUTE ON FUNCTION material_registration.record_native(uuid,uuid,text,uuid,jsonb,jsonb),material_registration.read_native(uuid,uuid,text) TO tender_native_material_registration;
COMMIT;
