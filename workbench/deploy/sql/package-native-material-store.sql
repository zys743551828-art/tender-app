-- Optional fresh check DB only. Private byte identity is not input qualification.
BEGIN;
CREATE SCHEMA technical_material_store;
REVOKE ALL ON SCHEMA technical_material_store FROM PUBLIC;
CREATE ROLE tender_material_store_write NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE tender_material_store_read NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE TABLE technical_material_store.objects(
 sha design.sha256 PRIMARY KEY,data bytea NOT NULL,
 CHECK(octet_length(data) BETWEEN 1 AND 67108864),CHECK(encode(sha256(data),'hex')=sha)
);
CREATE TABLE technical_material_store.records(
 id uuid PRIMARY KEY,bid_id uuid NOT NULL,scope_id uuid NOT NULL REFERENCES design.bid_package_technical_scopes(id),
 command_id uuid NOT NULL UNIQUE,actor name NOT NULL,document jsonb NOT NULL,digest design.sha256 NOT NULL,
 CHECK(octet_length(document::text)<=131072)
);
CREATE TABLE technical_material_store.record_objects(
 record_id uuid NOT NULL REFERENCES technical_material_store.records(id),
 object_sha design.sha256 NOT NULL REFERENCES technical_material_store.objects(sha),PRIMARY KEY(record_id,object_sha)
);
CREATE TRIGGER immutable_material_store_object BEFORE UPDATE OR DELETE ON technical_material_store.objects
 FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_material_store_record BEFORE UPDATE OR DELETE ON technical_material_store.records
 FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_material_store_link BEFORE UPDATE OR DELETE ON technical_material_store.record_objects
 FOR EACH ROW EXECUTE FUNCTION design.append_only();

