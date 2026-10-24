-- Optional fresh isolated initialization. Pending references grant no input authority.
BEGIN;
CREATE SCHEMA material_registration;
REVOKE ALL ON SCHEMA material_registration FROM PUBLIC;
CREATE ROLE tender_material_registration NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE TABLE material_registration.records(
 id uuid PRIMARY KEY, bid_id uuid NOT NULL,
 scope_id uuid NOT NULL REFERENCES design.bid_package_technical_scopes(id),
 command_id uuid NOT NULL UNIQUE, actor name NOT NULL,
 document jsonb NOT NULL, digest design.sha256 NOT NULL,
 CHECK(octet_length(document::text)<=16384)
);
CREATE TRIGGER immutable_material_registration BEFORE UPDATE OR DELETE ON material_registration.records
 FOR EACH ROW EXECUTE FUNCTION design.append_only();

CREATE FUNCTION material_registration.record(target_bid uuid,target_scope uuid,expected_scope text,command uuid,packet jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_registration,design,pg_temp
AS $material_record$
DECLARE old material_registration.records; scope_bid uuid; scope_hash text;
 identifier uuid; at timestamptz; result jsonb; checksum text; item record;
BEGIN
 IF current_setting('transaction_read_only')<>'off' OR current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'MATERIAL_REGISTRATION_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=session_user AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
  AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR NOT pg_has_role(session_user,'tender_material_registration','MEMBER')
 OR pg_has_role(session_user,current_user,'MEMBER') THEN
  RAISE EXCEPTION 'MATERIAL_REGISTRATION_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 IF target_bid IS NULL OR target_scope IS NULL OR command IS NULL OR expected_scope IS NULL
 OR expected_scope !~ '^[0-9a-f]{64}$' OR expected_scope=repeat('0',64)
 OR packet IS NULL OR jsonb_typeof(packet)<>'object' OR octet_length(packet::text)>4096 THEN
  RAISE EXCEPTION 'MATERIAL_REGISTRATION_PACKET_INVALID' USING ERRCODE='P0001'; END IF;
 IF NOT design.package_json_keys(packet,ARRAY['version','context_digest','context_method_digest','recovery_commit_digest',
  'recovery_method_digest','recovery_observation_digest','source_observation_digest','material_digest','registration_method_digest'])
 OR packet->>'version' IS DISTINCT FROM 'package-native-material-registration-packet/1' THEN
  RAISE EXCEPTION 'MATERIAL_REGISTRATION_PACKET_INVALID' USING ERRCODE='P0001'; END IF;
 FOR item IN SELECT key,value FROM jsonb_each(packet) WHERE key<>'version' LOOP
  IF jsonb_typeof(item.value)<>'string' OR item.value#>>'{}' !~ '^[0-9a-f]{64}$'
   OR item.value#>>'{}'=repeat('0',64) THEN
   RAISE EXCEPTION 'MATERIAL_REGISTRATION_PACKET_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 PERFORM pg_advisory_xact_lock(hashtextextended('material_registration:'||command::text,0));
 SELECT * INTO old FROM material_registration.records WHERE command_id=command;
 IF FOUND THEN
  IF old.bid_id<>target_bid OR old.scope_id<>target_scope OR old.actor<>session_user
   OR old.document->>'scope_digest'<>expected_scope OR old.document->'packet'<>packet THEN
   RAISE EXCEPTION 'MATERIAL_REGISTRATION_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 SELECT bid_id,digest::text INTO scope_bid,scope_hash FROM design.bid_package_technical_scopes WHERE id=target_scope;
 IF scope_bid IS DISTINCT FROM target_bid OR scope_hash IS DISTINCT FROM expected_scope THEN
  RAISE EXCEPTION 'MATERIAL_REGISTRATION_SCOPE_MISMATCH' USING ERRCODE='P0001'; END IF;
 identifier:=gen_random_uuid(); at:=clock_timestamp();
 result:=jsonb_build_object('version','package-native-material-registration/1','registration_id',identifier::text,
  'bid_id',target_bid::text,'scope_id',target_scope::text,'scope_digest',expected_scope,'command_id',command::text,
  'recorded_by',session_user::text,'recorded_at',to_char(at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'packet',packet,'status','awaiting_independent_verification','native_binding_verified',false,
  'necessary_scope_verified',false,'input_authority_granted',false,'execution_authorized',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO material_registration.records(id,bid_id,scope_id,command_id,actor,document,digest)
 VALUES(identifier,target_bid,target_scope,command,session_user,result,checksum);
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$material_record$;

CREATE FUNCTION material_registration.read(target_bid uuid,command uuid,expected_packet_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,material_registration,design,pg_temp
AS $material_read$
DECLARE item material_registration.records;
BEGIN
 IF current_setting('transaction_read_only')<>'on' OR current_setting('transaction_isolation')<>'repeatable read' THEN
  RAISE EXCEPTION 'MATERIAL_REGISTRATION_OWNED_READ_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=session_user AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
  AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR NOT pg_has_role(session_user,'tender_material_registration','MEMBER')
 OR pg_has_role(session_user,current_user,'MEMBER') THEN
  RAISE EXCEPTION 'MATERIAL_REGISTRATION_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 SELECT * INTO item FROM material_registration.records WHERE command_id=command AND bid_id=target_bid AND actor=session_user;
 IF NOT FOUND OR encode(sha256(convert_to(design.package_canonical_json(item.document->'packet'),'UTF8')),'hex') IS DISTINCT FROM expected_packet_digest THEN
  RAISE EXCEPTION 'MATERIAL_REGISTRATION_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 RETURN jsonb_build_object('document',item.document,'digest',item.digest::text);
END;
$material_read$;
REVOKE ALL ON FUNCTION material_registration.record(uuid,uuid,text,uuid,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION material_registration.read(uuid,uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA material_registration TO tender_material_registration;
GRANT EXECUTE ON FUNCTION material_registration.record(uuid,uuid,text,uuid,jsonb) TO tender_material_registration;
GRANT EXECUTE ON FUNCTION material_registration.read(uuid,uuid,text) TO tender_material_registration;
COMMIT;
