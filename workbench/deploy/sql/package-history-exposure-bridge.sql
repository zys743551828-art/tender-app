-- Optional reviewed native-package / legacy-body exposure bridge.
-- Fresh mechanism installation only. Never part of BASE or default recovery.
-- All changes (including function OIDs, triggers and prior-exposure capture) are
-- one transaction. Missing/drifted dependencies abort without a partial bridge.
BEGIN;
SET LOCAL search_path=pg_catalog,pg_temp;
SELECT pg_advisory_xact_lock(91143,1);
DO $$ BEGIN
 IF current_setting('transaction_isolation')<>'read committed'
 OR to_regclass('model_governance.exposures') IS NULL
 OR to_regclass('package_historical_research.exposures') IS NULL
 OR to_regclass('package_historical_research.admission_keys') IS NULL
 THEN RAISE EXCEPTION 'package_history_bridge_dependencies_missing' USING ERRCODE='55000'; END IF;
END $$;

CREATE SCHEMA package_history_exposure_bridge;
REVOKE ALL ON SCHEMA package_history_exposure_bridge FROM PUBLIC;
CREATE TABLE package_history_exposure_bridge.installation_functions(
 signature text PRIMARY KEY,original_oid oid NOT NULL,original_body_digest design.sha256 NOT NULL,
 installed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE package_history_exposure_bridge.entity_aliases(
 entity text NOT NULL,kind text NOT NULL CHECK(kind='source_group'),identity text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(entity,kind,identity)
);
CREATE TABLE package_history_exposure_bridge.cohort_bindings(
 namespace text NOT NULL CHECK(namespace IN('package','body')),cohort_id uuid NOT NULL,
 cohort_digest design.sha256 NOT NULL,membership_digest design.sha256 NOT NULL,
 seeds text[] NOT NULL,snapshot jsonb NOT NULL,snapshot_digest design.sha256 NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(namespace,cohort_id),
 CHECK(design.package_technical_digest(snapshot)=snapshot_digest)
);
CREATE TABLE package_history_exposure_bridge.exposure_receipts(
 namespace text NOT NULL CHECK(namespace IN('package','body')),exposure_id uuid NOT NULL,
 cohort_id uuid NOT NULL,cohort_digest design.sha256 NOT NULL,membership_digest design.sha256 NOT NULL,
 model_digest design.sha256 NOT NULL,predictions_digest design.sha256 NOT NULL,protocol_digest design.sha256 NOT NULL,
 seeds text[] NOT NULL,snapshot jsonb NOT NULL,snapshot_digest design.sha256 NOT NULL,
 original_created_xact xid8 NOT NULL,original_created_at timestamptz NOT NULL,
 captured_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(namespace,exposure_id),
 CHECK(design.package_technical_digest(snapshot)=snapshot_digest)
);
CREATE TABLE package_history_exposure_bridge.guard_contracts(
 object_type text NOT NULL,object_oid oid NOT NULL,identity text NOT NULL,fingerprint jsonb NOT NULL,
 PRIMARY KEY(object_type,identity)
);
CREATE TABLE package_history_exposure_bridge.guard_manifest(
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 contract_count integer NOT NULL CHECK(contract_count=76),
 contract_digest text NOT NULL CHECK(contract_digest~'^[0-9a-f]{64}$'),
 installed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['installation_functions','entity_aliases','cohort_bindings','exposure_receipts','guard_contracts','guard_manifest'] LOOP
  EXECUTE format('CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_history_exposure_bridge.%I FOR EACH ROW EXECUTE FUNCTION design.append_only()',tab);
 END LOOP;
END $$;

-- Exact prosrc digests below are derived from the separately reviewed files.
-- These checks intentionally do not guess how to patch a different release.
DO $verify$ DECLARE p pg_proc; BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('model_governance.current_cohort(uuid)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'boolean'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, model_governance, design, retrieval, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'b98900b5ee510428c897632d6c65065183f64aed8bb6676ad6ffa0fd8a1187e8'
 THEN RAISE EXCEPTION 'package_history_bridge_function_drift: model_governance.current_cohort(uuid)' USING ERRCODE='55000'; END IF;
 INSERT INTO package_history_exposure_bridge.installation_functions(signature,original_oid,original_body_digest) VALUES('model_governance.current_cohort(uuid)',p.oid,'b98900b5ee510428c897632d6c65065183f64aed8bb6676ad6ffa0fd8a1187e8');
END $verify$;

DO $verify$ DECLARE p pg_proc; BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('design.lock_research_run_scope(uuid)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'void'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, design, retrieval, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'73c31863790e1b53ebc37376dd1e611625da7051c6969cb35f9b4fb9b0d58ec2'
 THEN RAISE EXCEPTION 'package_history_bridge_function_drift: design.lock_research_run_scope(uuid)' USING ERRCODE='55000'; END IF;
 INSERT INTO package_history_exposure_bridge.installation_functions(signature,original_oid,original_body_digest) VALUES('design.lock_research_run_scope(uuid)',p.oid,'73c31863790e1b53ebc37376dd1e611625da7051c6969cb35f9b4fb9b0d58ec2');
END $verify$;

DO $verify$ DECLARE p pg_proc; BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('package_historical_research.related_admissions(uuid)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'uuid[]'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='sql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, package_historical_research, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'0b0599d43867280b2edcf12222deb5aaf6b557fdb19f21694180037edf5a561a'
 THEN RAISE EXCEPTION 'package_history_bridge_function_drift: package_historical_research.related_admissions(uuid)' USING ERRCODE='55000'; END IF;
 INSERT INTO package_history_exposure_bridge.installation_functions(signature,original_oid,original_body_digest) VALUES('package_historical_research.related_admissions(uuid)',p.oid,'0b0599d43867280b2edcf12222deb5aaf6b557fdb19f21694180037edf5a561a');
END $verify$;

DO $verify$ DECLARE p pg_proc; BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('package_historical_research.already_exposed(uuid[],uuid)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'boolean'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='sql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, package_historical_research, model_governance, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'d9a5a187a971638b43aae13935971e7c2c4aaf4dfb0968e1829c35bc67d23722'
 THEN RAISE EXCEPTION 'package_history_bridge_function_drift: package_historical_research.already_exposed(uuid[],uuid)' USING ERRCODE='55000'; END IF;
 INSERT INTO package_history_exposure_bridge.installation_functions(signature,original_oid,original_body_digest) VALUES('package_historical_research.already_exposed(uuid[],uuid)',p.oid,'d9a5a187a971638b43aae13935971e7c2c4aaf4dfb0968e1829c35bc67d23722');
END $verify$;

DO $verify$ DECLARE p pg_proc; BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('package_historical_research.freeze_cohort(uuid,timestamp with time zone,timestamp with time zone,jsonb,uuid,uuid)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'jsonb'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, package_historical_research, design, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'5acaf51eb129be94d83247779b815c2b9d9b95b0879d01a03e1eebe235c8a6eb'
 THEN RAISE EXCEPTION 'package_history_bridge_function_drift: package_historical_research.freeze_cohort(uuid,timestamp with time zone,timestamp with time zone,jsonb,uuid,uuid)' USING ERRCODE='55000'; END IF;
 INSERT INTO package_history_exposure_bridge.installation_functions(signature,original_oid,original_body_digest) VALUES('package_historical_research.freeze_cohort(uuid,timestamp with time zone,timestamp with time zone,jsonb,uuid,uuid)',p.oid,'5acaf51eb129be94d83247779b815c2b9d9b95b0879d01a03e1eebe235c8a6eb');
END $verify$;

DO $verify$ DECLARE p pg_proc; BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('package_historical_research.current_cohort(uuid)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'boolean'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, package_historical_research, design, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'381f6ad92ab158f645697dfeb43a9f21c09c7e2c01b29f423a6b0253d9e7f653'
 THEN RAISE EXCEPTION 'package_history_bridge_function_drift: package_historical_research.current_cohort(uuid)' USING ERRCODE='55000'; END IF;
 INSERT INTO package_history_exposure_bridge.installation_functions(signature,original_oid,original_body_digest) VALUES('package_historical_research.current_cohort(uuid)',p.oid,'381f6ad92ab158f645697dfeb43a9f21c09c7e2c01b29f423a6b0253d9e7f653');
END $verify$;

-- Reviewed existing consumers must retain their own lease/purpose guards.
DO $verify$ DECLARE p pg_proc; BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('model_governance.claim_job(uuid,uuid)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'jsonb'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, model_governance, design, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'21e373ca812486b2e8789321addf0392f85aa01ed3935fa48cd3db40880ba911'
 THEN RAISE EXCEPTION 'package_history_bridge_function_drift: model_governance.claim_job(uuid,uuid)' USING ERRCODE='55000'; END IF;
 INSERT INTO package_history_exposure_bridge.installation_functions(signature,original_oid,original_body_digest) VALUES('model_governance.claim_job(uuid,uuid)',p.oid,'21e373ca812486b2e8789321addf0392f85aa01ed3935fa48cd3db40880ba911');
END $verify$;

DO $verify$ DECLARE p pg_proc; BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('model_governance.assert_lease(uuid,uuid,bigint)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'model_governance.jobs'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, model_governance, design, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'f078d80b81f383c7a2a6d8a6242c75d1166a64cea29a7be746c58498bcd0d32b'
 THEN RAISE EXCEPTION 'package_history_bridge_function_drift: model_governance.assert_lease(uuid,uuid,bigint)' USING ERRCODE='55000'; END IF;
 INSERT INTO package_history_exposure_bridge.installation_functions(signature,original_oid,original_body_digest) VALUES('model_governance.assert_lease(uuid,uuid,bigint)',p.oid,'f078d80b81f383c7a2a6d8a6242c75d1166a64cea29a7be746c58498bcd0d32b');
END $verify$;

DO $verify$ DECLARE p pg_proc; BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('model_governance.read_training(uuid,uuid,bigint)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'jsonb'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, model_governance, design, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'bf110ac00133d803db072c6086aad3f601b5c36be274eeba244cbc129852b102'
 THEN RAISE EXCEPTION 'package_history_bridge_function_drift: model_governance.read_training(uuid,uuid,bigint)' USING ERRCODE='55000'; END IF;
 INSERT INTO package_history_exposure_bridge.installation_functions(signature,original_oid,original_body_digest) VALUES('model_governance.read_training(uuid,uuid,bigint)',p.oid,'bf110ac00133d803db072c6086aad3f601b5c36be274eeba244cbc129852b102');
END $verify$;

DO $verify$ DECLARE p pg_proc; BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('model_governance.open_final(uuid,uuid,bigint,uuid)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'uuid'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, model_governance, design, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'3ce25327a3ef059bde72d8c738875af8bccf5f189b3f34b45dfd8003b17ec12c'
 THEN RAISE EXCEPTION 'package_history_bridge_function_drift: model_governance.open_final(uuid,uuid,bigint,uuid)' USING ERRCODE='55000'; END IF;
 INSERT INTO package_history_exposure_bridge.installation_functions(signature,original_oid,original_body_digest) VALUES('model_governance.open_final(uuid,uuid,bigint,uuid)',p.oid,'3ce25327a3ef059bde72d8c738875af8bccf5f189b3f34b45dfd8003b17ec12c');
END $verify$;

DO $verify$ DECLARE p pg_proc; BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('model_governance.read_final(uuid,uuid,bigint)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'jsonb'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, model_governance, design, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'18f6584877cb93d3d05f1e9632e01ff903b406d97a2e6ab4874b046ad91f3a7e'
 THEN RAISE EXCEPTION 'package_history_bridge_function_drift: model_governance.read_final(uuid,uuid,bigint)' USING ERRCODE='55000'; END IF;
 INSERT INTO package_history_exposure_bridge.installation_functions(signature,original_oid,original_body_digest) VALUES('model_governance.read_final(uuid,uuid,bigint)',p.oid,'18f6584877cb93d3d05f1e9632e01ff903b406d97a2e6ab4874b046ad91f3a7e');
END $verify$;

DO $verify$ DECLARE p pg_proc; BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('model_governance.renew_job(uuid,uuid,bigint)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'boolean'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, model_governance, design, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'139caa2ead7950735062e5056992cd15beee1e8863fe8fb804b2fcbaf3734e98'
 THEN RAISE EXCEPTION 'package_history_bridge_function_drift: model_governance.renew_job(uuid,uuid,bigint)' USING ERRCODE='55000'; END IF;
 INSERT INTO package_history_exposure_bridge.installation_functions(signature,original_oid,original_body_digest) VALUES('model_governance.renew_job(uuid,uuid,bigint)',p.oid,'139caa2ead7950735062e5056992cd15beee1e8863fe8fb804b2fcbaf3734e98');
END $verify$;

DO $verify$ DECLARE p pg_proc; BEGIN
 SELECT * INTO p FROM pg_proc WHERE oid=to_regprocedure('model_governance.finish_job(uuid,uuid,bigint,design.sha256,jsonb)');
 IF p.oid IS NULL OR p.proowner<>current_user::regrole OR NOT p.prosecdef OR p.prorettype<>'boolean'::regtype
 OR p.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, model_governance, design, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>'296d64a4c0453faf2dd4dc944a8379028ce4f3b7496a9d4f7f19bded66020789'
 THEN RAISE EXCEPTION 'package_history_bridge_function_drift: model_governance.finish_job(uuid,uuid,bigint,design.sha256,jsonb)' USING ERRCODE='55000'; END IF;
 INSERT INTO package_history_exposure_bridge.installation_functions(signature,original_oid,original_body_digest) VALUES('model_governance.finish_job(uuid,uuid,bigint,design.sha256,jsonb)',p.oid,'296d64a4c0453faf2dd4dc944a8379028ce4f3b7496a9d4f7f19bded66020789');
END $verify$;

CREATE FUNCTION package_history_exposure_bridge.entities()
RETURNS TABLE(entity text,bid_id uuid,submission_id uuid,submitted_at timestamptz)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT 'package:'||a.id,a.bid_id,a.submission_id,(p.native_context#>>'{submission,submitted_at}')::timestamptz
 FROM package_historical_research.admissions a JOIN package_historical_research.proofs p ON p.id=a.proof_id
 UNION ALL
 SELECT 'body:'||s.id,s.bid_id,s.submission_id,r.submitted_at
 FROM design.samples s JOIN design.submission_records r ON r.id=s.submission_id
$$;

-- Grouping is conservative source identity, never a qualification shortcut.
-- All immutable historical aliases and prior closure keys remain connected.
-- No latest parse or current mutable profile can erase an original identity.
CREATE FUNCTION package_history_exposure_bridge.entity_keys()
RETURNS TABLE(entity text,kind text,identity text)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 WITH native AS MATERIALIZED (
  SELECT 'package:'||a.id entity,a.id,a.bid_id,a.submission_id,p.native_context ctx,p.normalized
  FROM package_historical_research.admissions a JOIN package_historical_research.proofs p ON p.id=a.proof_id
 ), legacy AS MATERIALIZED (
  SELECT 'body:'||s.id entity,s.*,r.body_version_id,r.review_id,r.evidence,ri.material_snapshot_id,o.source_version_id
  FROM design.samples s JOIN design.submission_records r ON r.id=s.submission_id
  JOIN design.outcomes o ON o.id=s.outcome_id LEFT JOIN design.review_runs rr ON rr.id=r.review_id
  LEFT JOIN design.review_inputs ri ON ri.id=rr.input_id
 ), legacy_documents AS MATERIALIZED (
  SELECT entity,body_version_id document_version_id FROM legacy
  UNION SELECT entity,source_version_id FROM legacy
  UNION SELECT l.entity,m.document_version_id FROM legacy l JOIN design.material_assignments m ON m.snapshot_id=l.material_snapshot_id
  UNION SELECT 'body:'||p.sample_id,p.document_version_id FROM model_governance.parse_bindings p
  UNION SELECT 'body:'||b.sample_id,n.document_version_id FROM model_governance.source_bindings b JOIN retrieval.source_nodes n ON n.id=b.ancestor_id
 ), legacy_originals AS MATERIALIZED (
  SELECT entity,document_version_id FROM legacy_documents
  UNION SELECT d.entity,parent.document_version_id FROM legacy_documents d
   JOIN retrieval.source_nodes n ON n.document_version_id=d.document_version_id
   JOIN retrieval.source_ancestors a ON a.source_id=n.id JOIN retrieval.source_nodes parent ON parent.id=a.ancestor_id
 ), facts AS (
  SELECT n.entity,'entity'::text kind,n.entity identity FROM native n
  UNION ALL SELECT l.entity,'entity',l.entity FROM legacy l
  UNION ALL SELECT n.entity,CASE k.kind WHEN 'body' THEN 'bytes' ELSE k.kind END,k.identity FROM native n JOIN package_historical_research.admission_keys k ON k.admission_id=n.id
  UNION ALL SELECT n.entity,v.kind,v.identity FROM native n CROSS JOIN LATERAL (VALUES
   ('project',n.ctx#>>'{identity,engineering_project_id}'),('lot',n.ctx#>>'{identity,lot_id}'),
   ('round',n.ctx#>>'{identity,round_id}'),('scope',n.ctx#>>'{scope,id}'),('submission',n.submission_id::text))v(kind,identity)
  UNION ALL SELECT n.entity,'bytes',v->>'digest' FROM native n CROSS JOIN LATERAL jsonb_array_elements(n.ctx->'originals')v
  UNION ALL SELECT n.entity,'bytes',n.ctx#>>'{label,file_digest}' FROM native n
  UNION ALL SELECT n.entity,'bytes',v->>'digest' FROM native n CROSS JOIN LATERAL jsonb_array_elements(n.ctx#>'{label,source_proof,heads}')v
  UNION ALL SELECT l.entity,v.kind,v.identity FROM legacy l CROSS JOIN LATERAL (VALUES
   ('submission',l.submission_id::text),('source_group',l.source_group_id::text),
   ('project',l.evidence#>>'{identity,engineering_project_id}'),('lot',l.evidence#>>'{identity,lot_id}'),('round',l.evidence#>>'{identity,round_id}'))v(kind,identity)
  UNION ALL SELECT l.entity,v.kind,v.identity FROM legacy l JOIN design.bid_profiles p ON p.bid_id=l.bid_id JOIN design.bid_rounds r ON r.id=p.round_id
   CROSS JOIN LATERAL (VALUES('project',r.engineering_project_id::text),('lot',r.lot_id::text),('round',r.id::text))v(kind,identity)
  UNION ALL SELECT l.entity,v.kind,v.identity FROM legacy l JOIN design.audit_entries a ON a.bid_id=l.bid_id AND a.event_type='identity.bound'
   CROSS JOIN LATERAL (VALUES('project',a.payload#>>'{after,engineering_project_id}'),('lot',a.payload#>>'{after,lot_id}'),('round',a.payload#>>'{after,round_id}'))v(kind,identity)
  UNION ALL SELECT 'body:'||m.sample_id,v.kind,v.identity FROM model_governance.members m CROSS JOIN LATERAL (VALUES
   ('project',m.project_id::text),('source_group',m.group_id::text),('bytes',m.body_digest::text),
   ('lot',m.identity_snapshot->>'lot_id'),('round',m.identity_snapshot->>'round_id'),('template',m.template_key),('near_duplicate',m.near_duplicate_key))v(kind,identity)
  UNION ALL SELECT l.entity,v.kind,v.identity FROM legacy l JOIN design.decisions d ON d.object_id=l.id AND d.object_kind='sample_group'
   CROSS JOIN LATERAL (SELECT CASE WHEN d.reason IS JSON OBJECT THEN d.reason::jsonb ELSE '{}'::jsonb END value)j
   CROSS JOIN LATERAL (VALUES('template',j.value->>'template_key'),('near_duplicate',j.value->>'near_duplicate_key'))v(kind,identity)
  UNION ALL SELECT d.entity,'bytes',b.digest::text FROM legacy_originals d JOIN design.document_versions v ON v.id=d.document_version_id JOIN design.blobs b ON b.id=v.blob_id
  UNION ALL SELECT a.entity,a.kind,a.identity FROM package_history_exposure_bridge.entity_aliases a
  UNION ALL SELECT e->>'entity',k->>'kind',k->>'identity' FROM package_history_exposure_bridge.exposure_receipts r
   CROSS JOIN LATERAL jsonb_array_elements(r.snapshot)e CROSS JOIN LATERAL jsonb_array_elements(e->'keys')k
  UNION ALL SELECT e->>'entity',k->>'kind',k->>'identity' FROM package_history_exposure_bridge.cohort_bindings r
   CROSS JOIN LATERAL jsonb_array_elements(r.snapshot)e CROSS JOIN LATERAL jsonb_array_elements(e->'keys')k
 ) SELECT DISTINCT f.entity,f.kind,f.identity FROM facts f WHERE f.identity IS NOT NULL AND f.identity<>''
$$;

CREATE FUNCTION package_history_exposure_bridge.related_entities(seeds text[]) RETURNS text[]
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE result text[];
BEGIN
 IF seeds IS NULL OR cardinality(seeds)=0 OR cardinality(seeds)>20000
 OR (SELECT count(*) FROM package_history_exposure_bridge.entities())>20000
 THEN RAISE EXCEPTION 'package_history_bridge_capacity_or_seeds_invalid' USING ERRCODE='54000'; END IF;
 WITH RECURSIVE keys AS MATERIALIZED(SELECT * FROM package_history_exposure_bridge.entity_keys()), closure(entity) AS (
  SELECT unnest(seeds) UNION SELECT r.entity FROM closure c JOIN keys l ON l.entity=c.entity JOIN keys r ON r.kind=l.kind AND r.identity=l.identity
 ) SELECT array_agg(entity ORDER BY entity) INTO result FROM closure;
 IF cardinality(result)>20000 THEN RAISE EXCEPTION 'package_history_bridge_capacity_exceeded' USING ERRCODE='54000'; END IF;
 RETURN result;
END $$;

CREATE FUNCTION package_history_exposure_bridge.closure_snapshot(seeds text[]) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 WITH closure AS MATERIALIZED(SELECT unnest(package_history_exposure_bridge.related_entities(seeds))entity),
 keys AS MATERIALIZED(SELECT * FROM package_history_exposure_bridge.entity_keys())
 SELECT jsonb_agg(jsonb_build_object('entity',c.entity,'bid_id',e.bid_id,'submission_id',e.submission_id,'submitted_at',e.submitted_at,
  'keys',(SELECT jsonb_agg(jsonb_build_object('kind',k.kind,'identity',k.identity) ORDER BY k.kind,k.identity) FROM keys k WHERE k.entity=c.entity)) ORDER BY c.entity)
 FROM closure c LEFT JOIN package_history_exposure_bridge.entities()e USING(entity)
$$;

CREATE FUNCTION package_history_exposure_bridge.related_bids(seeds text[]) RETURNS uuid[]
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT array_agg(DISTINCT e.bid_id ORDER BY e.bid_id) FROM package_history_exposure_bridge.entities()e
 WHERE e.entity=ANY(package_history_exposure_bridge.related_entities(seeds))
$$;

CREATE FUNCTION package_history_exposure_bridge.lock_scope(seeds text[]) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE bids uuid[]; bid uuid;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'package_history_bridge_read_committed_required' USING ERRCODE='55000'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 bids:=package_history_exposure_bridge.related_bids(seeds);
 IF bids IS NULL THEN RAISE EXCEPTION 'package_history_bridge_subject_missing' USING ERRCODE='P0002'; END IF;
 FOREACH bid IN ARRAY bids LOOP PERFORM design.lock_worker_bid(bid); END LOOP;
 PERFORM pg_advisory_xact_lock(90127,1);
 -- A source-edge writer can enter before the graph lock. Never acquire an
 -- additional bid out of order after the graph lock; restart the transaction.
 IF bids IS DISTINCT FROM package_history_exposure_bridge.related_bids(seeds) THEN
  RAISE EXCEPTION 'package_history_bridge_relation_changed_retry' USING ERRCODE='40001';
 END IF;
 PERFORM pg_advisory_xact_lock(91144,1);
END $$;

CREATE FUNCTION package_history_exposure_bridge.has_foreign_exposure(seeds text[],own_namespace text,own_cohort uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ids text[]; receipt record;
BEGIN
 ids:=package_history_exposure_bridge.related_entities(seeds);
 FOR receipt IN SELECT * FROM package_history_exposure_bridge.exposure_receipts r
 WHERE (r.namespace,r.cohort_id) IS DISTINCT FROM (own_namespace,own_cohort) LOOP
  -- Re-expand persisted original seeds through ALL current and retained keys.
  -- A newly imported unselected intermediary expands an old exposure forever.
  IF ids && package_history_exposure_bridge.related_entities(receipt.seeds) THEN RETURN true; END IF;
 END LOOP;
 RETURN false;
END $$;

CREATE FUNCTION package_history_exposure_bridge.native_binding_current(target uuid) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT EXISTS(SELECT FROM package_history_exposure_bridge.cohort_bindings b JOIN package_historical_research.cohorts c ON c.id=b.cohort_id
 WHERE b.namespace='package' AND c.id=target AND b.cohort_digest=c.digest AND b.membership_digest=c.membership_digest
 AND b.snapshot=package_history_exposure_bridge.closure_snapshot(b.seeds)
 AND NOT EXISTS(SELECT FROM package_historical_research.members m WHERE m.cohort_id=c.id AND
  ((SELECT count(DISTINCT (e.submitted_at<c.submission_split_at)) FROM package_history_exposure_bridge.entities()e
    WHERE e.entity=ANY(package_history_exposure_bridge.related_entities(ARRAY['package:'||m.admission_id])))>1)
  IS DISTINCT FROM (m.exclusion_reason IS NOT DISTINCT FROM 'group_spans_submission_split')))
$$;

CREATE FUNCTION package_history_exposure_bridge.bind_native_cohort(target uuid,selected uuid[]) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE seeds text[]; value jsonb; c package_historical_research.cohorts;
BEGIN
 SELECT * INTO STRICT c FROM package_historical_research.cohorts WHERE id=target;
 SELECT array_agg('package:'||id ORDER BY id) INTO seeds FROM unnest(selected)id;
 PERFORM package_history_exposure_bridge.lock_scope(seeds);
 value:=package_history_exposure_bridge.closure_snapshot(seeds);
 INSERT INTO package_history_exposure_bridge.cohort_bindings VALUES('package',target,c.digest,c.membership_digest,seeds,value,design.package_technical_digest(value),clock_timestamp());
END $$;

CREATE FUNCTION package_history_exposure_bridge.legacy_binding_current(target uuid) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT EXISTS(SELECT FROM package_history_exposure_bridge.cohort_bindings b JOIN model_governance.cohorts c ON c.id=b.cohort_id
 WHERE b.namespace='body' AND c.id=target AND b.cohort_digest=c.digest
 AND b.membership_digest=(SELECT design.package_technical_digest(jsonb_agg(to_jsonb(m) ORDER BY m.sample_id)) FROM model_governance.members m WHERE m.cohort_id=target)
 AND b.snapshot=package_history_exposure_bridge.closure_snapshot(b.seeds))
$$;

CREATE FUNCTION package_history_exposure_bridge.legacy_purpose_closed(target uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE m record; ids text[]; boundary timestamptz;
BEGIN
 SELECT test_start INTO boundary FROM model_governance.cohorts WHERE id=target;
 FOR m IN SELECT * FROM model_governance.members WHERE cohort_id=target AND purpose<>'excluded' LOOP
  ids:=package_history_exposure_bridge.related_entities(ARRAY['body:'||m.sample_id]);
  IF (SELECT count(DISTINCT (e.submitted_at<boundary)) FROM package_history_exposure_bridge.entities()e WHERE e.entity=ANY(ids))<>1
  OR EXISTS(SELECT FROM model_governance.members other WHERE other.cohort_id=target AND other.purpose NOT IN('excluded',m.purpose) AND 'body:'||other.sample_id=ANY(ids))
  THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;

CREATE FUNCTION package_history_exposure_bridge.bind_legacy_cohort(target uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE seeds text[]; value jsonb; c model_governance.cohorts; members_digest text;
BEGIN
 SELECT * INTO STRICT c FROM model_governance.cohorts WHERE id=target;
 SELECT array_agg('body:'||sample_id ORDER BY sample_id),design.package_technical_digest(jsonb_agg(to_jsonb(m) ORDER BY m.sample_id)) INTO seeds,members_digest FROM model_governance.members m WHERE cohort_id=target;
 IF seeds IS NULL THEN RETURN; END IF;
 PERFORM package_history_exposure_bridge.lock_scope(seeds);
 value:=package_history_exposure_bridge.closure_snapshot(seeds);
 INSERT INTO package_history_exposure_bridge.cohort_bindings VALUES('body',target,c.digest,members_digest,seeds,value,design.package_technical_digest(value),clock_timestamp());
END $$;

CREATE FUNCTION package_history_exposure_bridge.capture_legacy_cohort() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF (SELECT count(*) FROM model_governance.exports WHERE cohort_id=NEW.cohort_id)=3
 AND NOT EXISTS(SELECT FROM package_history_exposure_bridge.cohort_bindings WHERE namespace='body' AND cohort_id=NEW.cohort_id)
 THEN PERFORM package_history_exposure_bridge.bind_legacy_cohort(NEW.cohort_id); END IF;
 RETURN NEW;
END $$;

-- Captures only frozen rows; never calls current_cohort and therefore cannot
-- recursively re-enter itself via exposure/currentness checks.
CREATE FUNCTION package_history_exposure_bridge.capture_exposure(namespace text,target uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE x record; seeds text[]; value jsonb;
BEGIN
 IF namespace='package' THEN
  SELECT e.cohort_id,e.cohort_digest,e.membership_digest,p.model_digest,e.predictions_digest,pr.digest protocol_digest,e.created_xact,e.created_at INTO STRICT x
   FROM package_historical_research.exposures e JOIN package_historical_research.predictions p ON p.job_id=e.job_id
   JOIN package_historical_research.cohorts c ON c.id=e.cohort_id JOIN package_historical_research.protocols pr ON pr.id=c.protocol_id WHERE e.id=target;
  SELECT array_agg('package:'||m.admission_id ORDER BY m.admission_id) INTO seeds FROM package_historical_research.members m JOIN package_historical_research.cohorts c ON c.id=m.cohort_id WHERE c.id=x.cohort_id AND m.submitted_at>=c.submission_split_at;
 ELSIF namespace='body' THEN
  SELECT c.id cohort_id,c.digest cohort_digest,(SELECT design.package_technical_digest(jsonb_agg(to_jsonb(m) ORDER BY m.sample_id)) FROM model_governance.members m WHERE m.cohort_id=c.id)membership_digest,
   e.model_digest,e.predictions_digest,e.protocol_digest,e.created_xact,e.opened_at created_at INTO STRICT x
   FROM model_governance.exposures e JOIN model_governance.jobs j ON j.id=e.job_id JOIN model_governance.cohorts c ON c.id=j.cohort_id WHERE e.id=target;
  SELECT array_agg('body:'||sample_id ORDER BY sample_id) INTO seeds FROM model_governance.members WHERE cohort_id=x.cohort_id AND purpose='final';
 ELSE RAISE EXCEPTION 'package_history_bridge_namespace_invalid' USING ERRCODE='23514'; END IF;
 PERFORM package_history_exposure_bridge.lock_scope(seeds);
 value:=package_history_exposure_bridge.closure_snapshot(seeds);
 INSERT INTO package_history_exposure_bridge.exposure_receipts VALUES(namespace,target,x.cohort_id,x.cohort_digest,x.membership_digest,x.model_digest,x.predictions_digest,x.protocol_digest,
  seeds,value,design.package_technical_digest(value),x.created_xact,x.created_at,clock_timestamp());
END $$;

CREATE FUNCTION package_history_exposure_bridge.capture_new_exposure() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF TG_TABLE_SCHEMA='package_historical_research' THEN
  IF NOT pg_has_role(session_user,'tender_package_history_evaluate','member') THEN RAISE EXCEPTION 'package_history_bridge_exposure_purpose_denied' USING ERRCODE='42501'; END IF;
  PERFORM package_history_exposure_bridge.capture_exposure('package',NEW.id);
 ELSE
  IF NOT pg_has_role(session_user,'tender_model_evaluate','member') THEN RAISE EXCEPTION 'package_history_bridge_exposure_purpose_denied' USING ERRCODE='42501'; END IF;
  PERFORM package_history_exposure_bridge.capture_exposure('body',NEW.id);
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION package_history_exposure_bridge.reject_exposed_legacy_admission() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE seeds text[]:=ARRAY['body:'||NEW.id];
BEGIN
 -- This is an AFTER trigger so every relation is visible, including a newly
 -- imported intermediary. Its exception rolls the whole admission back.
 IF NEW.admission='admitted' THEN
  PERFORM package_history_exposure_bridge.lock_scope(seeds);
  IF package_history_exposure_bridge.has_foreign_exposure(seeds,NULL,NULL) THEN
   RAISE EXCEPTION 'package_history_bridge_final_already_exposed' USING ERRCODE='55000';
  END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION package_history_exposure_bridge.retain_legacy_identity() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF TG_OP='UPDATE' AND (NEW.id,NEW.bid_id,NEW.submission_id,NEW.outcome_id,NEW.known_at)
  IS DISTINCT FROM (OLD.id,OLD.bid_id,OLD.submission_id,OLD.outcome_id,OLD.known_at)
 THEN RAISE EXCEPTION 'package_history_bridge_sample_identity_immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  INSERT INTO package_history_exposure_bridge.entity_aliases(entity,kind,identity)
   VALUES('body:'||OLD.id,'source_group',OLD.source_group_id::text) ON CONFLICT DO NOTHING;
 END IF;
 INSERT INTO package_history_exposure_bridge.entity_aliases(entity,kind,identity)
  VALUES('body:'||NEW.id,'source_group',NEW.source_group_id::text) ON CONFLICT DO NOTHING;
 RETURN NEW;
END $$;

CREATE FUNCTION package_history_exposure_bridge.legacy_current_original(target uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,model_governance,design,retrieval,pg_temp AS $original$
DECLARE member record;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RETURN false; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 FOR member IN SELECT DISTINCT scope.bid_id FROM (
  SELECT bid_id FROM model_governance.members WHERE cohort_id=target
  UNION SELECT s.bid_id FROM design.samples s WHERE s.source_group_id IN (SELECT group_id FROM model_governance.members WHERE cohort_id=target)
 ) scope ORDER BY scope.bid_id LOOP
  PERFORM design.lock_worker_bid(member.bid_id);
 END LOOP;
 PERFORM pg_advisory_xact_lock(90127,1);
 IF NOT EXISTS(SELECT FROM model_governance.members WHERE cohort_id=target) THEN RETURN false; END IF;
 IF EXISTS(SELECT FROM model_governance.members m JOIN model_governance.cohorts c ON c.id=m.cohort_id
  JOIN design.outcomes o ON o.id=m.outcome_id JOIN design.submission_records submission ON submission.id=m.submission_id
  WHERE m.cohort_id=target AND (m.known_at IS DISTINCT FROM o.known_at OR m.submitted_at IS DISTINCT FROM submission.submitted_at
   OR m.known_at<m.submitted_at OR m.known_at>c.created_at OR o.score_kind<>'technical_total' OR o.value IS NULL
   OR (m.purpose IN ('fit','development','calibration') AND (m.known_at>=c.test_start OR m.submitted_at>=c.test_start))
   OR (m.purpose='final' AND m.submitted_at<c.test_start))) THEN RETURN false; END IF;
 IF EXISTS(SELECT FROM model_governance.members m CROSS JOIN LATERAL
  (VALUES('group',m.group_id::text),('project',m.project_id::text),('body',m.body_digest::text),('template',m.template_key),('near_duplicate',m.near_duplicate_key)) v(kind,identity)
  WHERE m.cohort_id=target AND m.purpose<>'excluded' AND v.identity IS NOT NULL
  GROUP BY v.kind,v.identity HAVING count(DISTINCT m.purpose)>1) THEN RETURN false; END IF;
 IF EXISTS(SELECT FROM model_governance.members frozen
  LEFT JOIN design.samples sample ON sample.id=frozen.sample_id
  LEFT JOIN design.submission_records submission ON submission.id=frozen.submission_id
  LEFT JOIN design.submission_heads sh ON sh.bid_id=frozen.bid_id
  LEFT JOIN design.outcome_heads oh ON oh.submission_id=frozen.submission_id
  LEFT JOIN design.decision_heads grouping ON grouping.bid_id=frozen.bid_id AND grouping.object_kind='sample_group' AND grouping.object_id=frozen.sample_id
  LEFT JOIN design.decision_heads verification ON verification.bid_id=frozen.bid_id AND verification.object_kind='outcome' AND verification.object_id=frozen.outcome_id
  LEFT JOIN design.bid_profiles profile ON profile.bid_id=frozen.bid_id
  LEFT JOIN design.bid_rounds round_identity ON round_identity.id=profile.round_id
  LEFT JOIN design.bidders bidder_identity ON bidder_identity.id=profile.bidder_id
  LEFT JOIN design.engineering_projects project_identity ON project_identity.id=round_identity.engineering_project_id
  LEFT JOIN design.audit_entries identity_authority ON identity_authority.id=frozen.identity_authority_id
  LEFT JOIN design.decisions verified ON verified.id=frozen.verification_decision_id
  LEFT JOIN design.outcomes official ON official.id=frozen.outcome_id
  LEFT JOIN design.document_versions official_document ON official_document.id=official.source_version_id
  WHERE frozen.cohort_id=target AND (sample.admission IS DISTINCT FROM 'admitted'
   OR sample.source_group_id IS DISTINCT FROM frozen.group_id OR sample.outcome_id IS DISTINCT FROM frozen.outcome_id
   OR sh.submission_id IS DISTINCT FROM frozen.submission_id OR oh.outcome_id IS DISTINCT FROM frozen.outcome_id
   OR submission.evidence->'identity' IS DISTINCT FROM frozen.identity_snapshot
   OR grouping.decision_id IS DISTINCT FROM frozen.grouping_decision_id
   OR verification.decision_id IS DISTINCT FROM frozen.verification_decision_id
   OR profile.bidder_id IS DISTINCT FROM (frozen.identity_snapshot->>'bidder_id')::uuid
   OR profile.round_id IS DISTINCT FROM (frozen.identity_snapshot->>'round_id')::uuid
   OR verified.decision IS DISTINCT FROM 'verified' OR verified.reason::jsonb->>'published_at' IS NULL
   OR (verified.reason::jsonb->>'published_at')::timestamptz>frozen.known_at
   OR (verified.reason::jsonb->>'published_at')::timestamptz<frozen.submitted_at
   OR official_document.obtained_at>frozen.known_at
   OR frozen.identity_snapshot->>'binding_status' IS DISTINCT FROM 'confirmed'
   OR frozen.identity_snapshot->>'authority_id' IS DISTINCT FROM frozen.identity_authority_id::text
   OR identity_authority.payload->'confirmed' IS DISTINCT FROM 'true'::jsonb
   OR identity_authority.payload->'after' IS DISTINCT FROM jsonb_build_object(
    'bidder_id',profile.bidder_id,'bidder_name',bidder_identity.name,'round_id',profile.round_id,
    'engineering_project_id',round_identity.engineering_project_id,'engineering_title',project_identity.title,
    'region',project_identity.region,'engineering_type',project_identity.engineering_type,
    'lot',round_identity.lot,'round_no',round_identity.round_no)
   OR frozen.identity_authority_id IS DISTINCT FROM (SELECT a.id FROM design.audit_entries a WHERE a.bid_id=frozen.bid_id AND a.event_type='identity.bound' ORDER BY coalesce((a.payload->>'identity_epoch')::bigint,0) DESC,a.created_at DESC,a.id DESC LIMIT 1)
  )) THEN RETURN false; END IF;
 IF EXISTS(SELECT FROM model_governance.source_bindings frozen
  LEFT JOIN retrieval.source_nodes n ON n.id=frozen.ancestor_id LEFT JOIN retrieval.source_heads h ON h.source_id=n.id LEFT JOIN design.document_versions source_document ON source_document.id=n.document_version_id
  WHERE frozen.cohort_id=target AND (n.digest IS DISTINCT FROM frozen.digest OR n.policy_class IS DISTINCT FROM frozen.policy_class OR n.kind IS DISTINCT FROM 'document' OR source_document.bid_id IS DISTINCT FROM (SELECT m.bid_id FROM model_governance.members m WHERE m.cohort_id=target AND m.sample_id=frozen.sample_id)
   OR h.status IS DISTINCT FROM 'published' OR h.revision IS DISTINCT FROM frozen.revision
   OR n.known_at IS DISTINCT FROM frozen.known_at OR h.valid_from IS DISTINCT FROM frozen.valid_from OR h.valid_until IS DISTINCT FROM frozen.valid_until
   OR h.valid_from>clock_timestamp() OR h.valid_until<=clock_timestamp()
   OR n.known_at>CASE WHEN frozen.policy_class='official_label' THEN (SELECT m.known_at FROM model_governance.members m WHERE m.cohort_id=target AND m.sample_id=frozen.sample_id)
     ELSE (SELECT least(m.submitted_at,min(authority.as_of)) FROM model_governance.members m JOIN model_governance.chapter_bindings cb ON cb.cohort_id=m.cohort_id AND cb.sample_id=m.sample_id JOIN design.research_chapter_authorities authority ON authority.chapter_package_id=cb.chapter_package_id WHERE m.cohort_id=target AND m.sample_id=frozen.sample_id GROUP BY m.submitted_at) END
   OR h.valid_from>CASE WHEN frozen.policy_class='official_label' THEN (SELECT c.created_at FROM model_governance.cohorts c WHERE c.id=target)
     ELSE (SELECT min(authority.as_of) FROM model_governance.chapter_bindings cb JOIN design.research_chapter_authorities authority ON authority.chapter_package_id=cb.chapter_package_id WHERE cb.cohort_id=target AND cb.sample_id=frozen.sample_id) END
   OR n.known_at>(SELECT c.created_at FROM model_governance.cohorts c WHERE c.id=target)
   OR NOT EXISTS(SELECT FROM retrieval.source_ancestors a WHERE a.source_id=frozen.source_id AND a.ancestor_id=frozen.ancestor_id))) THEN RETURN false; END IF;
 IF EXISTS(SELECT FROM model_governance.source_bindings selected JOIN retrieval.source_ancestors a ON a.source_id=selected.source_id
  WHERE selected.cohort_id=target AND NOT EXISTS(SELECT FROM model_governance.source_bindings frozen WHERE frozen.cohort_id=target AND frozen.sample_id=selected.sample_id AND frozen.source_id=a.source_id AND frozen.ancestor_id=a.ancestor_id)) THEN RETURN false; END IF;
 IF EXISTS(SELECT FROM model_governance.chapter_bindings cb JOIN model_governance.members m ON m.cohort_id=cb.cohort_id AND m.sample_id=cb.sample_id
  JOIN design.chapter_packages cp ON cp.id=cb.chapter_package_id JOIN design.submission_records submission ON submission.id=m.submission_id
  JOIN design.review_runs rr ON rr.id=cp.review_id JOIN design.review_inputs ri ON ri.id=rr.input_id
  WHERE cb.cohort_id=target AND (cp.bid_id<>m.bid_id OR cp.review_id IS DISTINCT FROM submission.review_id OR ri.body_version_id IS DISTINCT FROM submission.body_version_id
   OR NOT EXISTS(SELECT FROM design.rule_items rule WHERE rule.id=cp.rule_id AND rule.bid_id=m.bid_id AND rule.rule_set_id=(ri.manifest->>'rule_set_id')::uuid AND rule.kind='scoring')
   OR NOT EXISTS(SELECT FROM model_governance.parse_bindings p WHERE p.cohort_id=target AND p.sample_id=m.sample_id AND p.purpose='body' AND p.parse_id=cp.parse_id))) THEN RETURN false; END IF;
 -- Recheck exact original/parse/page/evidence; unchanged source heads do not authorize a replaced parse.
 IF EXISTS(SELECT FROM model_governance.parse_bindings frozen JOIN model_governance.members m ON m.cohort_id=frozen.cohort_id AND m.sample_id=frozen.sample_id
  LEFT JOIN design.parse_runs p ON p.id=frozen.parse_id LEFT JOIN design.document_versions d ON d.id=frozen.document_version_id
  LEFT JOIN design.blobs blob ON blob.id=d.blob_id LEFT JOIN retrieval.source_nodes n ON n.id=frozen.source_id
  LEFT JOIN retrieval.source_nodes original ON original.id=frozen.original_source_id
  WHERE frozen.cohort_id=target AND (p.bid_id IS DISTINCT FROM m.bid_id OR p.document_version_id IS DISTINCT FROM frozen.document_version_id
   OR p.id IS DISTINCT FROM (SELECT latest.id FROM design.parse_runs latest WHERE latest.document_version_id=frozen.document_version_id ORDER BY latest.created_at DESC,latest.id DESC LIMIT 1)
   OR p.coverage IS DISTINCT FROM 'complete' OR p.gaps IS DISTINCT FROM '[]'::jsonb OR p.page_count<=0
   OR p.page_count<>(SELECT count(*) FROM design.pages page WHERE page.parse_id=p.id)
   OR EXISTS(SELECT FROM design.pages page WHERE page.parse_id=p.id AND (page.quality<>'usable' OR page.gaps<>'[]'::jsonb))
   OR n.document_version_id IS DISTINCT FROM d.id OR original.document_version_id IS DISTINCT FROM d.id
   OR n.kind IS DISTINCT FROM 'document' OR original.kind IS DISTINCT FROM 'document'
   OR n.digest IS DISTINCT FROM blob.digest OR original.digest IS DISTINCT FROM blob.digest
   OR NOT EXISTS(SELECT FROM retrieval.lineage_edges e WHERE e.child_id=n.id AND e.parent_id=original.id)
   OR NOT EXISTS(SELECT FROM model_governance.source_bindings b WHERE b.cohort_id=target AND b.sample_id=m.sample_id AND b.source_id=n.id AND b.ancestor_id=n.id)
   OR (frozen.purpose='body' AND d.id IS DISTINCT FROM (SELECT s.body_version_id FROM design.submission_records s WHERE s.id=m.submission_id))
   OR (frozen.purpose='official' AND d.id IS DISTINCT FROM (SELECT o.source_version_id FROM design.outcomes o WHERE o.id=m.outcome_id))
   OR (frozen.purpose='rule' AND NOT EXISTS(SELECT FROM model_governance.chapter_bindings cb JOIN design.chapter_packages cp ON cp.id=cb.chapter_package_id JOIN design.review_runs rr ON rr.id=cp.review_id JOIN design.review_inputs ri ON ri.id=rr.input_id JOIN design.material_assignments a ON a.snapshot_id=ri.material_snapshot_id AND a.bid_id=m.bid_id AND a.role IN ('tender','supplement') WHERE cb.cohort_id=target AND cb.sample_id=m.sample_id AND a.document_version_id=d.id))
  )) THEN RETURN false; END IF;
 IF EXISTS(SELECT FROM model_governance.evidence_bindings frozen JOIN model_governance.members m ON m.cohort_id=frozen.cohort_id AND m.sample_id=frozen.sample_id
  LEFT JOIN design.evidence_blocks e ON e.id=frozen.evidence_id LEFT JOIN design.pages page ON page.parse_id=e.parse_id AND page.physical_page=e.physical_page
  WHERE frozen.cohort_id=target AND (e.bid_id IS DISTINCT FROM m.bid_id OR e.parse_id IS DISTINCT FROM frozen.parse_id
   OR e.physical_page IS DISTINCT FROM frozen.physical_page OR e.ordinal IS DISTINCT FROM frozen.ordinal OR e.digest IS DISTINCT FROM frozen.digest OR page.quality IS DISTINCT FROM 'usable')) THEN RETURN false; END IF;
 FOR member IN SELECT * FROM model_governance.members WHERE cohort_id=target LOOP
  IF NOT EXISTS(SELECT FROM model_governance.chapter_bindings cb WHERE cb.cohort_id=target AND cb.sample_id=member.sample_id) THEN RETURN false; END IF;
  IF (SELECT array_agg(DISTINCT cp.rule_id ORDER BY cp.rule_id) FROM model_governance.chapter_bindings cb JOIN design.chapter_packages cp ON cp.id=cb.chapter_package_id WHERE cb.cohort_id=target AND cb.sample_id=member.sample_id)
   IS DISTINCT FROM (SELECT array_agg(rule.id ORDER BY rule.id) FROM design.submission_records submission JOIN design.review_runs rr ON rr.id=submission.review_id JOIN design.review_inputs ri ON ri.id=rr.input_id JOIN design.rule_items rule ON rule.rule_set_id=(ri.manifest->>'rule_set_id')::uuid AND rule.bid_id=member.bid_id AND rule.kind='scoring' WHERE submission.id=member.submission_id) THEN RETURN false; END IF;
  IF (SELECT array_agg(DISTINCT e.id ORDER BY e.id) FROM model_governance.chapter_bindings cb JOIN design.chapter_packages cp ON cp.id=cb.chapter_package_id JOIN design.evidence_blocks e ON e.parse_id=cp.parse_id WHERE cb.cohort_id=target AND cb.sample_id=member.sample_id)
   IS DISTINCT FROM (SELECT array_agg(e.evidence_id ORDER BY e.evidence_id) FROM model_governance.evidence_bindings e JOIN model_governance.parse_bindings p USING(cohort_id,sample_id,parse_id) WHERE e.cohort_id=target AND e.sample_id=member.sample_id AND p.purpose='body') THEN RETURN false; END IF;
  IF (SELECT array_agg(DISTINCT evidence_id ORDER BY evidence_id) FROM model_governance.chapter_bindings cb JOIN design.chapter_packages cp ON cp.id=cb.chapter_package_id JOIN design.rule_items r ON r.id=cp.rule_id CROSS JOIN LATERAL unnest(r.evidence_ids) evidence_id WHERE cb.cohort_id=target AND cb.sample_id=member.sample_id)
   IS DISTINCT FROM (SELECT array_agg(e.evidence_id ORDER BY e.evidence_id) FROM model_governance.evidence_bindings e JOIN model_governance.parse_bindings p USING(cohort_id,sample_id,parse_id) WHERE e.cohort_id=target AND e.sample_id=member.sample_id AND p.purpose='rule') THEN RETURN false; END IF;
  IF (SELECT array_agg(DISTINCT evidence_id ORDER BY evidence_id) FROM design.decisions d CROSS JOIN LATERAL unnest(d.evidence_ids) evidence_id WHERE d.id=member.verification_decision_id AND d.decision='verified')
   IS DISTINCT FROM (SELECT array_agg(e.evidence_id ORDER BY e.evidence_id) FROM model_governance.evidence_bindings e JOIN model_governance.parse_bindings p USING(cohort_id,sample_id,parse_id) WHERE e.cohort_id=target AND e.sample_id=member.sample_id AND p.purpose='official') THEN RETURN false; END IF;
 END LOOP;
 RETURN NOT EXISTS(SELECT FROM model_governance.members m WHERE m.cohort_id=target AND NOT EXISTS(SELECT FROM model_governance.source_bindings s WHERE s.cohort_id=target AND s.sample_id=m.sample_id));
END $original$;

CREATE OR REPLACE FUNCTION model_governance.current_cohort(target uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,model_governance,design,retrieval,pg_temp AS $bridge$
DECLARE seeds text[];
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RETURN false; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT array_agg('body:'||sample_id ORDER BY sample_id) INTO seeds FROM model_governance.members WHERE cohort_id=target;
 IF seeds IS NULL THEN RETURN false; END IF;
 PERFORM package_history_exposure_bridge.lock_scope(seeds);
 IF NOT package_history_exposure_bridge.legacy_current_original(target)
 OR NOT package_history_exposure_bridge.legacy_binding_current(target)
 OR NOT package_history_exposure_bridge.legacy_purpose_closed(target) THEN RETURN false; END IF;
 RETURN NOT package_history_exposure_bridge.has_foreign_exposure(seeds,'body',target);
END $bridge$;

CREATE OR REPLACE FUNCTION design.lock_research_run_scope(target_run uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design,retrieval,pg_temp AS $bridge$
DECLARE member record; found_scope boolean:=false; seeds text[];
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'fresh_read_committed_required' USING ERRCODE='55000';
 END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT array_agg(DISTINCT 'body:'||sample.id ORDER BY 'body:'||sample.id) INTO seeds FROM design.research_runs run
  JOIN design.research_preview_samples frozen ON frozen.preview_id=run.preview_id
  JOIN design.samples sample ON sample.id=frozen.sample_id WHERE run.id=target_run;
 IF seeds IS NOT NULL THEN
  PERFORM package_history_exposure_bridge.lock_scope(seeds);
  IF package_history_exposure_bridge.has_foreign_exposure(seeds,NULL,NULL) THEN
   RAISE EXCEPTION 'package_history_bridge_final_already_exposed' USING ERRCODE='55000';
  END IF;
 END IF;
 FOR member IN SELECT DISTINCT sample.bid_id FROM design.research_runs run
  JOIN design.research_preview_samples frozen ON frozen.preview_id=run.preview_id
  JOIN design.samples sample ON sample.id=frozen.sample_id
  WHERE run.id=target_run ORDER BY sample.bid_id LOOP
  found_scope:=true;
  PERFORM design.lock_worker_bid(member.bid_id);
 END LOOP;
 IF NOT found_scope THEN RAISE EXCEPTION 'research_scope_missing' USING ERRCODE='P0002'; END IF;
END $bridge$;

CREATE OR REPLACE FUNCTION package_historical_research.related_admissions(target uuid) RETURNS uuid[]
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $bridge$
 SELECT array_agg(substring(entity FROM 9)::uuid ORDER BY substring(entity FROM 9)::uuid)
 FROM unnest(package_history_exposure_bridge.related_entities(ARRAY['package:'||target]))entity WHERE starts_with(entity,'package:')
$bridge$;

CREATE OR REPLACE FUNCTION package_historical_research.already_exposed(targets uuid[],own_cohort uuid DEFAULT NULL) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,model_governance,pg_temp AS $bridge$
 SELECT EXISTS(SELECT FROM package_historical_research.exposure_keys(targets) k WHERE
  EXISTS(SELECT FROM package_historical_research.exposure_members m JOIN package_historical_research.exposures x ON x.id=m.exposure_id WHERE m.kind=k.kind AND m.identity=k.identity AND x.cohort_id IS DISTINCT FROM own_cohort)
  OR EXISTS(SELECT FROM model_governance.exposure_members old WHERE old.kind=k.kind AND old.identity=k.identity)) OR package_history_exposure_bridge.has_foreign_exposure(ARRAY(SELECT 'package:'||id FROM unnest(targets)id),'package',own_cohort)
$bridge$;

CREATE OR REPLACE FUNCTION package_historical_research.freeze_cohort(protocol uuid,boundary timestamptz,label_cutoff timestamptz,selections jsonb,actor uuid,command uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,design,pg_temp AS $bridge$
DECLARE pr package_historical_research.protocols; selected_admission package_historical_research.admissions; selected_proof package_historical_research.proofs;
 identity uuid:=gen_random_uuid(); frozen timestamptz; origin text; selected uuid[]; all_ids uuid[]; closure uuid[]; bid uuid; related_id uuid; item jsonb; member jsonb;
 members jsonb:='[]'; doc jsonb; timing jsonb; training_rows jsonb; labels jsonb; manifest jsonb; value jsonb; membership text; reason text; intended text; project text; side timestamptz;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 PERFORM pg_advisory_xact_lock(91143,1);
 IF jsonb_typeof(selections) IS DISTINCT FROM 'array' OR jsonb_array_length(selections) NOT BETWEEN 4 AND 1000 OR (SELECT count(*) FROM package_historical_research.admissions)>10000
 OR boundary IS NULL OR label_cutoff IS NULL OR boundary>clock_timestamp() OR label_cutoff>clock_timestamp()
 OR EXISTS(SELECT FROM jsonb_array_elements(selections)s WHERE NOT design.package_json_keys(s,ARRAY['admission_id','purpose']) OR (s->>'purpose' IN('fit','development','calibration','final')) IS NOT TRUE)
 THEN RAISE EXCEPTION 'package_history_selection_invalid' USING ERRCODE='23514'; END IF;
 SELECT * INTO pr FROM package_historical_research.protocols WHERE id=protocol;
 IF NOT FOUND OR NOT EXISTS(SELECT FROM design.commands c WHERE c.id=command AND c.actor_id=actor AND c.target_id=protocol AND c.command_kind='package-history-cohort') THEN RAISE EXCEPTION 'package_history_protocol_command_missing' USING ERRCODE='23514'; END IF;
 SELECT array_agg((s->>'admission_id')::uuid ORDER BY (s->>'admission_id')::uuid) INTO selected FROM jsonb_array_elements(selections)s;
 IF cardinality(selected)<>(SELECT count(DISTINCT id) FROM unnest(selected)id) OR cardinality(selected)<>(SELECT count(*) FROM package_historical_research.admissions WHERE id=ANY(selected))
 OR cardinality(selected)<>(SELECT count(DISTINCT submission_id) FROM package_historical_research.admissions WHERE id=ANY(selected)) THEN RAISE EXCEPTION 'package_history_duplicate_or_missing_submission' USING ERRCODE='23514'; END IF;
 SELECT array_agg(DISTINCT related ORDER BY related) INTO all_ids FROM unnest(selected) s CROSS JOIN LATERAL unnest(package_historical_research.related_admissions(s)) related;
 PERFORM package_history_exposure_bridge.lock_scope(ARRAY(SELECT 'package:'||id FROM unnest(selected)id));
 -- Acquire all bids before the graph lock; new admissions share this governance lock.
 FOR bid IN SELECT DISTINCT a.bid_id FROM package_historical_research.admissions a WHERE a.id=ANY(all_ids) ORDER BY a.bid_id LOOP PERFORM design.lock_worker_bid(bid); END LOOP;
 PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(91144,1);
 IF package_historical_research.already_exposed(all_ids) THEN RAISE EXCEPTION 'package_history_final_already_exposed' USING ERRCODE='55000'; END IF;
 SELECT min(a.origin) INTO origin FROM package_historical_research.admissions a WHERE a.id=ANY(all_ids);
 IF (SELECT count(DISTINCT a.origin) FROM package_historical_research.admissions a WHERE a.id=ANY(all_ids))<>1 THEN RAISE EXCEPTION 'package_history_mixed_origins' USING ERRCODE='55000'; END IF;
 PERFORM package_historical_research.assert_origin(origin,true);
 FOREACH related_id IN ARRAY all_ids LOOP
  IF NOT package_historical_research.current_proof((SELECT proof_id FROM package_historical_research.admissions WHERE id=related_id)) THEN RAISE EXCEPTION 'package_history_related_admission_stale' USING ERRCODE='55000'; END IF;
 END LOOP;
 frozen:=clock_timestamp();
 timing:=jsonb_build_object('mode','retrospective_submission_time_holdout','historical_as_of','per_exact_actual_submission','submission_split_at',boundary,'label_available_as_of',label_cutoff,'training_frozen_at',frozen,'group_spanning_policy','exclude','prediction_timing','retrospective');
 FOR item IN SELECT entry FROM jsonb_array_elements(selections) selected_row(entry) ORDER BY entry->>'admission_id' LOOP
  SELECT * INTO selected_admission FROM package_historical_research.admissions WHERE id=(item->>'admission_id')::uuid;
  SELECT * INTO selected_proof FROM package_historical_research.proofs WHERE id=selected_admission.proof_id;
  IF NOT package_historical_research.current_proof(selected_proof.id) THEN RAISE EXCEPTION 'package_history_admission_stale' USING ERRCODE='55000'; END IF;
  closure:=package_historical_research.related_admissions(selected_admission.id); reason:=NULL;
  IF (SELECT count(DISTINCT (e.submitted_at<boundary)) FROM package_history_exposure_bridge.entities()e WHERE e.entity=ANY(package_history_exposure_bridge.related_entities(ARRAY['package:'||selected_admission.id])))>1 THEN reason:='group_spans_submission_split';
  ELSIF (selected_proof.native_context#>>'{label,known_at}')::timestamptz>label_cutoff THEN reason:='label_after_available_cutoff'; END IF;
  intended:=CASE WHEN reason IS NOT NULL THEN 'excluded' ELSE item->>'purpose' END;
  IF reason IS NULL AND ((intended='final') IS DISTINCT FROM ((selected_proof.native_context#>>'{submission,submitted_at}')::timestamptz>=boundary)) THEN RAISE EXCEPTION 'package_history_purpose_time_boundary' USING ERRCODE='23514'; END IF;
  member:=jsonb_build_object('admission_id',selected_admission.id,'proof_id',selected_proof.id,'submission_id',selected_admission.submission_id,'group_id',closure[1],'closure_ids',to_jsonb(closure),'requested_purpose',item->>'purpose','purpose',intended,'exclusion_reason',reason,'submitted_at',selected_proof.native_context#>'{submission,submitted_at}','label_known_at',selected_proof.native_context#>'{label,known_at}');
  members:=members||jsonb_build_array(member);
 END LOOP;
 IF EXISTS(SELECT r->>'group_id' FROM jsonb_array_elements(members)r WHERE r->>'purpose'<>'excluded' GROUP BY r->>'group_id' HAVING count(DISTINCT r->>'purpose')>1)
 OR (SELECT count(DISTINCT r->>'group_id') FROM jsonb_array_elements(members)r WHERE r->>'purpose'='fit')<2
 OR NOT EXISTS(SELECT FROM jsonb_array_elements(members)r WHERE r->>'purpose'='development') OR NOT EXISTS(SELECT FROM jsonb_array_elements(members)r WHERE r->>'purpose'='final')
 THEN RAISE EXCEPTION 'package_history_independent_purpose_groups_required' USING ERRCODE='23514'; END IF;
 membership:=design.package_technical_digest(members);
 doc:=jsonb_build_object('schema','package-history-cohort/1','id',identity,'protocol_id',protocol,'protocol_digest',pr.digest,'origin',origin,'timing',timing,'members',members,'membership_digest',membership,'research_only',true,'formal_eligibility','unavailable','strict_prebid_eligible',false,'online_metrics_eligible',false,'formal_sample_created',false);
 INSERT INTO package_historical_research.cohorts VALUES(identity,protocol,origin,boundary,label_cutoff,frozen,doc,design.package_technical_digest(doc),membership,actor,command);
 INSERT INTO package_historical_research.members SELECT identity,(r->>'admission_id')::uuid,(r->>'proof_id')::uuid,(r->>'submission_id')::uuid,(r->>'group_id')::uuid,ARRAY(SELECT v::uuid FROM jsonb_array_elements_text(r->'closure_ids')v),r->>'requested_purpose',r->>'purpose',r->>'exclusion_reason',(r->>'submitted_at')::timestamptz,(r->>'label_known_at')::timestamptz FROM jsonb_array_elements(members)r;
 SELECT jsonb_agg(jsonb_build_object('id',m.admission_id,'project_id',p.native_context#>>'{identity,engineering_project_id}','group_id',m.group_id,'purpose',m.purpose,'submitted_at',m.submitted_at,'label_known_at',m.label_known_at,'target',((p.native_context#>>'{label,value}')::numeric*100/(p.native_context#>>'{label,maximum}')::numeric)::text) ORDER BY m.admission_id) INTO training_rows FROM package_historical_research.members m JOIN package_historical_research.proofs p ON p.id=m.proof_id WHERE m.cohort_id=identity AND m.purpose IN('fit','development','calibration');
 value:=jsonb_build_object('schema','package-history-training-export/1','origin',origin,'cohort_id',identity,'protocol',pr.document,'timing',timing,'rows',training_rows,'membership_digest',membership);
 INSERT INTO package_historical_research.exports VALUES(identity,'training',value,design.package_technical_digest(value));
 SELECT jsonb_agg(jsonb_build_object('id',m.admission_id,'project_id',p.native_context#>>'{identity,engineering_project_id}','group_id',m.group_id,'method','package-history-project-baselines/1','engineering_type',p.native_context#>'{identity,engineering_type}','maximum',p.normalized#>'{scale,maximum}',
  'status',CASE WHEN m.purpose='final' THEN 'succeeded' WHEN m.exclusion_reason='label_after_available_cutoff' THEN 'unlabeled' ELSE 'rejected' END,
  'target',CASE WHEN m.purpose='final' THEN to_jsonb(((p.native_context#>>'{label,value}')::numeric*100/(p.native_context#>>'{label,maximum}')::numeric)::text) ELSE 'null'::jsonb END,
  'reason',m.exclusion_reason) ORDER BY m.admission_id) INTO labels FROM package_historical_research.members m JOIN package_historical_research.proofs p ON p.id=m.proof_id WHERE m.cohort_id=identity AND m.submitted_at>=boundary;
 SELECT jsonb_agg(r-'target' ORDER BY r->>'id') INTO manifest FROM jsonb_array_elements(labels)r;
 INSERT INTO package_historical_research.exports VALUES(identity,'final_labels',labels,design.package_technical_digest(labels)),(identity,'final_manifest',manifest,design.package_technical_digest(manifest));
 INSERT INTO design.audit_entries(id,actor_id,command_id,event_type,payload) VALUES(gen_random_uuid(),actor,command,'package-history.cohort-frozen',jsonb_build_object('cohort_id',identity,'digest',design.package_technical_digest(doc),'origin',origin));
 PERFORM package_history_exposure_bridge.bind_native_cohort(identity,selected);
 RETURN doc||jsonb_build_object('digest',design.package_technical_digest(doc));
END $bridge$;

CREATE OR REPLACE FUNCTION package_historical_research.current_cohort(target uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,design,pg_temp AS $bridge$
DECLARE cohort package_historical_research.cohorts; member_row package_historical_research.members; ids uuid[]; bid uuid; related_id uuid;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'package_history_read_committed_required' USING ERRCODE='55000'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT * INTO cohort FROM package_historical_research.cohorts WHERE id=target;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT array_agg(DISTINCT related ORDER BY related) INTO ids FROM package_historical_research.members m CROSS JOIN LATERAL unnest(package_historical_research.related_admissions(m.admission_id))related WHERE m.cohort_id=target;
 PERFORM package_history_exposure_bridge.lock_scope(ARRAY(SELECT 'package:'||id FROM unnest(ids)id));
 FOR bid IN SELECT DISTINCT a.bid_id FROM package_historical_research.admissions a WHERE a.id=ANY(ids) ORDER BY a.bid_id LOOP PERFORM design.lock_worker_bid(bid); END LOOP;
 PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM pg_advisory_xact_lock(91144,1);
 IF package_historical_research.already_exposed(ids,target) THEN RETURN false; END IF;
 FOREACH related_id IN ARRAY ids LOOP
  IF NOT package_historical_research.current_proof((SELECT proof_id FROM package_historical_research.admissions WHERE id=related_id)) THEN RETURN false; END IF;
 END LOOP;
 FOR member_row IN SELECT * FROM package_historical_research.members WHERE cohort_id=target LOOP
  IF member_row.closure_ids IS DISTINCT FROM package_historical_research.related_admissions(member_row.admission_id) OR member_row.group_id IS DISTINCT FROM member_row.closure_ids[1] OR NOT package_historical_research.current_proof(member_row.proof_id) THEN RETURN false; END IF;
 END LOOP;
 RETURN package_history_exposure_bridge.native_binding_current(target);
END $bridge$;

-- Backfill immutable facts while the same governance/graph/exposure fence is
-- held. Stale historical rows remain inspectable; no qualification is minted.
INSERT INTO package_history_exposure_bridge.entity_aliases(entity,kind,identity)
 SELECT 'body:'||id,'source_group',source_group_id::text FROM design.samples
 UNION SELECT 'body:'||sample_id,'source_group',group_id::text FROM model_governance.members;
DO $$ DECLARE row record; ids uuid[]; BEGIN
 FOR row IN SELECT id FROM model_governance.cohorts ORDER BY id LOOP
  PERFORM package_history_exposure_bridge.bind_legacy_cohort(row.id);
 END LOOP;
 FOR row IN SELECT id FROM package_historical_research.cohorts ORDER BY id LOOP
  SELECT array_agg(admission_id ORDER BY admission_id) INTO ids FROM package_historical_research.members WHERE cohort_id=row.id;
  PERFORM package_history_exposure_bridge.bind_native_cohort(row.id,ids);
 END LOOP;
 FOR row IN SELECT id FROM model_governance.exposures ORDER BY id LOOP
  PERFORM package_history_exposure_bridge.capture_exposure('body',row.id);
 END LOOP;
 FOR row IN SELECT id FROM package_historical_research.exposures ORDER BY id LOOP
  PERFORM package_history_exposure_bridge.capture_exposure('package',row.id);
 END LOOP;
END $$;
CREATE TRIGGER package_history_bridge_cohort AFTER INSERT ON model_governance.exports FOR EACH ROW EXECUTE FUNCTION package_history_exposure_bridge.capture_legacy_cohort();
CREATE TRIGGER package_history_bridge_exposure AFTER INSERT ON model_governance.exposures FOR EACH ROW EXECUTE FUNCTION package_history_exposure_bridge.capture_new_exposure();
CREATE TRIGGER package_history_bridge_exposure AFTER INSERT ON package_historical_research.exposures FOR EACH ROW EXECUTE FUNCTION package_history_exposure_bridge.capture_new_exposure();
CREATE TRIGGER package_history_bridge_admission AFTER INSERT OR UPDATE OF admission ON design.samples FOR EACH ROW EXECUTE FUNCTION package_history_exposure_bridge.reject_exposed_legacy_admission();
CREATE TRIGGER package_history_bridge_identity AFTER INSERT OR UPDATE ON design.samples FOR EACH ROW EXECUTE FUNCTION package_history_exposure_bridge.retain_legacy_identity();

-- Metadata only: no original, proof, label, job, audit or exposure data is read.
-- The fixed native core names deliberately exclude the independent metadata
-- directory, so installing that separately cannot grant or remove eligibility.
CREATE FUNCTION package_history_exposure_bridge.live_guard_contracts()
RETURNS TABLE(object_type text,object_oid oid,identity text,fingerprint jsonb)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $contracts$
 SELECT 'function',p.oid,p.oid::regprocedure::text,
  jsonb_build_object('owner',p.proowner,'namespace',p.pronamespace,
   'definition',encode(sha256(convert_to(pg_get_functiondef(p.oid),'UTF8')),'hex'),
   'acl',to_jsonb(coalesce(p.proacl,acldefault('f',p.proowner))))
 FROM pg_proc p WHERE p.pronamespace='package_history_exposure_bridge'::regnamespace
 OR (p.pronamespace='package_historical_research'::regnamespace AND p.proname=ANY(ARRAY[
  'assert_role','assert_origin','adapter_current','native_context','verification_material',
  'record_proof','current_proof','admission_context','admit','admission_view',
  'related_admissions','exposure_keys','already_exposed','register_protocol','freeze_cohort',
  'current_cohort','start_job','claim_job','assert_lease','read_training','open_final',
  'read_final','renew_job','finish_job','control_job','cohort_view','job_view']))
 OR p.oid IN(SELECT original_oid FROM package_history_exposure_bridge.installation_functions)
 OR p.oid IN('design.append_only()'::regprocedure,'design.lock_worker_bid(uuid)'::regprocedure)
 UNION ALL
 SELECT 'trigger',t.oid,t.tgrelid::regclass::text||'.'||t.tgname,
  jsonb_build_object('relation',t.tgrelid,'function',t.tgfoid,'enabled',t.tgenabled,
   'definition',encode(sha256(convert_to(pg_get_triggerdef(t.oid),'UTF8')),'hex'))
 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
 WHERE NOT t.tgisinternal AND (c.relnamespace='package_history_exposure_bridge'::regnamespace
 OR (t.tgname=ANY(ARRAY['package_history_bridge_cohort','package_history_bridge_exposure',
  'package_history_bridge_admission','package_history_bridge_identity']) AND
  t.tgrelid IN('design.samples'::regclass,'model_governance.exports'::regclass,
   'model_governance.exposures'::regclass,'package_historical_research.exposures'::regclass)))
 UNION ALL
 SELECT 'relation',c.oid,c.oid::regclass::text,
  jsonb_build_object('owner',c.relowner,'namespace',c.relnamespace,'kind',c.relkind,
   'acl',to_jsonb(coalesce(c.relacl,acldefault('r',c.relowner))),
   'row_security',c.relrowsecurity,'force_row_security',c.relforcerowsecurity,
   'columns',(SELECT jsonb_agg(jsonb_build_object('name',a.attname,'type',a.atttypid,
    'not_null',a.attnotnull,'dropped',a.attisdropped,'acl',to_jsonb(a.attacl)) ORDER BY a.attnum)
    FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attnum>0))
 FROM pg_class c WHERE c.relnamespace='package_history_exposure_bridge'::regnamespace AND c.relkind IN('r','p','v','m','f')
 UNION ALL
 SELECT 'namespace',n.oid,n.nspname,
  jsonb_build_object('owner',n.nspowner,'acl',to_jsonb(coalesce(n.nspacl,acldefault('n',n.nspowner))))
 FROM pg_namespace n WHERE n.oid='package_history_exposure_bridge'::regnamespace
$contracts$;

-- This RPC is the only bridge function callable by API LOGINs. The public API
-- also pins this exact function body and security signature before calling it.
-- A valid response attests installed guards only; it grants no sample, score,
-- model, trusted issuer or real-data qualification. No locks/writes occur here.
CREATE FUNCTION package_history_exposure_bridge.readiness() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $readiness$
DECLARE expected package_history_exposure_bridge.guard_manifest; live jsonb; recorded jsonb;
 state text:='ready';
BEGIN
 IF NOT pg_has_role(session_user,'tender_api','MEMBER')
 OR pg_has_role(session_user,current_user,'MEMBER')
 OR NOT EXISTS(SELECT FROM pg_roles WHERE rolname=session_user AND rolcanlogin
  AND NOT(rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication))
 THEN RAISE EXCEPTION 'package_history_bridge_readiness_role_denied' USING ERRCODE='42501'; END IF;
 SELECT * INTO expected FROM package_history_exposure_bridge.guard_manifest WHERE singleton;
 SELECT jsonb_agg(to_jsonb(c) ORDER BY object_type,identity) INTO live FROM package_history_exposure_bridge.live_guard_contracts()c;
 SELECT jsonb_agg(to_jsonb(c) ORDER BY object_type,identity) INTO recorded FROM package_history_exposure_bridge.guard_contracts c;
 IF expected.singleton IS DISTINCT FROM true OR expected.contract_count IS DISTINCT FROM 76
 OR jsonb_array_length(recorded) IS DISTINCT FROM expected.contract_count
 OR encode(sha256(convert_to(recorded::text,'UTF8')),'hex') IS DISTINCT FROM expected.contract_digest
 THEN state:='manifest_invalid';
 ELSIF live IS DISTINCT FROM recorded THEN state:='installed_guard_changed';
 ELSIF (SELECT count(*) FROM package_history_exposure_bridge.installation_functions)<>13
 OR EXISTS(SELECT FROM package_history_exposure_bridge.installation_functions f
  WHERE to_regprocedure(f.signature)::oid IS DISTINCT FROM f.original_oid)
 THEN state:='entry_identity_changed'; END IF;
 RETURN jsonb_build_object('schema','package-history-public-guard/1','configured',state='ready',
  'state',state,'contract_count',expected.contract_count,'checked_function_count',58,
  'checked_trigger_count',11,'public_metadata_only',true,'qualification_granted',false);
END $readiness$;

REVOKE ALL ON ALL TABLES IN SCHEMA package_history_exposure_bridge FROM PUBLIC,tender_api,tender_worker,tender_research_worker,tender_research_read,tender_score_read,tender_model_train,tender_model_evaluate,tender_model_score,tender_package_history_verify,tender_package_history_train,tender_package_history_evaluate,tender_package_history_test_api;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA package_history_exposure_bridge FROM PUBLIC,tender_api,tender_worker,tender_research_worker,tender_research_read,tender_score_read,tender_model_train,tender_model_evaluate,tender_model_score,tender_package_history_verify,tender_package_history_train,tender_package_history_evaluate,tender_package_history_test_api;
REVOKE ALL ON SCHEMA package_history_exposure_bridge FROM PUBLIC,tender_api,tender_worker,tender_research_worker,tender_research_read,tender_score_read,tender_model_train,tender_model_evaluate,tender_model_score,tender_package_history_verify,tender_package_history_train,tender_package_history_evaluate,tender_package_history_test_api;
GRANT USAGE ON SCHEMA package_history_exposure_bridge TO tender_api;
GRANT EXECUTE ON FUNCTION package_history_exposure_bridge.readiness() TO tender_api;
INSERT INTO package_history_exposure_bridge.guard_contracts SELECT * FROM package_history_exposure_bridge.live_guard_contracts();
INSERT INTO package_history_exposure_bridge.guard_manifest(singleton,contract_count,contract_digest)
 SELECT true,count(*)::integer,encode(sha256(convert_to(jsonb_agg(to_jsonb(c) ORDER BY object_type,identity)::text,'UTF8')),'hex')
 FROM package_history_exposure_bridge.guard_contracts c;
DO $$ BEGIN
 IF EXISTS(SELECT FROM package_history_exposure_bridge.installation_functions f WHERE to_regprocedure(f.signature)::oid IS DISTINCT FROM f.original_oid)
 THEN RAISE EXCEPTION 'package_history_bridge_function_oid_changed' USING ERRCODE='55000'; END IF;
END $$;
COMMIT;