CREATE FUNCTION technical_material_store.put(target_bid uuid,target_scope uuid,expected_scope text,command uuid,packet jsonb,object_keys text[],object_values bytea[])
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,technical_material_store,design,pg_temp SET TimeZone='UTC'
AS $material_store_put$
DECLARE old technical_material_store.records;refs jsonb;ref jsonb;key text;field text;i integer;
 required text[];actual text[];bytes bigint;image_bytes bigint:=0;identifier uuid;result jsonb;checksum text;
 context jsonb;observation jsonb;derivation jsonb;findings jsonb;image_refs jsonb;at timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off' THEN
  RAISE EXCEPTION 'MATERIAL_STORE_OWNED_WRITE_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_store_write',ARRAY['technical_material_store.put(uuid,uuid,text,uuid,jsonb,text[],bytea[])']) THEN
  RAISE EXCEPTION 'MATERIAL_STORE_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 IF target_bid IS NULL OR target_scope IS NULL OR command IS NULL OR expected_scope IS NULL
 OR expected_scope !~ '^[0-9a-f]{64}$' OR expected_scope=repeat('0',64) OR packet IS NULL
 OR jsonb_typeof(packet)<>'object' OR octet_length(packet::text)>100000 THEN
  RAISE EXCEPTION 'MATERIAL_STORE_PACKET_INVALID' USING ERRCODE='P0001'; END IF;
 IF NOT design.package_json_keys(packet,ARRAY['version','store_method_digest','context_digest','context_method_digest',
  'source_observation_digest','derivation_observation_digest','review_digest','findings_digest',
  'context_object','source_observation_object','derivation_object','findings_object','image_objects'])
 OR packet->>'version' IS DISTINCT FROM 'package-native-material-store-packet/1' THEN
  RAISE EXCEPTION 'MATERIAL_STORE_PACKET_INVALID' USING ERRCODE='P0001'; END IF;
 FOREACH field IN ARRAY ARRAY['store_method_digest','context_digest','context_method_digest','source_observation_digest',
  'derivation_observation_digest','review_digest','findings_digest'] LOOP
  IF jsonb_typeof(packet->field) IS DISTINCT FROM 'string' OR packet->>field !~ '^[0-9a-f]{64}$' OR packet->>field=repeat('0',64) THEN
   RAISE EXCEPTION 'MATERIAL_STORE_PACKET_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 IF jsonb_typeof(packet->'image_objects') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'MATERIAL_STORE_PACKET_INVALID' USING ERRCODE='P0001'; END IF;
 IF jsonb_array_length(packet->'image_objects') NOT BETWEEN 1 AND 384 THEN
  RAISE EXCEPTION 'MATERIAL_STORE_CAPACITY_EXCEEDED' USING ERRCODE='P0001'; END IF;
 refs:=jsonb_build_array(packet->'context_object',packet->'source_observation_object',packet->'derivation_object',packet->'findings_object');
 FOR ref IN SELECT value FROM jsonb_array_elements(refs) LOOP
  IF jsonb_typeof(ref) IS DISTINCT FROM 'object' OR NOT design.package_json_keys(ref,ARRAY['sha256','byte_size']) THEN
   RAISE EXCEPTION 'MATERIAL_STORE_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 FOR ref IN SELECT value FROM jsonb_array_elements(packet->'image_objects') LOOP
  IF jsonb_typeof(ref) IS DISTINCT FROM 'object' OR NOT design.package_json_keys(ref,ARRAY['asset_id','sha256','byte_size'])
  OR jsonb_typeof(ref->'asset_id') IS DISTINCT FROM 'string' OR ref->>'asset_id' !~ '^[0-9a-f]{64}$' OR ref->>'asset_id'=repeat('0',64) THEN
   RAISE EXCEPTION 'MATERIAL_STORE_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 IF (SELECT count(DISTINCT value->>'asset_id') FROM jsonb_array_elements(packet->'image_objects'))<>jsonb_array_length(packet->'image_objects') THEN
  RAISE EXCEPTION 'MATERIAL_STORE_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(refs||(packet->'image_objects')) LOOP
  IF jsonb_typeof(ref->'sha256') IS DISTINCT FROM 'string' OR ref->>'sha256' !~ '^[0-9a-f]{64}$' OR ref->>'sha256'=repeat('0',64)
  OR jsonb_typeof(ref->'byte_size') IS DISTINCT FROM 'number' OR ref->>'byte_size' !~ '^[1-9][0-9]{0,8}$' THEN
   RAISE EXCEPTION 'MATERIAL_STORE_REFERENCE_INVALID' USING ERRCODE='P0001'; END IF;
  IF (ref->>'byte_size')::bigint>67108864 THEN RAISE EXCEPTION 'MATERIAL_STORE_CAPACITY_EXCEEDED' USING ERRCODE='P0001'; END IF;
 END LOOP;
 IF (packet#>>'{context_object,byte_size}')::bigint>12582912 OR (packet#>>'{source_observation_object,byte_size}')::bigint>2097152
 OR (packet#>>'{derivation_object,byte_size}')::bigint>4194304 OR (packet#>>'{findings_object,byte_size}')::bigint>8392704 THEN
  RAISE EXCEPTION 'MATERIAL_STORE_CAPACITY_EXCEEDED' USING ERRCODE='P0001'; END IF;
 SELECT sum((value->>'byte_size')::bigint) INTO image_bytes FROM jsonb_array_elements(packet->'image_objects');
 IF image_bytes>67108864 OR EXISTS(SELECT FROM jsonb_array_elements(packet->'image_objects') WHERE (value->>'byte_size')::bigint>33554432) THEN
  RAISE EXCEPTION 'MATERIAL_STORE_CAPACITY_EXCEEDED' USING ERRCODE='P0001'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('technical_material_store:'||command::text,0));
 SELECT * INTO old FROM technical_material_store.records WHERE command_id=command;
 IF FOUND THEN
  IF old.actor<>session_user OR old.bid_id<>target_bid OR old.scope_id<>target_scope OR old.document->'packet'<>packet
  OR old.document->>'scope_digest'<>expected_scope THEN RAISE EXCEPTION 'MATERIAL_STORE_COMMAND_CONFLICT' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('document',old.document,'digest',old.digest::text);
 END IF;
 IF NOT EXISTS(SELECT FROM design.bid_package_technical_scopes WHERE id=target_scope AND bid_id=target_bid AND digest=expected_scope) THEN
  RAISE EXCEPTION 'MATERIAL_STORE_SCOPE_MISMATCH' USING ERRCODE='P0001'; END IF;
 SELECT array_agg(x ORDER BY x) INTO required FROM (SELECT DISTINCT value->>'sha256' x FROM jsonb_array_elements(refs||(packet->'image_objects'))) q;
 IF object_keys IS NULL OR object_values IS NULL OR coalesce(array_ndims(object_keys),0)<>1 OR coalesce(array_ndims(object_values),0)<>1
 OR array_lower(object_keys,1)<>1 OR array_lower(object_values,1)<>1 OR cardinality(object_keys)<>cardinality(required)
 OR cardinality(object_keys)<>cardinality(object_values) THEN RAISE EXCEPTION 'MATERIAL_STORE_OBJECT_SET_INVALID' USING ERRCODE='P0001'; END IF;
 SELECT array_agg(x ORDER BY x) INTO actual FROM unnest(object_keys) x;
 IF actual IS DISTINCT FROM required THEN RAISE EXCEPTION 'MATERIAL_STORE_OBJECT_SET_INVALID' USING ERRCODE='P0001'; END IF;
 FOR i IN 1..cardinality(object_keys) LOOP
  IF object_values[i] IS NULL OR octet_length(object_values[i]) NOT BETWEEN 1 AND 67108864
  OR encode(sha256(object_values[i]),'hex')<>object_keys[i] THEN RAISE EXCEPTION 'MATERIAL_STORE_OBJECT_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 FOR ref IN SELECT value FROM jsonb_array_elements(refs||(packet->'image_objects')) LOOP
  i:=array_position(object_keys,ref->>'sha256');
  IF octet_length(object_values[i])<>(ref->>'byte_size')::bigint THEN RAISE EXCEPTION 'MATERIAL_STORE_OBJECT_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 BEGIN
  context:=convert_from(object_values[array_position(object_keys,packet#>>'{context_object,sha256}')],'UTF8')::jsonb;
  observation:=convert_from(object_values[array_position(object_keys,packet#>>'{source_observation_object,sha256}')],'UTF8')::jsonb;
  derivation:=convert_from(object_values[array_position(object_keys,packet#>>'{derivation_object,sha256}')],'UTF8')::jsonb;
  findings:=convert_from(object_values[array_position(object_keys,packet#>>'{findings_object,sha256}')],'UTF8')::jsonb;
 EXCEPTION WHEN invalid_text_representation OR character_not_in_repertoire THEN
  RAISE EXCEPTION 'MATERIAL_STORE_DOCUMENT_INVALID' USING ERRCODE='P0001';
 END;
 IF context->>'version' IS DISTINCT FROM 'package-technical-material-context/3' OR context->>'bid_id' IS DISTINCT FROM target_bid::text
 OR context->>'scope_id' IS DISTINCT FROM target_scope::text OR context->>'scope_digest' IS DISTINCT FROM expected_scope
 OR context->>'digest' IS DISTINCT FROM packet->>'context_digest' OR context->>'context_method_digest' IS DISTINCT FROM packet->>'context_method_digest'
 OR context->>'source_observation_digest' IS DISTINCT FROM packet->>'source_observation_digest'
 OR observation->>'digest' IS DISTINCT FROM packet->>'source_observation_digest'
 OR derivation->>'digest' IS DISTINCT FROM packet->>'derivation_observation_digest' OR derivation->>'context_digest' IS DISTINCT FROM packet->>'context_digest'
 OR derivation->>'version' IS DISTINCT FROM 'fusion-exact-context-derivation/1'
 OR findings->>'digest' IS DISTINCT FROM packet->>'findings_digest' OR findings->>'context_digest' IS DISTINCT FROM packet->>'context_digest'
 OR findings->>'review_digest' IS DISTINCT FROM packet->>'review_digest' OR findings->>'version' IS DISTINCT FROM 'package-material-scope-findings-check/1' THEN
  RAISE EXCEPTION 'MATERIAL_STORE_DOCUMENT_INVALID' USING ERRCODE='P0001'; END IF;
 FOREACH field IN ARRAY ARRAY['context_digest','source_observation_digest','derivation_observation_digest','findings_digest'] LOOP
  checksum:=encode(sha256(convert_to(design.package_canonical_json((CASE field WHEN 'context_digest' THEN context
   WHEN 'source_observation_digest' THEN observation WHEN 'derivation_observation_digest' THEN derivation ELSE findings END)-'digest'),'UTF8')),'hex');
  IF checksum IS DISTINCT FROM packet->>field THEN RAISE EXCEPTION 'MATERIAL_STORE_DOCUMENT_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 FOREACH field IN ARRAY ARRAY['necessary_scope_verified','native_binding_verified','input_authority_granted','execution_authorized','historical_existence_verified'] LOOP
  IF ((context ? field) AND context->field IS DISTINCT FROM 'false'::jsonb)
  OR ((observation ? field) AND observation->field IS DISTINCT FROM 'false'::jsonb)
  OR ((derivation ? field) AND derivation->field IS DISTINCT FROM 'false'::jsonb)
  OR ((findings ? field) AND findings->field IS DISTINCT FROM 'false'::jsonb) THEN
   RAISE EXCEPTION 'MATERIAL_STORE_DOCUMENT_INVALID' USING ERRCODE='P0001'; END IF;
 END LOOP;
 IF jsonb_typeof(context->'images') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'MATERIAL_STORE_DOCUMENT_INVALID' USING ERRCODE='P0001'; END IF;
 SELECT jsonb_agg(jsonb_build_object('asset_id',value#>>'{asset,id}','sha256',value#>>'{asset,sha256}',
  'byte_size',value#>'{asset,byte_size}') ORDER BY value#>>'{asset,id}') INTO image_refs FROM jsonb_array_elements(context->'images');
 IF image_refs IS DISTINCT FROM packet->'image_objects' THEN RAISE EXCEPTION 'MATERIAL_STORE_DOCUMENT_INVALID' USING ERRCODE='P0001'; END IF;
 FOR i IN 1..cardinality(object_keys) LOOP
  INSERT INTO technical_material_store.objects(sha,data) VALUES(object_keys[i],object_values[i]) ON CONFLICT DO NOTHING;
  IF NOT EXISTS(SELECT FROM technical_material_store.objects WHERE sha=object_keys[i] AND data=object_values[i]) THEN
   RAISE EXCEPTION 'MATERIAL_STORE_OBJECT_CONFLICT' USING ERRCODE='P0001'; END IF;
 END LOOP;
 identifier:=gen_random_uuid();at:=clock_timestamp();
 result:=jsonb_build_object('version','package-native-material-store-record/1','record_id',identifier::text,
  'bid_id',target_bid::text,'scope_id',target_scope::text,'scope_digest',expected_scope,'command_id',command::text,
  'recorded_by',session_user::text,'recorded_at',to_char(at,'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'packet',packet,'packet_digest',encode(sha256(convert_to(design.package_canonical_json(packet),'UTF8')),'hex'),
  'status','private_evidence_stored','necessary_scope_verified',false,'native_binding_verified',false,
  'input_authority_granted',false,'execution_authorized',false,'historical_existence_verified',false);
 checksum:=encode(sha256(convert_to(design.package_canonical_json(result),'UTF8')),'hex');
 INSERT INTO technical_material_store.records VALUES(identifier,target_bid,target_scope,command,session_user,result,checksum);
 INSERT INTO technical_material_store.record_objects SELECT identifier,x FROM unnest(required) x;
 RETURN jsonb_build_object('document',result,'digest',checksum);
END;
$material_store_put$;

CREATE FUNCTION technical_material_store.read(target_bid uuid,target_command uuid,expected_packet_digest text,object_key text)
RETURNS TABLE(document jsonb,digest text,object_sha text,data bytea) LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,technical_material_store,design,pg_temp SET TimeZone='UTC'
AS $material_store_read$
DECLARE stored technical_material_store.records;payload bytea;
BEGIN
 IF current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on' THEN
  RAISE EXCEPTION 'MATERIAL_STORE_OWNED_READ_TRANSACTION_REQUIRED' USING ERRCODE='25001'; END IF;
 IF NOT scope_review_issuer.role_policy(session_user,'tender_material_store_read',ARRAY['technical_material_store.read(uuid,uuid,text,text)']) THEN
  RAISE EXCEPTION 'MATERIAL_STORE_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 SELECT * INTO stored FROM technical_material_store.records r WHERE r.bid_id=target_bid AND r.command_id=target_command
  AND r.document->>'packet_digest'=expected_packet_digest;
 IF NOT FOUND THEN RAISE EXCEPTION 'MATERIAL_STORE_NOT_FOUND' USING ERRCODE='P0001'; END IF;
 IF object_key IS NOT NULL THEN
  SELECT o.data INTO payload FROM technical_material_store.objects o JOIN technical_material_store.record_objects x ON x.object_sha=o.sha
   WHERE x.record_id=stored.id AND o.sha=object_key;
  IF NOT FOUND THEN RAISE EXCEPTION 'MATERIAL_STORE_OBJECT_NOT_IN_RECORD' USING ERRCODE='P0001'; END IF;
 END IF;
 RETURN QUERY SELECT stored.document,stored.digest::text,object_key,payload;
END;
$material_store_read$;
REVOKE ALL ON FUNCTION technical_material_store.put(uuid,uuid,text,uuid,jsonb,text[],bytea[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION technical_material_store.read(uuid,uuid,text,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA technical_material_store TO tender_material_store_write,tender_material_store_read;
GRANT EXECUTE ON FUNCTION technical_material_store.put(uuid,uuid,text,uuid,jsonb,text[],bytea[]) TO tender_material_store_write;
GRANT EXECUTE ON FUNCTION technical_material_store.read(uuid,uuid,text,text) TO tender_material_store_read;
COMMIT;
