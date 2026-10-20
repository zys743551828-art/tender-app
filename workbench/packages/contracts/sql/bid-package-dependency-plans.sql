-- Explicit immutable human plans, with the original assessment and exact command/audit.
BEGIN;
SET search_path=design,public;
CREATE TABLE bid_package_dependency_plans(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL,
 execution_input_id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 manifest jsonb NOT NULL,
 digest sha256 NOT NULL,
 FOREIGN KEY(bid_id,execution_input_id) REFERENCES bid_package_execution_inputs(bid_id,id),
 UNIQUE(bid_id,id),
 CHECK(encode(sha256(convert_to(package_canonical_json(manifest),'UTF8')),'hex')=digest)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON bid_package_dependency_plans
 FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE FUNCTION bid_dependency_plan_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE prepared design.bid_package_execution_inputs; original design.bid_package_review_inputs;
 m jsonb; p jsonb; a jsonb; u jsonb; k text; expected jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'dependency_plan_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 SELECT * INTO prepared FROM design.bid_package_execution_inputs WHERE bid_id=NEW.bid_id AND id=NEW.execution_input_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'dependency_plan_prepared' USING ERRCODE='23514'; END IF;
 SELECT * INTO original FROM design.bid_package_review_inputs WHERE bid_id=NEW.bid_id AND id=prepared.frozen_input_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'dependency_plan_original' USING ERRCODE='23514'; END IF;
 m:=NEW.manifest; p:=m->'prepared'; a:=m#>'{assessment,manifest}'; u:=m#>'{usage,manifest}';
 IF NOT design.package_json_keys(m,ARRAY['version','kind','id','actor_id','command_id','saved_at','reason','request_digest','prepared','assessment','usage','inventory_complete','facts_qualified','review_ready','launch_available','publication_authorized'])
 OR m->>'version' IS DISTINCT FROM 'package-dependency-plan/1' OR m->>'kind' IS DISTINCT FROM 'human_dependency_plan'
 OR m->>'id' IS DISTINCT FROM NEW.id::text OR m->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
 OR m->>'command_id' IS DISTINCT FROM NEW.command_id::text
 OR jsonb_typeof(m->'reason') IS DISTINCT FROM 'string' OR length(m->>'reason') NOT BETWEEN 1 AND 2000
 OR m->>'reason' IS DISTINCT FROM btrim(m->>'reason')
 OR m->>'request_digest' !~ '^[0-9a-f]{64}$'
 OR jsonb_typeof(m->'saved_at') IS DISTINCT FROM 'string' OR (m->>'saved_at')::timestamptz IS NULL THEN
  RAISE EXCEPTION 'dependency_plan_manifest' USING ERRCODE='23514'; END IF;
 IF NOT design.package_json_keys(p,ARRAY['bid_id','package_id','revision_id','inventory_id','frozen_input_id','execution_input_id','execution_input_digest'])
 OR p->>'execution_input_id' IS DISTINCT FROM NEW.execution_input_id::text
 OR p->>'execution_input_digest' IS DISTINCT FROM prepared.digest
 OR p->>'frozen_input_id' IS DISTINCT FROM prepared.frozen_input_id::text THEN
  RAISE EXCEPTION 'dependency_plan_binding' USING ERRCODE='23514'; END IF;
 FOREACH k IN ARRAY ARRAY['bid_id','package_id','revision_id','inventory_id'] LOOP
  IF p->k IS DISTINCT FROM prepared.manifest->k THEN RAISE EXCEPTION 'dependency_plan_scope' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NOT design.package_json_keys(m->'assessment',ARRAY['manifest','digest']) OR NOT design.package_json_keys(m->'usage',ARRAY['manifest','digest'])
 OR a->>'version' IS DISTINCT FROM 'package-input-dependencies/1' OR a->>'kind' IS DISTINCT FROM 'input_dependency_assessment'
 OR u->>'version' IS DISTINCT FROM 'package-fact-usage/1' OR u->>'kind' IS DISTINCT FROM 'fact_usage_selection'
 OR a->>'purpose' IS DISTINCT FROM 'prebid_compliance' OR u->>'purpose' IS DISTINCT FROM 'prebid_compliance'
 OR m#>>'{assessment,digest}' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(a),'UTF8')),'hex')
 OR m#>>'{usage,digest}' IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(u),'UTF8')),'hex')
 OR a->'prepared' IS DISTINCT FROM p OR u->'prepared' IS DISTINCT FROM p
 OR a->>'usage_digest' IS DISTINCT FROM m#>>'{usage,digest}'
 OR a->>'frozen_digest' IS DISTINCT FROM original.digest
 OR a->>'inventory_digest' IS DISTINCT FROM original.evidence_text::jsonb#>>'{selection,inventory,digest}'
 OR jsonb_typeof(u->'selected') IS DISTINCT FROM 'array' OR (a->>'selected_fact_count')::int IS DISTINCT FROM jsonb_array_length(u->'selected')
 OR jsonb_typeof(a->'requirements') IS DISTINCT FROM 'array'
 OR (a->>'requirement_count')::int IS DISTINCT FROM jsonb_array_length(a->'requirements')
 OR (a->>'requirement_count')::int IS DISTINCT FROM jsonb_array_length(original.evidence_text::jsonb#>'{selection,inventory,manifest,requirements}') THEN
  RAISE EXCEPTION 'dependency_plan_assessment' USING ERRCODE='23514'; END IF;
 FOREACH k IN ARRAY ARRAY['inventory_complete','facts_qualified','review_ready','launch_available','publication_authorized'] LOOP
  IF m->k IS DISTINCT FROM 'false'::jsonb OR a->k IS DISTINCT FROM 'false'::jsonb THEN RAISE EXCEPTION 'dependency_plan_never_authorized' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOREACH k IN ARRAY ARRAY['facts_qualified','review_ready','launch_available','publication_authorized'] LOOP
  IF u->k IS DISTINCT FROM 'false'::jsonb THEN RAISE EXCEPTION 'dependency_plan_never_authorized' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF a->'original_bytes_verified' IS DISTINCT FROM 'false'::jsonb THEN RAISE EXCEPTION 'dependency_plan_never_authorized' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM design.commands c WHERE c.id=NEW.command_id AND c.actor_id=NEW.actor_id
 AND c.command_kind='package-dependency-plan-save' AND c.target_id=NEW.execution_input_id AND c.request_digest=m->>'request_digest'
 AND c.response=jsonb_build_object('body',jsonb_build_object('manifest',m,'digest',NEW.digest),'status',201,'headers','{}'::jsonb)) THEN
  RAISE EXCEPTION 'dependency_plan_ack' USING ERRCODE='23514'; END IF;
 expected:=jsonb_build_object('plan_id',NEW.id,'digest',NEW.digest,'execution_input_id',NEW.execution_input_id,'assessment_digest',m#>'{assessment,digest}');
 IF (SELECT count(*) FROM design.audit_entries a WHERE a.command_id=NEW.command_id AND a.event_type='package.dependency_plan.saved')<>1
 OR NOT EXISTS(SELECT 1 FROM design.audit_entries a WHERE a.command_id=NEW.command_id AND a.event_type='package.dependency_plan.saved'
 AND a.actor_id=NEW.actor_id AND a.bid_id=NEW.bid_id AND a.payload=expected) THEN
  RAISE EXCEPTION 'dependency_plan_audit' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER dependency_plan_complete AFTER INSERT ON bid_package_dependency_plans
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bid_dependency_plan_guard();
REVOKE ALL ON FUNCTION bid_dependency_plan_guard() FROM PUBLIC;
COMMIT;
