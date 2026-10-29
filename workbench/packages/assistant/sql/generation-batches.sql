-- Optional fresh extension, after assistant.sql, live-facts.sql, intent-budget.sql.
-- Reuses the native assistant jobs, outbox, model-call ledger and reservations.
BEGIN;
SET search_path=design,public;

CREATE TABLE assistant_generation_batches(
 id uuid PRIMARY KEY,bid_id uuid NOT NULL,draft_id uuid NOT NULL,
 base_draft_revision bigint NOT NULL CHECK(base_draft_revision>0),base_snapshot_id uuid NOT NULL,
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),created_by uuid NOT NULL REFERENCES members(id),
 manifest jsonb NOT NULL CHECK(jsonb_typeof(manifest)='object'),digest sha256 NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(bid_id,draft_id) REFERENCES drafts(bid_id,id),
 FOREIGN KEY(bid_id,draft_id,base_snapshot_id) REFERENCES draft_snapshots(bid_id,draft_id,id),
 UNIQUE(bid_id,draft_id,id),
 CHECK(octet_length(convert_to(package_canonical_json(manifest),'UTF8'))<=16777216),
 CHECK(encode(sha256(convert_to(package_canonical_json(manifest),'UTF8')),'hex')=digest)
);
CREATE INDEX assistant_generation_batch_history ON assistant_generation_batches(bid_id,draft_id,created_at DESC,id DESC);

