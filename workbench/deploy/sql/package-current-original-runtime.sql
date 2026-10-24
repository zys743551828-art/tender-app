-- Optional fresh independent check installation; never part of BASE.
BEGIN;
CREATE SCHEMA current_technical_original;
REVOKE ALL ON SCHEMA current_technical_original FROM PUBLIC;
DO $$ BEGIN
 IF EXISTS(SELECT FROM pg_roles WHERE rolname='tender_current_original_verify') THEN
  RAISE EXCEPTION 'current_original_role_already_exists';
 END IF;
 CREATE ROLE tender_current_original_verify NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
END $$;
GRANT tender_current_scope_verify TO tender_current_original_verify;

CREATE FUNCTION current_technical_original.locate(target_bid uuid,target_scope uuid,expected_scope_digest text,target_document uuid,expected_original_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design,pg_temp
AS $current_original$
DECLARE facts jsonb; frozen jsonb; files jsonb; sources jsonb; selected jsonb; native record;
 roots uuid[]; pending uuid[]; seen uuid[]:='{}'; remaining uuid[]; ready uuid[];
 depth integer; edges bigint:=0; amount bigint; actual_pairs jsonb; frozen_pairs jsonb;
 at_time timestamptz:=clock_timestamp();
BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=session_user AND rolcanlogin AND NOT rolsuper
  AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR NOT pg_has_role(session_user,'tender_current_original_verify','MEMBER') THEN
  RAISE EXCEPTION 'CURRENT_ORIGINAL_INDEPENDENT_LOGIN_REQUIRED' USING ERRCODE='42501'; END IF;
 facts:=current_technical_scope.observe(target_bid,target_scope,expected_scope_digest);
 frozen:=facts#>'{scope,manifest,preview,manifest}';
 files:=facts#>'{scope,manifest,original_verification,files}';
 sources:=frozen->'source_snapshot';
 IF jsonb_typeof(files) IS DISTINCT FROM 'array' OR jsonb_array_length(files) NOT BETWEEN 1 AND 20000 THEN
  RAISE EXCEPTION 'CURRENT_ORIGINAL_FILE_SET_INVALID'; END IF;
 SELECT count(*),jsonb_agg(value)->0 INTO amount,selected FROM jsonb_array_elements(files)
  WHERE value->>'document_version_id'=target_document::text AND value->>'digest'=expected_original_digest;
 IF amount<>1 THEN RAISE EXCEPTION 'CURRENT_ORIGINAL_NOT_IN_SCOPE'; END IF;
 IF jsonb_typeof(sources) IS DISTINCT FROM 'array' OR jsonb_array_length(sources) NOT BETWEEN 1 AND 20000 THEN
  RAISE EXCEPTION 'CURRENT_ORIGINAL_SOURCE_SET_INVALID'; END IF;

 -- Recompute the canonical roots from both packages, rather than trusting caller JSON.
 SELECT array_agg(id ORDER BY id) INTO roots FROM (
  SELECT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-original:'||(value->>'document_version_id')) id
   FROM jsonb_array_elements(frozen->'documents')
  UNION
  SELECT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-parse:'||(value#>>'{parse,parse_run_id}'))
   FROM jsonb_array_elements(frozen->'documents') WHERE value#>>'{parse,status}'='frozen'
 ) r;
 IF roots IS NULL OR roots IS DISTINCT FROM (SELECT array_agg(id ORDER BY id) FROM (
  SELECT DISTINCT (value->>'source_id')::uuid id FROM jsonb_array_elements(sources)) r) THEN
  RAISE EXCEPTION 'CURRENT_ORIGINAL_SOURCE_SET_INVALID'; END IF;

 -- Bound the reachable graph before computing its full root/ancestor closure.
 pending:=roots;
 FOR depth IN 1..64 LOOP
  EXIT WHEN cardinality(pending)=0;
  seen:=seen||pending;
  IF cardinality(seen)>20000 THEN RAISE EXCEPTION 'CURRENT_ORIGINAL_SOURCE_LIMIT'; END IF;
  SELECT count(*) INTO amount FROM (SELECT FROM retrieval.lineage_edges WHERE child_id=ANY(pending) LIMIT 20001) e;
  edges:=edges+amount;
  IF edges>20000 THEN RAISE EXCEPTION 'CURRENT_ORIGINAL_SOURCE_LIMIT'; END IF;
  SELECT coalesce(array_agg(id ORDER BY id),'{}'::uuid[]) INTO pending FROM (
   SELECT DISTINCT parent_id id FROM retrieval.lineage_edges WHERE child_id=ANY(pending) AND NOT parent_id=ANY(seen)
  ) e;
 END LOOP;
 IF cardinality(pending)>0 THEN RAISE EXCEPTION 'CURRENT_ORIGINAL_SOURCE_LIMIT'; END IF;
 -- A cycle, even introduced outside the normal append guard, must fail closed.
 remaining:=seen;
 FOR depth IN 1..64 LOOP
  EXIT WHEN cardinality(remaining)=0;
  SELECT coalesce(array_agg(id),'{}'::uuid[]) INTO ready FROM unnest(remaining) id
   WHERE NOT EXISTS(SELECT FROM retrieval.lineage_edges WHERE child_id=id AND parent_id=ANY(remaining));
  IF cardinality(ready)=0 THEN RAISE EXCEPTION 'CURRENT_ORIGINAL_SOURCE_LIMIT'; END IF;
  SELECT coalesce(array_agg(id),'{}'::uuid[]) INTO remaining FROM unnest(remaining) id WHERE NOT id=ANY(ready);
 END LOOP;
 IF cardinality(remaining)>0 THEN RAISE EXCEPTION 'CURRENT_ORIGINAL_SOURCE_LIMIT'; END IF;
 WITH RECURSIVE walk(source_id,ancestor_id) AS (
  SELECT id,id FROM unnest(roots) id UNION
  SELECT w.source_id,e.parent_id FROM walk w JOIN retrieval.lineage_edges e ON e.child_id=w.ancestor_id
 ), limited AS (SELECT * FROM walk LIMIT 20001)
 SELECT count(*),jsonb_agg(jsonb_build_array(source_id,ancestor_id) ORDER BY source_id,ancestor_id)
 INTO amount,actual_pairs FROM limited;
 IF amount>20000 THEN RAISE EXCEPTION 'CURRENT_ORIGINAL_SOURCE_LIMIT'; END IF;
 SELECT jsonb_agg(jsonb_build_array(source_id,ancestor_id) ORDER BY source_id,ancestor_id) INTO frozen_pairs
 FROM jsonb_to_recordset(sources) AS f(source_id uuid,ancestor_id uuid);
 IF actual_pairs IS DISTINCT FROM frozen_pairs THEN RAISE EXCEPTION 'CURRENT_ORIGINAL_SOURCE_CLOSURE_CHANGED'; END IF;
 IF EXISTS(
  SELECT FROM jsonb_to_recordset(sources) AS f(ancestor_id uuid,document_version_id uuid,digest text,kind text,
   policy_class text,known_at timestamptz,revision bigint,status text,valid_from timestamptz,valid_until timestamptz)
  LEFT JOIN retrieval.source_nodes n ON n.id=f.ancestor_id LEFT JOIN retrieval.source_heads h ON h.source_id=n.id
  LEFT JOIN design.document_versions v ON v.id=n.document_version_id LEFT JOIN design.blobs b ON b.id=v.blob_id
  WHERE n.id IS NULL OR v.bid_id IS DISTINCT FROM target_bid OR n.document_version_id IS DISTINCT FROM f.document_version_id
   OR n.kind IS DISTINCT FROM 'document' OR n.kind IS DISTINCT FROM f.kind
   OR n.policy_class IS DISTINCT FROM 'prebid_content' OR n.policy_class IS DISTINCT FROM f.policy_class
   OR n.digest IS DISTINCT FROM f.digest OR n.digest IS DISTINCT FROM b.digest
   OR n.known_at IS DISTINCT FROM f.known_at OR n.known_at>at_time
   OR h.status IS DISTINCT FROM 'published' OR h.status IS DISTINCT FROM f.status
   OR h.revision IS NULL OR h.revision IS DISTINCT FROM f.revision
   OR h.valid_from IS NULL OR h.valid_from IS DISTINCT FROM f.valid_from OR h.valid_from>at_time
   OR h.valid_until IS DISTINCT FROM f.valid_until OR h.valid_until<=at_time
 ) THEN RAISE EXCEPTION 'CURRENT_ORIGINAL_SOURCES_CHANGED'; END IF;
 SELECT b.object_key,b.digest,b.byte_size,b.media_type,v.artifact_kind INTO native
 FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=target_bid AND v.id=target_document;
 IF NOT FOUND OR native.digest IS DISTINCT FROM expected_original_digest
 OR native.byte_size IS DISTINCT FROM (selected->>'byte_size')::bigint OR native.byte_size NOT BETWEEN 1 AND 33554432
 OR native.artifact_kind NOT IN('source_original','bid_body') OR native.object_key IS NULL
 OR octet_length(native.object_key) NOT BETWEEN 1 AND 4096 THEN RAISE EXCEPTION 'CURRENT_ORIGINAL_BINDING_INVALID'; END IF;
 RETURN jsonb_build_object('version','package-current-original-locator/1','bid_id',target_bid,'scope_id',target_scope,
  'scope_digest',expected_scope_digest,'document_version_id',target_document,'source_digest',native.digest,
  'source_byte_size',native.byte_size,'media_type',native.media_type,'observed_at',clock_timestamp(),
  'source_snapshot_digest',design.package_technical_digest(sources),'locator',native.object_key,
  'native_current_original_locator_checked',true,'original_bytes_reverified',false,'necessary_scope_verified',false,
  'input_authority_granted',false,'execution_authorized',false,'historical_existence_verified',false);
END;
$current_original$;
REVOKE ALL ON FUNCTION current_technical_original.locate(uuid,uuid,text,uuid,text) FROM PUBLIC;
GRANT USAGE ON SCHEMA current_technical_original TO tender_current_original_verify;
GRANT EXECUTE ON FUNCTION current_technical_original.locate(uuid,uuid,text,uuid,text) TO tender_current_original_verify;
COMMIT;
