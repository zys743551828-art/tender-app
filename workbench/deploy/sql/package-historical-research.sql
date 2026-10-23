-- Optional native package CPU research after package-historical-admission.sql.
-- Fresh reviewed database only; no default BASE/recovery installation.
BEGIN;
CREATE TABLE package_historical_research.protocols(
 id uuid PRIMARY KEY,document jsonb NOT NULL,digest design.sha256 NOT NULL UNIQUE,
 created_by uuid NOT NULL REFERENCES design.members(id),command_id uuid NOT NULL REFERENCES design.commands(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(design.package_technical_digest(document)=digest)
);
CREATE TABLE package_historical_research.cohorts(
 id uuid PRIMARY KEY,protocol_id uuid NOT NULL REFERENCES package_historical_research.protocols(id),
 origin text NOT NULL CHECK(origin IN('synthetic','external_evidence')),
 submission_split_at timestamptz NOT NULL,label_available_as_of timestamptz NOT NULL,training_frozen_at timestamptz NOT NULL,
 document jsonb NOT NULL,digest design.sha256 NOT NULL,membership_digest design.sha256 NOT NULL,
 created_by uuid NOT NULL REFERENCES design.members(id),command_id uuid NOT NULL UNIQUE REFERENCES design.commands(id),
 CHECK(submission_split_at<=training_frozen_at AND label_available_as_of<=training_frozen_at),CHECK(design.package_technical_digest(document)=digest)
);
CREATE TABLE package_historical_research.members(
 cohort_id uuid NOT NULL REFERENCES package_historical_research.cohorts(id),admission_id uuid NOT NULL REFERENCES package_historical_research.admissions(id),
 proof_id uuid NOT NULL REFERENCES package_historical_research.proofs(id),submission_id uuid NOT NULL REFERENCES design.submission_records(id),
 group_id uuid NOT NULL,closure_ids uuid[] NOT NULL CHECK(cardinality(closure_ids)>0),
 requested_purpose text NOT NULL CHECK(requested_purpose IN('fit','development','calibration','final')),
 purpose text NOT NULL CHECK(purpose IN('fit','development','calibration','final','excluded')),
 exclusion_reason text CHECK(exclusion_reason IN('group_spans_submission_split','label_after_available_cutoff')),
 submitted_at timestamptz NOT NULL,label_known_at timestamptz NOT NULL,
 PRIMARY KEY(cohort_id,admission_id),UNIQUE(cohort_id,submission_id),
 CHECK((purpose='excluded')=(exclusion_reason IS NOT NULL))
);
CREATE TABLE package_historical_research.exports(
 cohort_id uuid NOT NULL REFERENCES package_historical_research.cohorts(id),purpose text NOT NULL CHECK(purpose IN('training','final_manifest','final_labels')),
 document jsonb NOT NULL,digest design.sha256 NOT NULL,PRIMARY KEY(cohort_id,purpose),
 CHECK(design.package_technical_digest(document)=digest),CHECK(octet_length(document::text)<=16777216)
);
CREATE TABLE package_historical_research.jobs(
 id uuid PRIMARY KEY,cohort_id uuid NOT NULL REFERENCES package_historical_research.cohorts(id),kind text NOT NULL CHECK(kind IN('train','evaluate')),
 state text NOT NULL CHECK(state IN('queued','running','paused','succeeded','failed','cancelled')),
 generation bigint NOT NULL DEFAULT 1 CHECK(generation>0),fence bigint NOT NULL DEFAULT 0 CHECK(fence>=0),owner_token uuid,lease_until timestamptz,
 created_by uuid NOT NULL REFERENCES design.members(id),command_id uuid NOT NULL UNIQUE REFERENCES design.commands(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK((owner_token IS NULL)=(lease_until IS NULL)),UNIQUE(cohort_id,kind)
);
CREATE TABLE package_historical_research.results(
 job_id uuid PRIMARY KEY REFERENCES package_historical_research.jobs(id),document jsonb NOT NULL,digest design.sha256 NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(design.package_technical_digest(document)=digest),CHECK(octet_length(document::text)<=16777216)
);
CREATE TABLE package_historical_research.predictions(
 job_id uuid PRIMARY KEY REFERENCES package_historical_research.jobs(id),training_job_id uuid NOT NULL REFERENCES package_historical_research.results(job_id),
 model_digest design.sha256 NOT NULL,document jsonb NOT NULL,digest design.sha256 NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(design.package_technical_digest(document)=digest)
);
CREATE TABLE package_historical_research.exposures(
 id uuid PRIMARY KEY,job_id uuid NOT NULL UNIQUE REFERENCES package_historical_research.jobs(id),cohort_id uuid NOT NULL REFERENCES package_historical_research.cohorts(id),
 cohort_digest design.sha256 NOT NULL,membership_digest design.sha256 NOT NULL,predictions_digest design.sha256 NOT NULL,
 closure_ids uuid[] NOT NULL,created_xact xid8 NOT NULL DEFAULT pg_current_xact_id(),created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE package_historical_research.exposure_members(
 exposure_id uuid NOT NULL REFERENCES package_historical_research.exposures(id),kind text NOT NULL CHECK(kind IN('admission','submission','project','body','text','template','near_duplicate')),
 identity text NOT NULL,PRIMARY KEY(exposure_id,kind,identity)
);
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['protocols','cohorts','members','exports','results','predictions','exposures','exposure_members'] LOOP
  EXECUTE format('CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_historical_research.%I FOR EACH ROW EXECUTE FUNCTION design.append_only()',tab);
 END LOOP;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA package_historical_research FROM PUBLIC,tender_api,tender_worker,tender_research_worker,tender_research_read,tender_score_read,tender_model_train,tender_model_evaluate,tender_model_score,tender_package_history_verify,tender_package_history_train,tender_package_history_evaluate,tender_package_history_test_api;

CREATE FUNCTION package_historical_research.related_admissions(target uuid) RETURNS uuid[]
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
 WITH RECURSIVE closure(id) AS (SELECT target UNION
  SELECT r.admission_id FROM closure c JOIN package_historical_research.admission_keys l ON l.admission_id=c.id
   JOIN package_historical_research.admission_keys r ON r.kind=l.kind AND r.identity=l.identity)
 SELECT array_agg(id ORDER BY id) FROM closure
$$;

CREATE FUNCTION package_historical_research.exposure_keys(targets uuid[]) RETURNS TABLE(kind text,identity text)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
 SELECT 'admission'::text,a.id::text FROM package_historical_research.admissions a WHERE a.id=ANY(targets)
 UNION SELECT k.kind,k.identity FROM package_historical_research.admission_keys k WHERE k.admission_id=ANY(targets)
$$;

CREATE FUNCTION package_historical_research.already_exposed(targets uuid[],own_cohort uuid DEFAULT NULL) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,model_governance,pg_temp AS $$
 SELECT EXISTS(SELECT FROM package_historical_research.exposure_keys(targets) k WHERE
  EXISTS(SELECT FROM package_historical_research.exposure_members m JOIN package_historical_research.exposures x ON x.id=m.exposure_id WHERE m.kind=k.kind AND m.identity=k.identity AND x.cohort_id IS DISTINCT FROM own_cohort)
  OR EXISTS(SELECT FROM model_governance.exposure_members old WHERE old.kind=k.kind AND old.identity=k.identity))
$$;

CREATE FUNCTION package_historical_research.register_protocol(payload jsonb,actor uuid,command uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,design,pg_temp AS $$
DECLARE identity uuid:=gen_random_uuid(); fingerprint text;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 IF NOT design.package_json_keys(payload,ARRAY['schema','method','families','selection_metric','tie_order','refit_with_development','interval_levels','bootstrap_iterations','seed','group_spanning_policy'])
 OR payload->>'schema' IS DISTINCT FROM 'package-history-cpu-protocol/1' OR payload#>>'{method,version}' IS DISTINCT FROM 'package-history-project-baselines/1'
 OR payload#>>'{method,purpose}' IS DISTINCT FROM 'retrospective_research' OR payload#>>'{method,features}' IS DISTINCT FROM 'not_required_by_constant_baselines'
 OR payload#>'{method,provider_requests}' IS DISTINCT FROM '0'::jsonb OR payload#>>'{method,digest}' IS DISTINCT FROM design.package_technical_digest((payload->'method')-'digest')
 OR payload->'families' IS DISTINCT FROM '["mean","median"]'::jsonb OR payload->'tie_order' IS DISTINCT FROM '["mean","median"]'::jsonb
 OR payload->>'selection_metric' IS DISTINCT FROM 'project_mae' OR payload->'refit_with_development' IS DISTINCT FROM 'false'::jsonb
 OR payload->'interval_levels' IS DISTINCT FROM '[0.8,0.9]'::jsonb OR payload->>'group_spanning_policy' IS DISTINCT FROM 'exclude'
 OR NOT design.package_json_integer(payload->'bootstrap_iterations',100) OR (payload->>'bootstrap_iterations')::bigint>10000
 OR NOT design.package_json_integer(payload->'seed',0) OR (payload->>'seed')::bigint>2147483647
 OR NOT EXISTS(SELECT FROM design.commands c WHERE c.id=command AND c.actor_id=actor AND c.command_kind='package-history-protocol')
 THEN RAISE EXCEPTION 'package_history_protocol_invalid' USING ERRCODE='23514'; END IF;
 fingerprint:=design.package_technical_digest(payload);
 PERFORM pg_advisory_xact_lock(91504,hashtext(fingerprint));
 SELECT id INTO identity FROM package_historical_research.protocols WHERE digest=fingerprint;
 IF NOT FOUND THEN identity:=gen_random_uuid(); INSERT INTO package_historical_research.protocols VALUES(identity,payload,fingerprint,actor,command,clock_timestamp()); END IF;
 RETURN jsonb_build_object('id',identity,'document',payload,'digest',fingerprint,'research_only',true,'formal_eligibility','unavailable');
END $$;

CREATE FUNCTION package_historical_research.freeze_cohort(protocol uuid,boundary timestamptz,label_cutoff timestamptz,selections jsonb,actor uuid,command uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,design,pg_temp AS $$
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
  IF (SELECT count(DISTINCT ((rp.native_context#>>'{submission,submitted_at}')::timestamptz<boundary)) FROM package_historical_research.admissions ra JOIN package_historical_research.proofs rp ON rp.id=ra.proof_id WHERE ra.id=ANY(closure))>1 THEN reason:='group_spans_submission_split';
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
 RETURN doc||jsonb_build_object('digest',design.package_technical_digest(doc));
END $$;

CREATE FUNCTION package_historical_research.current_cohort(target uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,design,pg_temp AS $$
DECLARE cohort package_historical_research.cohorts; member_row package_historical_research.members; ids uuid[]; bid uuid; related_id uuid;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'package_history_read_committed_required' USING ERRCODE='55000'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT * INTO cohort FROM package_historical_research.cohorts WHERE id=target;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT array_agg(DISTINCT related ORDER BY related) INTO ids FROM package_historical_research.members m CROSS JOIN LATERAL unnest(package_historical_research.related_admissions(m.admission_id))related WHERE m.cohort_id=target;
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
 RETURN true;
END $$;

CREATE FUNCTION package_historical_research.start_job(cohort uuid,job_kind text,actor uuid,command uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,design,pg_temp AS $$
DECLARE c package_historical_research.cohorts; job package_historical_research.jobs; trained record; manifest jsonb; predicted jsonb; base jsonb;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT * INTO c FROM package_historical_research.cohorts WHERE id=cohort;
 IF NOT FOUND OR job_kind NOT IN('train','evaluate') THEN RAISE EXCEPTION 'package_history_job_subject_missing' USING ERRCODE='P0002'; END IF;
 PERFORM package_historical_research.assert_origin(c.origin,true);
 IF NOT package_historical_research.current_cohort(cohort) THEN RAISE EXCEPTION 'package_history_cohort_stale' USING ERRCODE='55000'; END IF;
 IF NOT EXISTS(SELECT FROM design.commands cmd WHERE cmd.id=command AND cmd.actor_id=actor AND cmd.target_id=cohort AND cmd.command_kind='package-history-job') THEN RAISE EXCEPTION 'package_history_command_unbound' USING ERRCODE='23514'; END IF;
 SELECT * INTO job FROM package_historical_research.jobs WHERE cohort_id=cohort AND kind=job_kind;
 IF FOUND THEN RETURN jsonb_build_object('job_id',job.id,'cohort_id',job.cohort_id,'kind',job.kind,'state',job.state,'generation',job.generation,'research_only',true,'formal_eligibility','unavailable'); END IF;
 IF job_kind='evaluate' THEN
  SELECT j.id,r.document,r.digest INTO trained FROM package_historical_research.jobs j JOIN package_historical_research.results r ON r.job_id=j.id WHERE j.cohort_id=cohort AND j.kind='train' AND j.state='succeeded';
  IF trained.id IS NULL THEN RAISE EXCEPTION 'package_history_training_not_frozen' USING ERRCODE='55000'; END IF;
 END IF;
 INSERT INTO package_historical_research.jobs(id,cohort_id,kind,state,created_by,command_id) VALUES(gen_random_uuid(),cohort,job_kind,'queued',actor,command) RETURNING * INTO job;
 IF job_kind='evaluate' THEN
  SELECT document INTO manifest FROM package_historical_research.exports WHERE cohort_id=cohort AND purpose='final_manifest';
  SELECT jsonb_agg(jsonb_build_object('id',r->'id','status',r->'status','prediction',CASE WHEN r->>'status'='succeeded' THEN trained.document#>'{model,constant}' ELSE 'null'::jsonb END) ORDER BY r->>'id') INTO predicted FROM jsonb_array_elements(manifest)r;
  SELECT jsonb_object_agg(name,row_values) INTO base FROM (
   SELECT name,(SELECT jsonb_object_agg(r->>'id',trained.document->'baselines'->name) FROM jsonb_array_elements(manifest)r WHERE r->>'status'='succeeded') row_values FROM unnest(ARRAY['mean','median']) name
  ) constants;
  predicted:=jsonb_build_object('schema','package-history-frozen-final-predictions/1','model_digest',trained.document->'model_digest','rows',predicted,'intervals',trained.document->'intervals','baseline_predictions',base);
  INSERT INTO package_historical_research.predictions VALUES(job.id,trained.id,trained.document->>'model_digest',predicted,design.package_technical_digest(predicted),clock_timestamp());
 END IF;
 RETURN jsonb_build_object('job_id',job.id,'cohort_id',job.cohort_id,'kind',job.kind,'state',job.state,'generation',job.generation,'research_only',true,'formal_eligibility','unavailable');
END $$;

CREATE FUNCTION package_historical_research.claim_job(target uuid,expected_generation bigint,owner uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE job package_historical_research.jobs;
BEGIN
 SELECT * INTO job FROM package_historical_research.jobs WHERE id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'package_history_job_missing' USING ERRCODE='P0002'; END IF;
 PERFORM package_historical_research.assert_role(job.kind);
 IF NOT package_historical_research.current_cohort(job.cohort_id) THEN RAISE EXCEPTION 'package_history_cohort_stale' USING ERRCODE='55000'; END IF;
 SELECT * INTO job FROM package_historical_research.jobs WHERE id=target FOR UPDATE;
 IF owner IS NULL OR expected_generation IS DISTINCT FROM job.generation THEN RAISE EXCEPTION 'package_history_lease_invalid' USING ERRCODE='55000'; END IF;
 IF job.state='succeeded' THEN RETURN jsonb_build_object('job_id',job.id,'state','succeeded','result_digest',(SELECT digest FROM package_historical_research.results WHERE job_id=target)); END IF;
 IF job.state NOT IN('queued','running') OR job.state='running' AND job.lease_until>clock_timestamp() THEN RAISE EXCEPTION 'package_history_job_not_claimable' USING ERRCODE='55000'; END IF;
 UPDATE package_historical_research.jobs SET state='running',owner_token=owner,lease_until=clock_timestamp()+interval '120 seconds',fence=jobs.fence+1 WHERE id=target RETURNING * INTO job;
 RETURN jsonb_build_object('job_id',job.id,'generation',job.generation,'fence',job.fence,'owner',owner,'state','running');
END $$;

CREATE FUNCTION package_historical_research.assert_lease(target uuid,generation bigint,fence bigint,owner uuid) RETURNS package_historical_research.jobs
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE job package_historical_research.jobs;
BEGIN
 SELECT * INTO job FROM package_historical_research.jobs WHERE id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'package_history_job_missing' USING ERRCODE='P0002'; END IF;
 PERFORM package_historical_research.assert_role(job.kind);
 IF NOT package_historical_research.current_cohort(job.cohort_id) THEN RAISE EXCEPTION 'package_history_cohort_stale' USING ERRCODE='55000'; END IF;
 SELECT * INTO job FROM package_historical_research.jobs WHERE id=target FOR UPDATE;
 IF job.state<>'running' OR job.generation IS DISTINCT FROM generation OR job.fence IS DISTINCT FROM fence OR job.owner_token IS DISTINCT FROM owner OR owner IS NULL OR job.lease_until<=clock_timestamp() THEN RAISE EXCEPTION 'package_history_lease_invalid' USING ERRCODE='55000'; END IF;
 RETURN job;
END $$;

CREATE FUNCTION package_historical_research.read_training(target uuid,generation bigint,fence bigint,owner uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE job package_historical_research.jobs;
BEGIN
 PERFORM package_historical_research.assert_role('train'); job:=package_historical_research.assert_lease(target,generation,fence,owner);
 IF job.kind<>'train' THEN RAISE EXCEPTION 'package_history_purpose_denied' USING ERRCODE='42501'; END IF;
 RETURN (SELECT document FROM package_historical_research.exports WHERE cohort_id=job.cohort_id AND purpose='training');
END $$;

CREATE FUNCTION package_historical_research.open_final(target uuid,generation bigint,fence bigint,owner uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE job package_historical_research.jobs; cohort package_historical_research.cohorts; prior uuid; exposure_identity uuid:=gen_random_uuid(); ids uuid[]; prediction package_historical_research.predictions;
BEGIN
 PERFORM package_historical_research.assert_role('evaluate'); job:=package_historical_research.assert_lease(target,generation,fence,owner);
 SELECT * INTO prediction FROM package_historical_research.predictions WHERE job_id=target;
 IF job.kind<>'evaluate' OR prediction.job_id IS NULL THEN RAISE EXCEPTION 'package_history_predictions_not_frozen' USING ERRCODE='55000'; END IF;
 SELECT * INTO cohort FROM package_historical_research.cohorts WHERE id=job.cohort_id;
 SELECT id INTO prior FROM package_historical_research.exposures WHERE job_id=target;
 IF FOUND THEN RETURN prior; END IF;
 SELECT array_agg(DISTINCT related ORDER BY related) INTO ids FROM package_historical_research.members m CROSS JOIN LATERAL unnest(m.closure_ids)related WHERE m.cohort_id=job.cohort_id AND m.submitted_at>=cohort.submission_split_at;
 IF ids IS NULL OR package_historical_research.already_exposed(ids,job.cohort_id) THEN RAISE EXCEPTION 'package_history_final_already_exposed' USING ERRCODE='55000'; END IF;
 INSERT INTO package_historical_research.exposures VALUES(exposure_identity,target,cohort.id,cohort.digest,cohort.membership_digest,prediction.digest,ids,pg_current_xact_id(),clock_timestamp());
 INSERT INTO package_historical_research.exposure_members SELECT exposure_identity,k.kind,k.identity FROM package_historical_research.exposure_keys(ids)k;
 INSERT INTO design.audit_entries(id,actor_id,event_type,payload) VALUES(gen_random_uuid(),NULL,'package-history.final-exposed',jsonb_build_object('exposure_id',exposure_identity,'cohort_id',cohort.id,'cohort_digest',cohort.digest,'membership_digest',cohort.membership_digest,'predictions_digest',prediction.digest,'principal',session_user));
 RETURN exposure_identity;
END $$;

CREATE FUNCTION package_historical_research.read_final(target uuid,generation bigint,fence bigint,owner uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE job package_historical_research.jobs;
BEGIN
 PERFORM package_historical_research.assert_role('evaluate'); job:=package_historical_research.assert_lease(target,generation,fence,owner);
 IF job.kind<>'evaluate' OR NOT EXISTS(SELECT FROM package_historical_research.exposures x WHERE x.job_id=target AND x.created_xact<>pg_current_xact_id()) THEN RAISE EXCEPTION 'package_history_committed_exposure_required' USING ERRCODE='55000'; END IF;
 RETURN (SELECT jsonb_build_object('schema','package-history-final-evaluation-export/1','origin',c.origin,'cohort_id',c.id,'protocol',p.document,'timing',c.document->'timing','labels',l.document,'labels_digest',l.digest,'predictions',v.document,'predictions_digest',v.digest,'model_digest',v.model_digest,'membership_digest',c.membership_digest,
  'denominator',jsonb_build_object('selected_submissions',(SELECT count(*) FROM package_historical_research.members WHERE cohort_id=c.id),'excluded_submissions',(SELECT count(*) FROM package_historical_research.members WHERE cohort_id=c.id AND purpose='excluded'),'final_side_candidates',jsonb_array_length(l.document)))
  FROM package_historical_research.cohorts c JOIN package_historical_research.protocols p ON p.id=c.protocol_id JOIN package_historical_research.exports l ON l.cohort_id=c.id AND l.purpose='final_labels' JOIN package_historical_research.predictions v ON v.job_id=target WHERE c.id=job.cohort_id);
END $$;

CREATE FUNCTION package_historical_research.renew_job(target uuid,generation bigint,fence bigint,owner uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
BEGIN
 PERFORM package_historical_research.assert_lease(target,generation,fence,owner);
 UPDATE package_historical_research.jobs SET lease_until=clock_timestamp()+interval '120 seconds' WHERE id=target;
END $$;

CREATE FUNCTION package_historical_research.finish_job(target uuid,generation bigint,fence bigint,owner uuid,payload jsonb,payload_digest design.sha256) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE job package_historical_research.jobs; c package_historical_research.cohorts; pr package_historical_research.protocols;
BEGIN
 job:=package_historical_research.assert_lease(target,generation,fence,owner);
 SELECT * INTO c FROM package_historical_research.cohorts WHERE id=job.cohort_id;
 SELECT * INTO pr FROM package_historical_research.protocols WHERE id=c.protocol_id;
 IF payload_digest::text IS DISTINCT FROM design.package_technical_digest(payload) OR payload->>'cohort_id' IS DISTINCT FROM c.id::text OR payload->>'origin' IS DISTINCT FROM c.origin OR payload->>'protocol_digest' IS DISTINCT FROM pr.digest::text OR payload->>'membership_digest' IS DISTINCT FROM c.membership_digest::text
 OR payload->'research_only' IS DISTINCT FROM 'true'::jsonb OR payload->>'formal_eligibility' IS DISTINCT FROM 'unavailable' OR payload->'provider_requests' IS DISTINCT FROM '0'::jsonb OR payload->'paid_calls' IS DISTINCT FROM '0'::jsonb
 THEN RAISE EXCEPTION 'package_history_result_binding_invalid' USING ERRCODE='23514'; END IF;
 IF job.kind='train' THEN
  IF payload->>'schema' IS DISTINCT FROM 'package-history-training-result/1' OR payload->>'training_export_digest' IS DISTINCT FROM (SELECT digest::text FROM package_historical_research.exports WHERE cohort_id=c.id AND purpose='training')
  OR payload->>'model_digest' IS DISTINCT FROM design.package_technical_digest(payload->'model') OR payload#>>'{model,schema}' IS DISTINCT FROM 'package-history-constant-model/1'
  OR payload#>>'{model,method_digest}' IS DISTINCT FROM pr.document#>>'{method,digest}' OR (payload#>>'{model,family}' IN('mean','median')) IS NOT TRUE
  OR jsonb_typeof(payload#>'{model,constant}') IS DISTINCT FROM 'string'
  OR (payload#>>'{model,constant}')::numeric NOT BETWEEN 0 AND 100 OR (payload#>>'{model,constant}')::numeric IN('NaN','Infinity','-Infinity')
  OR payload#>>'{model,training_export_digest}' IS DISTINCT FROM payload->>'training_export_digest'
  THEN RAISE EXCEPTION 'package_history_training_result_invalid' USING ERRCODE='23514'; END IF;
 ELSE
  IF payload->>'schema' IS DISTINCT FROM 'package-history-independent-evaluation/1' OR payload->>'acceptance_decision' IS DISTINCT FROM 'unavailable'
  OR payload->>'predictions_digest' IS DISTINCT FROM (SELECT digest::text FROM package_historical_research.predictions WHERE job_id=target)
  OR payload->>'model_digest' IS DISTINCT FROM (SELECT model_digest::text FROM package_historical_research.predictions WHERE job_id=target)
  OR payload->>'labels_digest' IS DISTINCT FROM (SELECT digest::text FROM package_historical_research.exports WHERE cohort_id=c.id AND purpose='final_labels')
  OR NOT EXISTS(SELECT FROM package_historical_research.exposures WHERE job_id=target AND created_xact<>pg_current_xact_id())
  THEN RAISE EXCEPTION 'package_history_evaluation_result_invalid' USING ERRCODE='23514'; END IF;
 END IF;
 INSERT INTO package_historical_research.results VALUES(target,payload,payload_digest,clock_timestamp());
 UPDATE package_historical_research.jobs SET state='succeeded',owner_token=NULL,lease_until=NULL WHERE id=target;
 RETURN true;
END $$;

CREATE FUNCTION package_historical_research.control_job(target uuid,expected_generation bigint,action text,actor uuid,command uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,design,pg_temp AS $$
DECLARE job package_historical_research.jobs;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT * INTO job FROM package_historical_research.jobs WHERE id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'package_history_job_missing' USING ERRCODE='P0002'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 IF action='resume' AND NOT package_historical_research.current_cohort(job.cohort_id) THEN RAISE EXCEPTION 'package_history_cohort_stale' USING ERRCODE='55000'; END IF;
 SELECT * INTO job FROM package_historical_research.jobs WHERE id=target FOR UPDATE;
 IF job.generation IS DISTINCT FROM expected_generation OR action NOT IN('pause','resume','cancel') OR job.state IN('succeeded','cancelled','failed') OR action='resume' AND job.state<>'paused'
 OR NOT EXISTS(SELECT FROM design.commands c WHERE c.id=command AND c.actor_id=actor AND c.target_id=target AND c.command_kind='package-history-job-control') THEN RAISE EXCEPTION 'package_history_control_conflict' USING ERRCODE='55000'; END IF;
 UPDATE package_historical_research.jobs SET state=CASE action WHEN 'pause' THEN 'paused' WHEN 'resume' THEN 'queued' ELSE 'cancelled' END,generation=jobs.generation+1,owner_token=NULL,lease_until=NULL WHERE id=target RETURNING * INTO job;
 INSERT INTO design.audit_entries(id,actor_id,command_id,event_type,payload) VALUES(gen_random_uuid(),actor,command,'package-history.job-controlled',jsonb_build_object('job_id',target,'action',action,'generation',job.generation));
 RETURN jsonb_build_object('job_id',job.id,'cohort_id',job.cohort_id,'kind',job.kind,'state',job.state,'generation',job.generation,'research_only',true,'formal_eligibility','unavailable');
END $$;

CREATE FUNCTION package_historical_research.cohort_view(target uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE c package_historical_research.cohorts;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT * INTO c FROM package_historical_research.cohorts WHERE id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'package_history_cohort_missing' USING ERRCODE='P0002'; END IF;
 RETURN jsonb_build_object('cohort',c.document||jsonb_build_object('digest',c.digest),'current',package_historical_research.current_cohort(target));
END $$;

CREATE FUNCTION package_historical_research.job_view(target uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE job package_historical_research.jobs; current boolean; result jsonb; fingerprint text;
BEGIN
 PERFORM package_historical_research.assert_role('api');
 SELECT * INTO job FROM package_historical_research.jobs WHERE id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'package_history_job_missing' USING ERRCODE='P0002'; END IF;
 current:=package_historical_research.current_cohort(job.cohort_id);
 SELECT document,digest INTO result,fingerprint FROM package_historical_research.results WHERE job_id=target;
 RETURN jsonb_build_object('job_id',job.id,'cohort_id',job.cohort_id,'kind',job.kind,'state',job.state,'generation',job.generation,'current',current,'result',result,'result_digest',fingerprint,'research_only',true,'formal_eligibility','unavailable');
END $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA package_historical_research FROM PUBLIC;
GRANT EXECUTE ON FUNCTION package_historical_research.register_protocol(jsonb,uuid,uuid),package_historical_research.freeze_cohort(uuid,timestamptz,timestamptz,jsonb,uuid,uuid),package_historical_research.start_job(uuid,text,uuid,uuid),package_historical_research.control_job(uuid,bigint,text,uuid,uuid),package_historical_research.cohort_view(uuid),package_historical_research.job_view(uuid) TO tender_api;
GRANT EXECUTE ON FUNCTION package_historical_research.claim_job(uuid,bigint,uuid),package_historical_research.renew_job(uuid,bigint,bigint,uuid),package_historical_research.finish_job(uuid,bigint,bigint,uuid,jsonb,design.sha256) TO tender_package_history_train,tender_package_history_evaluate;
GRANT EXECUTE ON FUNCTION package_historical_research.read_training(uuid,bigint,bigint,uuid) TO tender_package_history_train;
GRANT EXECUTE ON FUNCTION package_historical_research.open_final(uuid,bigint,bigint,uuid),package_historical_research.read_final(uuid,bigint,bigint,uuid) TO tender_package_history_evaluate;
COMMIT;
