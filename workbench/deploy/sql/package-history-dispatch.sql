-- Optional bounded CPU queue discovery. Install after the complete exposure bridge.
-- Existing claims, leases, source checks and final-exposure transactions remain authoritative.
BEGIN;

CREATE INDEX package_history_dispatch_order
 ON package_historical_research.jobs(kind,created_at,id)
 WHERE state IN('queued','running');

CREATE FUNCTION package_historical_research.dispatch_candidates(
 purpose text, after_at timestamptz, after_id uuid, page_size integer
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE expected package_history_exposure_bridge.guard_manifest;
 live jsonb; recorded jsonb; result jsonb; entry record;
BEGIN
 IF purpose IS NULL OR purpose NOT IN('train','evaluate') THEN
  RAISE EXCEPTION 'package_history_dispatch_purpose_invalid' USING ERRCODE='23514';
 END IF;
 PERFORM package_historical_research.assert_role(purpose);
 IF page_size IS NULL OR page_size NOT BETWEEN 1 AND 20
 OR (after_at IS NULL) IS DISTINCT FROM (after_id IS NULL)
 OR (after_at IS NOT NULL AND NOT isfinite(after_at)) THEN
  RAISE EXCEPTION 'package_history_dispatch_page_invalid' USING ERRCODE='23514';
 END IF;

 -- Attest the same complete installation as the public entry, without granting
 -- CPU identities API membership or direct access to the private guard tables.
 SELECT p.proowner=n.nspowner AND p.proowner=d.nspowner AND p.prosecdef
  AND p.prokind='f' AND p.provolatile='s' AND NOT p.proretset
  AND p.prorettype='jsonb'::regtype AND p.pronargs=0
  AND p.prolang=(SELECT oid FROM pg_language WHERE lanname='plpgsql')
  AND p.proconfig=ARRAY['search_path=pg_catalog, pg_temp']::text[]
  AND encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')=
   '2e34c9cce5297cd7c8c32e9e27464eb821579c4f62b152c9eebbd3e2d7de2d66' AS ready
 INTO entry FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 JOIN pg_namespace d ON d.nspname='design'
 WHERE n.nspname='package_history_exposure_bridge' AND p.proname='readiness'
 AND p.pronargs=0;
 IF entry.ready IS DISTINCT FROM true THEN
  RAISE EXCEPTION 'package_history_dispatch_guard_unavailable' USING ERRCODE='55000';
 END IF;
 SELECT * INTO expected FROM package_history_exposure_bridge.guard_manifest WHERE singleton;
 SELECT jsonb_agg(to_jsonb(c) ORDER BY object_type,identity) INTO live
 FROM package_history_exposure_bridge.live_guard_contracts() c;
 SELECT jsonb_agg(to_jsonb(c) ORDER BY object_type,identity) INTO recorded
 FROM package_history_exposure_bridge.guard_contracts c;
 IF expected.singleton IS DISTINCT FROM true OR expected.contract_count IS DISTINCT FROM 76
 OR jsonb_array_length(recorded) IS DISTINCT FROM expected.contract_count
 OR encode(sha256(convert_to(recorded::text,'UTF8')),'hex') IS DISTINCT FROM expected.contract_digest
 OR live IS DISTINCT FROM recorded
 OR (SELECT count(*) FROM package_history_exposure_bridge.installation_functions)<>13
 OR EXISTS(SELECT FROM package_history_exposure_bridge.installation_functions f
  WHERE to_regprocedure(f.signature)::oid IS DISTINCT FROM f.original_oid) THEN
  RAISE EXCEPTION 'package_history_dispatch_guard_unavailable' USING ERRCODE='55000';
 END IF;

 SELECT coalesce(jsonb_agg(to_jsonb(candidate) ORDER BY created_at,job_id),'[]'::jsonb)
 INTO result FROM (
  SELECT id AS job_id,generation,created_at
  FROM package_historical_research.jobs
  WHERE kind=purpose AND (state='queued' OR state='running' AND lease_until<=clock_timestamp())
  AND (after_at IS NULL OR (created_at,id)>(after_at,after_id))
  ORDER BY created_at,id LIMIT page_size
 ) candidate;
 RETURN result;
END $$;

REVOKE ALL ON FUNCTION package_historical_research.dispatch_candidates(text,timestamptz,uuid,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION package_historical_research.dispatch_candidates(text,timestamptz,uuid,integer)
 TO tender_package_history_train,tender_package_history_evaluate;
COMMIT;