CREATE TABLE assistant_generation_batch_attempts(
 batch_id uuid NOT NULL,bid_id uuid NOT NULL,draft_id uuid NOT NULL,section_id uuid NOT NULL,
 attempt integer NOT NULL CHECK(attempt BETWEEN 1 AND 5),job_id uuid NOT NULL UNIQUE REFERENCES assistant_jobs(id),
 writing_plan_id uuid NOT NULL UNIQUE REFERENCES writing_plans(id),command_id uuid NOT NULL REFERENCES commands(id),
 created_by uuid NOT NULL REFERENCES members(id),previous_job_id uuid REFERENCES assistant_jobs(id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(batch_id,section_id,attempt),
 FOREIGN KEY(bid_id,draft_id,batch_id) REFERENCES assistant_generation_batches(bid_id,draft_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(bid_id,section_id) REFERENCES sections(bid_id,id),
 CHECK((attempt=1)=(previous_job_id IS NULL))
);
CREATE INDEX assistant_generation_batch_attempt_commands ON assistant_generation_batch_attempts(command_id);

CREATE TABLE assistant_generation_batch_resolutions(
 batch_id uuid PRIMARY KEY,bid_id uuid NOT NULL,draft_id uuid NOT NULL,
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),resolved_by uuid NOT NULL REFERENCES members(id),
 decision text NOT NULL CHECK(decision IN('apply','reject')),
 result jsonb NOT NULL CHECK(jsonb_typeof(result)='object'),digest sha256 NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(bid_id,draft_id,batch_id) REFERENCES assistant_generation_batches(bid_id,draft_id,id),
 CHECK(encode(sha256(convert_to(package_canonical_json(result),'UTF8')),'hex')=digest)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON assistant_generation_batches FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON assistant_generation_batch_attempts FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON assistant_generation_batch_resolutions FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE FUNCTION assistant_generation_batch_command_valid(cmd design.commands,binding jsonb,bid uuid,draft uuid,target uuid,kind text)
RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog,design AS $$
 SELECT coalesce(
 design.package_json_keys(binding,ARRAY['command_id','actor_id','idempotency_key','request_digest','request','if_match'])
 AND binding->>'command_id'=cmd.id::text AND binding->>'actor_id'=cmd.actor_id::text
 AND cmd.command_kind=kind AND cmd.target_id=target AND binding->>'idempotency_key'=cmd.idempotency_key
 AND binding->>'request_digest'=cmd.request_digest
 AND cmd.request_digest=encode(sha256(convert_to(design.package_canonical_json(jsonb_build_object(
 'body',(binding->'request')||jsonb_build_object('bid_id',bid,'draft_id',draft),'if_match',binding->'if_match')),'UTF8')),'hex')
 AND cmd.response#>'{body,command}'=binding AND cmd.response#>>'{body,bid_id}'=bid::text
 AND cmd.response#>>'{body,draft_id}'=draft::text
 AND cmd.response#>>'{body,protocol}'='authoring-generation-batch-command/1',false)
$$;

CREATE FUNCTION assistant_generation_batch_assert_budget(batch uuid) RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE m jsonb; section jsonb; total numeric; count_jobs bigint; size_bytes numeric;
BEGIN
 SELECT manifest INTO m FROM design.assistant_generation_batches WHERE id=batch;
 IF m IS NULL THEN RAISE EXCEPTION 'generation_batch_missing' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM design.assistant_generation_batch_attempts a
 JOIN design.assistant_budget_reservations r ON r.job_id=a.job_id
 WHERE a.batch_id=batch AND (r.price_id::text IS DISTINCT FROM m#>>'{price,price_version_id}'
 OR r.currency IS DISTINCT FROM m#>>'{price,currency}')) THEN
 RAISE EXCEPTION 'generation_batch_price_binding' USING ERRCODE='23514'; END IF;
 SELECT count(*),coalesce(sum(CASE WHEN r.state IN('settled','released') THEN r.charged_minor ELSE r.reserved_minor END),0),
 coalesce(sum(octet_length(convert_to(design.package_canonical_json(j.input_manifest),'UTF8'))),0)
 INTO count_jobs,total,size_bytes FROM design.assistant_generation_batch_attempts a
 JOIN design.assistant_budget_reservations r ON r.job_id=a.job_id JOIN design.assistant_jobs j ON j.id=a.job_id WHERE a.batch_id=batch;
 IF count_jobs<>(SELECT count(*) FROM design.assistant_generation_batch_attempts WHERE batch_id=batch)
 OR total>(m#>>'{request,total_limit_minor}')::numeric OR total>9007199254740991 OR size_bytes>16777216 THEN
 RAISE EXCEPTION 'generation_batch_budget_or_capacity' USING ERRCODE='23514'; END IF;
 FOR section IN SELECT value FROM jsonb_array_elements(m->'sections') LOOP
  SELECT coalesce(sum(CASE WHEN r.state IN('settled','released') THEN r.charged_minor ELSE r.reserved_minor END),0) INTO total
  FROM design.assistant_generation_batch_attempts a JOIN design.assistant_budget_reservations r ON r.job_id=a.job_id
  WHERE a.batch_id=batch AND a.section_id::text=section->>'section_id';
  IF total>(section->>'budget_limit_minor')::numeric OR total>9007199254740991 THEN
   RAISE EXCEPTION 'generation_batch_chapter_budget' USING ERRCODE='23514'; END IF;
 END LOOP;
END $$;

CREATE FUNCTION assistant_generation_batch_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE m jsonb; request jsonb; binding jsonb; section jsonb; expected jsonb; selected jsonb;
 cmd design.commands; base design.draft_snapshots; price design.assistant_price_versions; ids jsonb; n integer; shares numeric;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
 RAISE EXCEPTION 'generation_batch_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 m:=NEW.manifest;request:=m->'request';binding:=m->'preparation';
 SELECT * INTO cmd FROM design.commands WHERE id=NEW.command_id;
 SELECT * INTO base FROM design.draft_snapshots WHERE id=NEW.base_snapshot_id AND bid_id=NEW.bid_id
 AND draft_id=NEW.draft_id AND revision=NEW.base_draft_revision;
 SELECT * INTO price FROM design.assistant_price_versions WHERE id=(m#>>'{price,price_version_id}')::uuid;
 IF NOT design.package_json_keys(m,ARRAY['protocol','generation_mode','batch_id','bid_id','draft_id','target','price','request','sections','preparation'])
 OR m->>'protocol' IS DISTINCT FROM 'authoring-generation-batch/1' OR m->>'generation_mode' IS DISTINCT FROM 'section_patch_set/1'
 OR m->>'batch_id' IS DISTINCT FROM NEW.id::text OR m->>'bid_id' IS DISTINCT FROM NEW.bid_id::text
 OR m->>'draft_id' IS DISTINCT FROM NEW.draft_id::text OR base.id IS NULL
 OR m#>'{target,base_draft_revision}' IS DISTINCT FROM to_jsonb(NEW.base_draft_revision)
 OR m#>>'{target,base_snapshot_id}' IS DISTINCT FROM NEW.base_snapshot_id::text
 OR m#>>'{target,base_snapshot_digest}' IS DISTINCT FROM base.digest
 OR m#>>'{target,base_draft_etag}' IS DISTINCT FROM ('"draft:'||NEW.draft_id::text||':'||NEW.base_draft_revision::text||'"')
 OR NOT EXISTS(SELECT 1 FROM design.drafts d WHERE d.id=NEW.draft_id AND d.bid_id=NEW.bid_id AND d.revision=NEW.base_draft_revision)
 OR jsonb_typeof(m->'sections') IS DISTINCT FROM 'array' OR jsonb_array_length(m->'sections') NOT BETWEEN 1 AND 20
 OR NOT design.package_json_keys(request,ARRAY['base_draft_revision','price_version_id','currency','amount_scale','total_limit_minor','sections','reason'])
 OR request->'base_draft_revision' IS DISTINCT FROM to_jsonb(NEW.base_draft_revision)
 OR request->>'currency' IS DISTINCT FROM price.currency OR request->'amount_scale' IS DISTINCT FROM '1000000000'::jsonb
 OR request->>'price_version_id' IS DISTINCT FROM price.id::text OR price.id IS NULL
 OR (request->>'total_limit_minor')::numeric NOT BETWEEN 1 AND 9007199254740991
 OR (request->>'total_limit_minor')::numeric<>trunc((request->>'total_limit_minor')::numeric)
 OR jsonb_typeof(request->'reason') IS DISTINCT FROM 'string' OR length(btrim(request->>'reason')) NOT BETWEEN 1 AND 1000
 OR cmd.actor_id IS DISTINCT FROM NEW.created_by OR NOT design.assistant_generation_batch_command_valid(cmd,binding,NEW.bid_id,NEW.draft_id,NEW.draft_id,'create-authoring-generation-batch')
 OR binding->'request' IS DISTINCT FROM request OR binding->'if_match' IS DISTINCT FROM m#>'{target,base_draft_etag}'
 OR cmd.response->>'status' IS DISTINCT FROM '201' OR cmd.response#>>'{body,kind}' IS DISTINCT FROM 'created'
 OR cmd.response#>>'{body,batch_id}' IS DISTINCT FROM NEW.id::text OR cmd.response#>>'{body,batch_digest}' IS DISTINCT FROM NEW.digest THEN
 RAISE EXCEPTION 'generation_batch_header_binding' USING ERRCODE='23514'; END IF;
 expected:=jsonb_build_object('price_version_id',price.id,'version',price.version,'provider',price.provider,'model',price.model,
 'currency',price.currency,'amount_scale',price.amount_scale,'input_upper',price.input_hard_ceiling,'output_upper',price.output_hard_ceiling,
 'input_per_million_minor',price.input_per_million_minor,'output_per_million_minor',price.output_per_million_minor,
 'valid_until',m#>'{price,valid_until}','source_kind',price.source_kind,'source_uri',price.source_uri,'source_sha256',price.source_sha256);
 IF m->'price' IS DISTINCT FROM expected OR (m#>>'{price,valid_until}')::timestamptz IS DISTINCT FROM price.valid_until THEN
 RAISE EXCEPTION 'generation_batch_tariff_binding' USING ERRCODE='23514'; END IF;
 n:=0;shares:=0;ids:='[]'::jsonb;
 FOR section IN SELECT value FROM jsonb_array_elements(m->'sections') LOOP
  selected:=request->'sections'->n;n:=n+1;
  IF NOT design.package_json_keys(section,ARRAY['section_id','base_section_revision','instruction','source_version_ids','selected_node_ids','max_tokens','budget_limit_minor','title','ordinal','before_digest','plan_digest'])
  OR section-ARRAY['title','ordinal','before_digest','plan_digest'] IS DISTINCT FROM selected
  OR NOT design.package_json_keys(selected,ARRAY['section_id','base_section_revision','instruction','source_version_ids','selected_node_ids','max_tokens','budget_limit_minor'])
  OR jsonb_typeof(selected->'instruction') IS DISTINCT FROM 'string' OR length(btrim(selected->>'instruction')) NOT BETWEEN 1 AND 8000
  OR jsonb_typeof(selected->'source_version_ids') IS DISTINCT FROM 'array' OR jsonb_array_length(selected->'source_version_ids')>30
  OR (selected->>'budget_limit_minor')::numeric NOT BETWEEN 1 AND 9007199254740991
  OR (selected->>'budget_limit_minor')::numeric<>trunc((selected->>'budget_limit_minor')::numeric)
  OR (selected->>'max_tokens')::integer NOT BETWEEN 1 AND least(8192,price.output_hard_ceiling)
  OR NOT EXISTS(SELECT 1 FROM design.draft_snapshot_sections ss JOIN design.section_revisions sr ON sr.id=ss.section_revision_id
   WHERE ss.snapshot_id=base.id AND sr.section_id=(section->>'section_id')::uuid
   AND sr.revision=(section->>'base_section_revision')::bigint AND sr.digest=section->>'before_digest'
   AND sr.content#>'{attrs,title}'=section->'title' AND ss.ordinal=(section->>'ordinal')::integer)
  OR NOT EXISTS(SELECT 1 FROM design.assistant_generation_batch_attempts a WHERE a.batch_id=NEW.id
   AND a.section_id=(section->>'section_id')::uuid AND a.attempt=1 AND a.command_id=NEW.command_id) THEN
   RAISE EXCEPTION 'generation_batch_section_binding' USING ERRCODE='23514'; END IF;
  ids:=ids||jsonb_build_array(section->'section_id');shares:=shares+(section->>'budget_limit_minor')::numeric;
 END LOOP;
 IF n<>jsonb_array_length(request->'sections') OR n<>(SELECT count(DISTINCT value) FROM jsonb_array_elements(ids))
 OR shares>(request->>'total_limit_minor')::numeric OR n<>(SELECT count(*) FROM design.assistant_generation_batch_attempts WHERE batch_id=NEW.id AND attempt=1)
 OR cmd.response#>'{body,created_job_ids}' IS DISTINCT FROM (SELECT jsonb_agg(a.job_id ORDER BY e.ord)
 FROM jsonb_array_elements(m->'sections') WITH ORDINALITY e(v,ord) JOIN design.assistant_generation_batch_attempts a
 ON a.batch_id=NEW.id AND a.section_id=(e.v->>'section_id')::uuid AND a.attempt=1) THEN
 RAISE EXCEPTION 'generation_batch_atomic_create' USING ERRCODE='23514'; END IF;
 PERFORM design.assistant_generation_batch_assert_budget(NEW.id);
 IF NOT EXISTS(SELECT 1 FROM design.audit_entries a WHERE a.command_id=NEW.command_id AND a.actor_id=NEW.created_by
 AND a.bid_id=NEW.bid_id AND a.event_type='authoring.generation_batch_created' AND a.payload=jsonb_build_object(
 'batch_id',NEW.id,'batch_digest',NEW.digest,'draft_id',NEW.draft_id)) THEN
 RAISE EXCEPTION 'generation_batch_create_audit' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER assistant_generation_batch_complete AFTER INSERT ON assistant_generation_batches
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION assistant_generation_batch_guard();

CREATE FUNCTION assistant_generation_batch_attempt_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE b design.assistant_generation_batches;j design.assistant_jobs;plan design.writing_plans;
 cmd design.commands;section jsonb;f jsonb;binding jsonb;request jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
 RAISE EXCEPTION 'generation_batch_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 SELECT * INTO b FROM design.assistant_generation_batches WHERE id=NEW.batch_id AND bid_id=NEW.bid_id AND draft_id=NEW.draft_id;
 SELECT * INTO j FROM design.assistant_jobs WHERE id=NEW.job_id;
 SELECT * INTO plan FROM design.writing_plans WHERE id=NEW.writing_plan_id;
 SELECT value INTO section FROM jsonb_array_elements(b.manifest->'sections') WHERE value->>'section_id'=NEW.section_id::text;
 SELECT * INTO cmd FROM design.commands WHERE id=NEW.command_id;
 f:=j.input_manifest;binding:=cmd.response#>'{body,command}';request:=binding->'request';
 IF b.id IS NULL OR section IS NULL OR j.id IS NULL OR plan.id IS NULL
 OR j.scope IS DISTINCT FROM 'project' OR j.kind IS DISTINCT FROM 'authoring' OR j.bid_id IS DISTINCT FROM NEW.bid_id
 OR j.actor_id IS DISTINCT FROM NEW.created_by OR j.writing_plan_id IS DISTINCT FROM NEW.writing_plan_id
 OR j.origin_action_id IS NOT NULL OR plan.bid_id IS DISTINCT FROM NEW.bid_id OR plan.section_id IS DISTINCT FROM NEW.section_id
 OR plan.base_section_revision IS DISTINCT FROM (section->>'base_section_revision')::bigint
 OR f->>'generation_mode' IS DISTINCT FROM 'section_patch_set/1'
 OR f->'batch_context' IS DISTINCT FROM jsonb_build_object('batch_id',NEW.batch_id,'section_id',NEW.section_id,'attempt',NEW.attempt)
 OR f->'plan' IS DISTINCT FROM plan.plan OR f->>'writing_plan_id' IS DISTINCT FROM plan.id::text
 OR f->'request' IS DISTINCT FROM section-ARRAY['selected_node_ids','budget_limit_minor','title','ordinal','before_digest','plan_digest']
 OR f#>>'{logical_intent,price_version_id}' IS DISTINCT FROM b.manifest#>>'{price,price_version_id}'
 OR encode(sha256(convert_to(design.package_canonical_json(jsonb_build_object('plan',f->'plan','project_memory',f->'project_memory')),'UTF8')),'hex') IS DISTINCT FROM section->>'plan_digest'
 OR f#>>'{plan,section_digest}' IS DISTINCT FROM section->>'before_digest'
 OR f#>'{plan,base_draft_revision}' IS DISTINCT FROM to_jsonb(b.base_draft_revision)
 OR EXISTS(SELECT 1 FROM design.assistant_generation_batch_resolutions WHERE batch_id=NEW.batch_id)
 OR NOT EXISTS(SELECT 1 FROM design.operations o WHERE o.id=j.operation_id AND o.command_id=NEW.command_id AND o.bid_id=NEW.bid_id)
 OR NOT EXISTS(SELECT 1 FROM design.assistant_budget_reservations r WHERE r.job_id=NEW.job_id AND r.actor_id=NEW.created_by)
 OR cmd.actor_id IS DISTINCT FROM NEW.created_by OR cmd.response#>>'{body,batch_id}' IS DISTINCT FROM NEW.batch_id::text
 OR cmd.response#>>'{body,batch_digest}' IS DISTINCT FROM b.digest THEN
 RAISE EXCEPTION 'generation_batch_attempt_binding' USING ERRCODE='23514'; END IF;
 IF NEW.attempt=1 THEN
  IF cmd.id IS DISTINCT FROM b.command_id OR cmd.command_kind IS DISTINCT FROM 'create-authoring-generation-batch' THEN
   RAISE EXCEPTION 'generation_batch_first_attempt_command' USING ERRCODE='23514'; END IF;
 ELSE
  IF NOT design.assistant_generation_batch_command_valid(cmd,binding,NEW.bid_id,NEW.draft_id,NEW.batch_id,'retry-authoring-generation-batch')
  OR NOT design.package_json_keys(request,ARRAY['batch_digest','section_id','previous_attempt','previous_job_id','reason'])
  OR request->>'batch_digest' IS DISTINCT FROM b.digest OR request->>'section_id' IS DISTINCT FROM NEW.section_id::text
  OR request->'previous_attempt' IS DISTINCT FROM to_jsonb(NEW.attempt-1) OR request->>'previous_job_id' IS DISTINCT FROM NEW.previous_job_id::text
  OR length(btrim(request->>'reason')) NOT BETWEEN 1 AND 1000
  OR binding->'if_match' IS DISTINCT FROM b.manifest#>'{target,base_draft_etag}'
  OR cmd.response#>>'{body,kind}' IS DISTINCT FROM 'retried' OR cmd.response->>'status' IS DISTINCT FROM '200'
  OR cmd.response#>'{body,created_job_ids}' IS DISTINCT FROM jsonb_build_array(NEW.job_id)
  OR NOT EXISTS(SELECT 1 FROM design.assistant_generation_batch_attempts a JOIN design.assistant_jobs prior ON prior.id=a.job_id
   JOIN design.operations o ON o.id=prior.operation_id JOIN design.assistant_budget_reservations r ON r.job_id=prior.id
   LEFT JOIN design.assistant_publications p ON p.job_id=prior.id
   WHERE a.batch_id=NEW.batch_id AND a.section_id=NEW.section_id AND a.attempt=NEW.attempt-1 AND a.job_id=NEW.previous_job_id
   AND o.state IN('succeeded','failed','cancelled') AND (o.state IN('failed','cancelled') OR p.state IN('stale','failed'))
   AND r.state IN('settled','released') AND NOT r.requires_manual_reconciliation
   AND NOT EXISTS(SELECT 1 FROM design.model_calls mc WHERE mc.operation_id=o.id AND mc.state IN('reserved','unknown')))
  OR EXISTS(SELECT 1 FROM design.assistant_generation_batch_attempts a JOIN design.assistant_jobs prev ON prev.id=a.job_id
   JOIN design.assistant_budget_reservations r ON r.job_id=prev.id WHERE a.batch_id=NEW.batch_id
   AND (r.state IN('sent','unknown') OR r.requires_manual_reconciliation
    OR EXISTS(SELECT 1 FROM design.model_calls mc WHERE mc.operation_id=prev.operation_id AND mc.state IN('reserved','unknown')))) THEN
   RAISE EXCEPTION 'generation_batch_retry_unproven' USING ERRCODE='23514'; END IF;
 END IF;
 PERFORM design.assistant_generation_batch_assert_budget(NEW.batch_id);
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER assistant_generation_batch_attempt_complete AFTER INSERT ON assistant_generation_batch_attempts
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION assistant_generation_batch_attempt_guard();

CREATE FUNCTION assistant_generation_batch_candidate_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE b design.assistant_generation_batches;j design.assistant_jobs;attempt design.assistant_generation_batch_attempts;
 p jsonb;f jsonb;
BEGIN
 IF NEW.payload->>'kind' IS DISTINCT FROM 'authoring_patch_set' THEN RETURN NEW; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);p:=NEW.payload;
 SELECT * INTO b FROM design.assistant_generation_batches WHERE id=(p#>>'{batch_context,batch_id}')::uuid AND bid_id=NEW.bid_id;
 SELECT * INTO j FROM design.assistant_jobs WHERE id=(p->>'job_id')::uuid;
 SELECT * INTO attempt FROM design.assistant_generation_batch_attempts WHERE batch_id=b.id AND job_id=j.id;
 f:=j.input_manifest;
 IF b.id IS NULL OR j.id IS NULL OR attempt.job_id IS NULL
 OR NOT design.package_json_keys(p,ARRAY['kind','batch_context','batch_digest','job_id','writing_plan_id','section_id','draft_id','base_section_revision','candidate','context','authority_manifest','before_section_digest','schema_digest'])
 OR NEW.base_revision IS DISTINCT FROM b.base_draft_revision OR p->>'batch_digest' IS DISTINCT FROM b.digest
 OR p->>'draft_id' IS DISTINCT FROM b.draft_id::text OR p->>'section_id' IS DISTINCT FROM attempt.section_id::text
 OR p->>'writing_plan_id' IS DISTINCT FROM attempt.writing_plan_id::text
 OR p->'batch_context' IS DISTINCT FROM f->'batch_context' OR p->'base_section_revision' IS DISTINCT FROM f#>'{request,base_section_revision}'
 OR p->>'before_section_digest' IS DISTINCT FROM f#>>'{plan,section_digest}' OR p->'context' IS DISTINCT FROM f#>'{plan,context}'
 OR NEW.request_digest IS DISTINCT FROM encode(sha256(convert_to(design.package_canonical_json(p),'UTF8')),'hex')
 OR EXISTS(SELECT 1 FROM design.assistant_generation_batch_resolutions WHERE batch_id=b.id)
 OR attempt.attempt<>(SELECT max(a.attempt) FROM design.assistant_generation_batch_attempts a WHERE a.batch_id=b.id AND a.section_id=attempt.section_id)
 OR NOT EXISTS(SELECT 1 FROM design.assistant_outputs o JOIN design.operations op ON op.id=j.operation_id
   WHERE o.job_id=j.id AND o.payload=p->'candidate' AND op.state='succeeded')
 OR NOT EXISTS(SELECT 1 FROM design.assistant_publications pub JOIN design.assistant_action_links link ON link.action_id=pub.action_id AND link.job_id=pub.job_id
   WHERE pub.job_id=j.id AND pub.action_id=NEW.id AND pub.state='published' AND link.tool='authoring.apply_patch' AND link.state='pending') THEN
 RAISE EXCEPTION 'generation_batch_candidate_unverified' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER assistant_generation_batch_candidate_complete AFTER INSERT ON proposed_actions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION assistant_generation_batch_candidate_guard();

CREATE FUNCTION assistant_generation_batch_resolution_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE b design.assistant_generation_batches;cmd design.commands;snapshot design.draft_snapshots;
 r jsonb;binding jsonb;request jsonb;item jsonb;chosen jsonb;unselected jsonb;selected_count integer;
 action design.proposed_actions;attempt design.assistant_generation_batch_attempts;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
 RAISE EXCEPTION 'generation_batch_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 SELECT * INTO b FROM design.assistant_generation_batches WHERE id=NEW.batch_id AND bid_id=NEW.bid_id AND draft_id=NEW.draft_id;
 SELECT * INTO cmd FROM design.commands WHERE id=NEW.command_id;
 r:=NEW.result;binding:=r->'command';request:=binding->'request';
 IF b.id IS NULL OR NOT design.package_json_keys(r,ARRAY['protocol','bid_id','draft_id','batch_id','batch_digest','kind','batch_state','created_job_ids','applied_section_ids','unselected_section_ids','draft_revision','snapshot_id','snapshot_digest','recorded_at','command'])
 OR r->>'protocol' IS DISTINCT FROM 'authoring-generation-batch-command/1' OR r->>'bid_id' IS DISTINCT FROM NEW.bid_id::text
 OR r->>'draft_id' IS DISTINCT FROM NEW.draft_id::text OR r->>'batch_id' IS DISTINCT FROM NEW.batch_id::text
 OR r->>'batch_digest' IS DISTINCT FROM b.digest OR r->>'kind' IS DISTINCT FROM (CASE NEW.decision WHEN 'apply' THEN 'applied' ELSE 'rejected' END)
 OR r->'batch_state' IS DISTINCT FROM r->'kind' OR r->'created_job_ids' IS DISTINCT FROM '[]'::jsonb
 OR NOT design.package_json_keys(request,ARRAY['decision','batch_digest','selections','reason'])
 OR request->>'decision' IS DISTINCT FROM NEW.decision OR request->>'batch_digest' IS DISTINCT FROM b.digest
 OR length(btrim(request->>'reason')) NOT BETWEEN 1 AND 1000 OR jsonb_typeof(request->'selections') IS DISTINCT FROM 'array'
 OR cmd.actor_id IS DISTINCT FROM NEW.resolved_by OR NOT design.assistant_generation_batch_command_valid(cmd,binding,NEW.bid_id,NEW.draft_id,NEW.batch_id,'resolve-authoring-generation-batch')
 OR cmd.response->'body' IS DISTINCT FROM r OR cmd.response->>'status' IS DISTINCT FROM '200' THEN
 RAISE EXCEPTION 'generation_batch_resolution_binding' USING ERRCODE='23514'; END IF;
 SELECT coalesce(jsonb_agg(value->'section_id' ORDER BY ordinal),'[]'::jsonb),count(*) INTO chosen,selected_count
 FROM jsonb_array_elements(request->'selections') WITH ORDINALITY e(value,ordinal);
 SELECT coalesce(jsonb_agg(value->'section_id' ORDER BY ordinal),'[]'::jsonb) INTO unselected
 FROM jsonb_array_elements(b.manifest->'sections') WITH ORDINALITY e(value,ordinal) WHERE NOT chosen ? (value->>'section_id');
 IF r->'applied_section_ids' IS DISTINCT FROM chosen OR r->'unselected_section_ids' IS DISTINCT FROM unselected
 OR selected_count<>(SELECT count(DISTINCT value) FROM jsonb_array_elements(chosen)) THEN
 RAISE EXCEPTION 'generation_batch_selection_binding' USING ERRCODE='23514'; END IF;
 IF NEW.decision='reject' THEN
  IF selected_count<>0 OR r->'draft_revision' IS DISTINCT FROM 'null'::jsonb OR r->'snapshot_id' IS DISTINCT FROM 'null'::jsonb
  OR r->'snapshot_digest' IS DISTINCT FROM 'null'::jsonb THEN
  RAISE EXCEPTION 'generation_batch_reject_mutated_draft' USING ERRCODE='23514'; END IF;
 ELSE
  IF selected_count NOT BETWEEN 1 AND 20 OR binding->'if_match' IS DISTINCT FROM b.manifest#>'{target,base_draft_etag}'
  OR r->'draft_revision' IS DISTINCT FROM to_jsonb(b.base_draft_revision+1)
  OR EXISTS(SELECT 1 FROM design.assistant_generation_batch_attempts a JOIN design.assistant_jobs j ON j.id=a.job_id
   JOIN design.operations o ON o.id=j.operation_id JOIN design.assistant_budget_reservations h ON h.job_id=j.id
   WHERE a.batch_id=b.id AND (o.state NOT IN('succeeded','failed','cancelled') OR (o.state='succeeded' AND NOT EXISTS(SELECT 1 FROM design.assistant_publications p WHERE p.job_id=j.id)) OR h.state NOT IN('settled','released')
   OR h.requires_manual_reconciliation OR EXISTS(SELECT 1 FROM design.model_calls mc WHERE mc.operation_id=o.id AND mc.state IN('reserved','unknown')))) THEN
   RAISE EXCEPTION 'generation_batch_apply_not_terminal' USING ERRCODE='23514'; END IF;
  SELECT * INTO snapshot FROM design.draft_snapshots WHERE id=(r->>'snapshot_id')::uuid AND bid_id=NEW.bid_id
   AND draft_id=NEW.draft_id AND revision=b.base_draft_revision+1 AND digest=r->>'snapshot_digest';
  IF snapshot.id IS NULL OR (SELECT count(*) FROM design.draft_snapshot_sections WHERE snapshot_id=snapshot.id)<>
   (SELECT count(*) FROM design.draft_snapshot_sections WHERE snapshot_id=b.base_snapshot_id)
   OR EXISTS(SELECT 1 FROM design.draft_snapshot_sections prior JOIN design.section_revisions sr ON sr.id=prior.section_revision_id
    WHERE prior.snapshot_id=b.base_snapshot_id AND NOT chosen ? sr.section_id::text AND NOT EXISTS(
      SELECT 1 FROM design.draft_snapshot_sections fresh WHERE fresh.snapshot_id=snapshot.id AND fresh.section_revision_id=prior.section_revision_id AND fresh.ordinal=prior.ordinal)) THEN
   RAISE EXCEPTION 'generation_batch_atomic_snapshot' USING ERRCODE='23514'; END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(request->'selections') LOOP
   SELECT * INTO action FROM design.proposed_actions WHERE id=(item->>'action_id')::uuid AND bid_id=NEW.bid_id;
   SELECT a.* INTO attempt FROM design.assistant_generation_batch_attempts a WHERE a.batch_id=b.id AND a.section_id=(item->>'section_id')::uuid
    AND a.attempt=(item->>'attempt')::integer AND a.job_id=(item->>'job_id')::uuid;
   IF NOT design.package_json_keys(item,ARRAY['section_id','attempt','job_id','action_id','candidate_digest'])
   OR action.id IS NULL OR attempt.job_id IS NULL OR action.payload->>'job_id' IS DISTINCT FROM attempt.job_id::text
   OR action.payload->>'batch_digest' IS DISTINCT FROM b.digest OR action.request_digest IS DISTINCT FROM item->>'candidate_digest'
   OR action.expires_at<=clock_timestamp() OR action.payload->>'kind' IS DISTINCT FROM 'authoring_patch_set'
   OR attempt.attempt<>(SELECT max(a.attempt) FROM design.assistant_generation_batch_attempts a WHERE a.batch_id=b.id AND a.section_id=attempt.section_id)
   OR NOT EXISTS(SELECT 1 FROM design.draft_snapshot_sections ss JOIN design.section_revisions sr ON sr.id=ss.section_revision_id
    WHERE ss.snapshot_id=snapshot.id AND sr.section_id=attempt.section_id
    AND sr.revision=(action.payload->>'base_section_revision')::bigint+1 AND sr.created_by=NEW.resolved_by
    AND sr.digest=action.payload#>>'{candidate,after_digest}' AND sr.schema_digest=action.payload->>'schema_digest')
   OR NOT EXISTS(SELECT 1 FROM design.assistant_action_links l JOIN design.action_consumptions ac ON ac.action_id=l.action_id
    WHERE l.action_id=action.id AND l.job_id=attempt.job_id AND l.state='executed' AND ac.command_id=NEW.command_id AND ac.consumed_by=NEW.resolved_by) THEN
    RAISE EXCEPTION 'generation_batch_selected_candidate' USING ERRCODE='23514'; END IF;
  END LOOP;
 END IF;
 IF EXISTS(SELECT 1 FROM design.assistant_generation_batch_attempts a JOIN design.assistant_publications p ON p.job_id=a.job_id
 JOIN design.assistant_action_links l ON l.action_id=p.action_id WHERE a.batch_id=b.id AND l.state='pending')
 OR NOT EXISTS(SELECT 1 FROM design.audit_entries a WHERE a.command_id=NEW.command_id AND a.actor_id=NEW.resolved_by
 AND a.bid_id=NEW.bid_id AND a.event_type='authoring.generation_batch_resolved' AND a.payload=jsonb_build_object(
 'batch_id',b.id,'batch_digest',b.digest,'draft_id',NEW.draft_id,'decision',NEW.decision)) THEN
 RAISE EXCEPTION 'generation_batch_close_incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER assistant_generation_batch_resolution_complete AFTER INSERT ON assistant_generation_batch_resolutions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION assistant_generation_batch_resolution_guard();

CREATE FUNCTION assistant_generation_batch_leaf_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE action design.proposed_actions;resolution design.assistant_generation_batch_resolutions;consumption design.action_consumptions;leaf design.assistant_action_links;
 expected text;
BEGIN
 SELECT * INTO action FROM design.proposed_actions WHERE id=NEW.action_id;
 IF action.payload->>'kind' IS DISTINCT FROM 'authoring_patch_set' THEN RETURN NEW; END IF;
 SELECT * INTO leaf FROM design.assistant_action_links WHERE action_id=NEW.action_id;
 IF TG_TABLE_NAME='assistant_action_links' AND leaf.state='pending' THEN RETURN NEW; END IF;
 SELECT * INTO resolution FROM design.assistant_generation_batch_resolutions WHERE batch_id=(action.payload#>>'{batch_context,batch_id}')::uuid;
 SELECT * INTO consumption FROM design.action_consumptions WHERE action_id=NEW.action_id;
 expected:=CASE WHEN resolution.decision='apply' AND EXISTS(SELECT 1 FROM jsonb_array_elements(resolution.result#>'{command,request,selections}') e(v)
 WHERE v->>'action_id'=NEW.action_id::text) THEN 'executed' ELSE 'rejected' END;
 IF resolution.batch_id IS NULL OR consumption.action_id IS NULL OR leaf.state IS DISTINCT FROM expected
 OR consumption.command_id IS DISTINCT FROM resolution.command_id OR consumption.consumed_by IS DISTINCT FROM resolution.resolved_by
 OR leaf.resolved_by IS DISTINCT FROM resolution.resolved_by OR consumption.result#>>'{assistant_resolution,state}' IS DISTINCT FROM expected
 OR consumption.result#>'{assistant_resolution,http_status}' IS DISTINCT FROM '200'::jsonb THEN
 RAISE EXCEPTION 'generation_batch_leaf_requires_atomic_resolution' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER assistant_generation_batch_leaf_complete AFTER UPDATE ON assistant_action_links
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION assistant_generation_batch_leaf_guard();
CREATE CONSTRAINT TRIGGER assistant_generation_batch_consumption_complete AFTER INSERT ON action_consumptions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION assistant_generation_batch_leaf_guard();

REVOKE ALL ON assistant_generation_batches,assistant_generation_batch_attempts,assistant_generation_batch_resolutions
 FROM PUBLIC,tender_api,tender_worker,tender_research_worker,tender_score_read,tender_research_read;
GRANT SELECT,INSERT ON assistant_generation_batches,assistant_generation_batch_attempts,assistant_generation_batch_resolutions TO tender_api;
-- The ordinary Worker only reads the frozen assistant job and native ledger.
-- API-role coordinator publishes candidates; no batch mutation grant is added.
REVOKE ALL ON FUNCTION assistant_generation_batch_command_valid(design.commands,jsonb,uuid,uuid,uuid,text),
 assistant_generation_batch_assert_budget(uuid),assistant_generation_batch_guard(),assistant_generation_batch_attempt_guard(),
 assistant_generation_batch_candidate_guard(),assistant_generation_batch_resolution_guard(),assistant_generation_batch_leaf_guard() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION assistant_generation_batch_command_valid(design.commands,jsonb,uuid,uuid,uuid,text),
 assistant_generation_batch_assert_budget(uuid) TO tender_api;
COMMIT;
