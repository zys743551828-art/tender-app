-- Optional fresh isolated DB extension for independent native-evidence issuers.
BEGIN;
CREATE ROLE tender_native_evidence_issuer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE tender_native_evidence_verify NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE FUNCTION scope_review_issuer.attest_native(target_case uuid,command uuid,reference jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,scope_review_issuer,design,pg_temp SET TimeZone='UTC'
AS $scope_issuer_attest$
DECLARE old scope_review_issuer.attestations;p scope_review_issuer.profiles;h scope_review_issuer.profile_heads;
 c scope_review_issuer.cases;ch scope_review_issuer.case_heads;r material_registration.records;
 at timestamptz;identifier uuid;result jsonb;checksum text;item record;stored technical_material_store.records;report jsonb;
BEGIN
 IF current_setting('transaction_read_only')<>'off' OR current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_native_evidence_issuer',ARRAY['scope_review_issuer.attest_native(uuid,uuid,jsonb)']) THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 IF target_case IS NULL OR command IS NULL OR reference IS NULL OR jsonb_typeof(reference)<>'object'
 OR octet_length(reference::text)>4096 OR NOT design.package_json_keys(reference,ARRAY['version','context_digest','review_digest',
  'findings_digest','findings_method_digest','native_store_method_digest','storage_record_id','storage_record_digest','storage_packet_digest','registration_id','registration_digest','registration_method_digest'])
 OR reference->>'version' IS DISTINCT FROM 'package-native-evidence-attestation-reference/2' THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 FOR item IN SELECT key,value FROM jsonb_each(reference) WHERE key NOT IN('version','storage_record_id','registration_id') LOOP
  IF jsonb_typeof(item.value)<>'string' OR item.value#>>'{}' !~ '^[0-9a-f]{64}$' OR item.value#>>'{}'=repeat('0',64) THEN
   RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 IF jsonb_typeof(reference->'storage_record_id') IS DISTINCT FROM 'string'
 OR reference->>'storage_record_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
 OR jsonb_typeof(reference->'registration_id') IS DISTINCT FROM 'string'
 OR reference->>'registration_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('scope_review_issuer:'||command::text,0));
 SELECT * INTO old FROM scope_review_issuer.attestations WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.case_id<>target_case OR old.document->'reference'<>reference THEN
   RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 at:=clock_timestamp();
 SELECT * INTO h FROM scope_review_issuer.profile_heads WHERE login_name=session_user;
 SELECT * INTO p FROM scope_review_issuer.profiles WHERE id=h.profile_id AND login_name=session_user;
 IF p.id IS NULL OR h.enabled IS DISTINCT FROM true OR at<p.valid_from OR at>=p.valid_until
 OR p.database_name<>current_database() OR p.database_oid<>(SELECT oid FROM pg_database WHERE datname=current_database()) THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_PROFILE_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO c FROM scope_review_issuer.cases WHERE id=target_case AND profile_id=p.id;
 SELECT * INTO ch FROM scope_review_issuer.case_heads WHERE case_id=c.id;
 IF c.id IS NULL OR ch.enabled IS DISTINCT FROM true OR at<c.valid_from OR at>=c.valid_until THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_CASE_UNAVAILABLE' USING ERRCODE='P0001'; END IF;
 SELECT * INTO r FROM material_registration.records WHERE id=c.registration_id AND digest=c.registration_digest;
 IF r.id IS NULL OR r.document#>>'{packet,context_digest}' IS DISTINCT FROM c.context_digest::text
 OR reference->>'context_digest' IS DISTINCT FROM c.context_digest::text OR reference->>'review_digest' IS DISTINCT FROM c.review_digest::text
 OR reference->>'findings_method_digest' IS DISTINCT FROM p.findings_method_digest::text
 OR reference->>'native_store_method_digest' IS DISTINCT FROM p.store_method_digest::text THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_CASE_REFERENCE_MISMATCH' USING ERRCODE='P0001'; END IF;
 IF r.document->>'version' IS DISTINCT FROM 'package-native-material-registration/2'
 OR reference->>'registration_id' IS DISTINCT FROM r.id::text OR reference->>'registration_digest' IS DISTINCT FROM r.digest::text
 OR reference->>'registration_method_digest' IS DISTINCT FROM r.document#>>'{packet,registration_method_digest}'
 OR reference->>'storage_record_id' IS DISTINCT FROM r.document#>>'{packet,storage_record_id}'
 OR reference->>'storage_record_digest' IS DISTINCT FROM r.document#>>'{packet,storage_record_digest}'
 OR reference->>'storage_packet_digest' IS DISTINCT FROM r.document#>>'{packet,storage_packet_digest}'
 OR reference->>'findings_digest' IS DISTINCT FROM r.document#>>'{packet,findings_digest}' THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_CASE_REFERENCE_MISMATCH' USING ERRCODE='P0001'; END IF;
 SELECT * INTO stored FROM technical_material_store.records WHERE id=(reference->>'storage_record_id')::uuid
  AND digest=reference->>'storage_record_digest' AND bid_id=r.bid_id AND scope_id=r.scope_id;
 IF stored.id IS NULL OR stored.document->>'scope_digest' IS DISTINCT FROM r.document->>'scope_digest'
 OR stored.document->>'packet_digest' IS DISTINCT FROM reference->>'storage_packet_digest'
 OR stored.document#>>'{packet,store_method_digest}' IS DISTINCT FROM reference->>'native_store_method_digest'
 OR stored.document#>>'{packet,context_digest}' IS DISTINCT FROM reference->>'context_digest'
 OR stored.document#>>'{packet,findings_digest}' IS DISTINCT FROM reference->>'findings_digest' THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_CASE_REFERENCE_MISMATCH' USING ERRCODE='P0001'; END IF;
 BEGIN
  SELECT convert_from(data,'UTF8')::jsonb INTO report FROM technical_material_store.objects
   WHERE sha=stored.document#>>'{packet,findings_object,sha256}';
 EXCEPTION WHEN invalid_text_representation OR character_not_in_repertoire THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_CASE_REFERENCE_MISMATCH' USING ERRCODE='P0001';
 END;
 IF report->>'digest' IS DISTINCT FROM reference->>'findings_digest'
 OR report->>'context_digest' IS DISTINCT FROM reference->>'context_digest'
 OR report->>'review_digest' IS DISTINCT FROM reference->>'review_digest'
 OR report->>'method_digest' IS DISTINCT FROM reference->>'findings_method_digest' THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_CASE_REFERENCE_MISMATCH' USING ERRCODE='P0001'; END IF;
 identifier:=gen_random_uuid();
 result:=jsonb_build_object('version','package-native-evidence-attestation/2','attestation_id',identifier::text,
  'case_id',c.id::text,'command_id',command::text,'profile_id',p.id::text,'subject_id',p.subject_id::text,
  'issuer_kind',p.issuer_kind,'issuer_origin',p.origin,'authority_policy_digest',p.authority_policy_digest::text,
  'profile_digest',encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex'),
  'case_digest',encode(sha256(convert_to(design.package_canonical_json(to_jsonb(c)),'UTF8')),'hex'),
  'registration_id',r.id::text,'registration_digest',r.digest::text,'bid_id',r.bid_id::text,
  'scope_id',r.scope_id::text,'recorded_by',session_user::text,'recorded_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'reference',reference,'status','issuer_attestation_recorded','necessary_scope_verified',false,
  'native_binding_verified',false,'input_authority_granted',false,'execution_authorized',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO scope_review_issuer.attestations(id,case_id,command_id,actor,bid_id,document,digest)
 VALUES(identifier,c.id,command,session_user,r.bid_id,result,checksum);
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$scope_issuer_attest$;

CREATE FUNCTION scope_review_issuer.read_native(target_bid uuid,target_command uuid,expected_reference_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,scope_review_issuer,design,pg_temp SET TimeZone='UTC'
AS $scope_issuer_read$
DECLARE a scope_review_issuer.attestations;p scope_review_issuer.profiles;h scope_review_issuer.profile_heads;
 c scope_review_issuer.cases;ch scope_review_issuer.case_heads;r material_registration.records;at timestamptz;
 issuer_active boolean;case_active boolean;
BEGIN
 IF current_setting('transaction_read_only')<>'on' OR current_setting('transaction_isolation')<>'repeatable read' THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_OWNED_READ_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_native_evidence_verify',ARRAY['scope_review_issuer.read_native(uuid,uuid,text)']) THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 SELECT * INTO a FROM scope_review_issuer.attestations WHERE command_id=target_command AND bid_id=target_bid AND document->>'version'='package-native-evidence-attestation/2'
  AND encode(sha256(convert_to(design.package_canonical_json(document->'reference'),'UTF8')),'hex')=expected_reference_digest;
 IF NOT FOUND THEN RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 SELECT * INTO c FROM scope_review_issuer.cases WHERE id=a.case_id;
 SELECT * INTO p FROM scope_review_issuer.profiles WHERE id=c.profile_id;
 SELECT * INTO h FROM scope_review_issuer.profile_heads WHERE login_name=p.login_name;
 SELECT * INTO ch FROM scope_review_issuer.case_heads WHERE case_id=c.id;
 SELECT * INTO r FROM material_registration.records WHERE id=c.registration_id AND digest=c.registration_digest;
 IF r.id IS NULL OR r.document->>'version' IS DISTINCT FROM 'package-native-material-registration/2' OR p.id::text IS DISTINCT FROM a.document->>'profile_id' OR p.login_name IS DISTINCT FROM a.actor
 OR encode(sha256(convert_to(design.package_canonical_json(to_jsonb(p)),'UTF8')),'hex') IS DISTINCT FROM a.document->>'profile_digest'
 OR encode(sha256(convert_to(design.package_canonical_json(to_jsonb(c)),'UTF8')),'hex') IS DISTINCT FROM a.document->>'case_digest' THEN
  RAISE EXCEPTION 'NATIVE_EVIDENCE_ISSUER_REFERENCE_STATE_INVALID' USING ERRCODE='P0001'; END IF;
 at:=clock_timestamp();
 issuer_active:=coalesce(h.profile_id=p.id AND h.enabled AND at>=p.valid_from AND at<p.valid_until
  AND p.database_name=current_database() AND p.database_oid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND scope_review_issuer.role_policy(p.login_name,'tender_native_evidence_issuer',ARRAY['scope_review_issuer.attest_native(uuid,uuid,jsonb)']),false);
 case_active:=coalesce(ch.enabled AND at>=c.valid_from AND at<c.valid_until,false);
 RETURN jsonb_build_object('record',jsonb_build_object('document',a.document,'digest',a.digest::text),
  'current',jsonb_build_object('observed_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
   'issuer_active',issuer_active,'case_active',case_active,'profile_head_revision',h.revision,'case_head_revision',ch.revision,
   'configured_issuer_identity_verified',true,'current_business_sources_rechecked',false,'necessary_scope_verified',false,
   'native_binding_verified',false,'input_authority_granted',false,'execution_authorized',false));
END;
$scope_issuer_read$;
REVOKE ALL ON FUNCTION scope_review_issuer.attest_native(uuid,uuid,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION scope_review_issuer.read_native(uuid,uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA scope_review_issuer TO tender_native_evidence_issuer,tender_native_evidence_verify;
GRANT EXECUTE ON FUNCTION scope_review_issuer.attest_native(uuid,uuid,jsonb) TO tender_native_evidence_issuer;
GRANT EXECUTE ON FUNCTION scope_review_issuer.read_native(uuid,uuid,text) TO tender_native_evidence_verify;
COMMIT;
