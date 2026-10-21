-- Explicit whole-package retrospectives; no edits to scores, risks, samples or models.
-- Install after bid-package-submissions, review decisions and retrieval.
BEGIN;
SET search_path=design,public;

CREATE TABLE package_retrospectives(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL REFERENCES bids(id),
 submission_id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 manifest jsonb NOT NULL,
 digest sha256 NOT NULL,
 created_at timestamptz NOT NULL,
 FOREIGN KEY(bid_id,submission_id) REFERENCES submission_records(bid_id,id),
 FOREIGN KEY(submission_id) REFERENCES bid_package_submission_bindings(submission_id),
 UNIQUE(bid_id,id),
 CHECK(octet_length(manifest::text)<=8388608),
 CHECK(digest=package_submission_digest(manifest)),
 CHECK((manifest->>'version'='package-retrospective/1' AND manifest->>'state'='pending_review'
  AND manifest->>'id'=id::text AND manifest->>'bid_id'=bid_id::text
  AND manifest->>'actor_id'=actor_id::text AND manifest->>'command_id'=command_id::text
  AND manifest#>>'{preview,manifest,selection,submission_id}'=submission_id::text) IS TRUE)
);
CREATE INDEX package_retrospective_history ON package_retrospectives(bid_id,created_at DESC,id DESC);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_retrospectives
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE TABLE package_retrospective_knowledge_links(
 retrospective_id uuid PRIMARY KEY REFERENCES package_retrospectives(id),
 bid_id uuid NOT NULL,
 retrospective_digest sha256 NOT NULL,
 knowledge_id uuid NOT NULL UNIQUE REFERENCES retrieval.knowledge_items(id),
 knowledge_version_id uuid NOT NULL UNIQUE,
 source_id uuid NOT NULL UNIQUE REFERENCES retrieval.source_nodes(id),
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 reason text NOT NULL CHECK(length(reason) BETWEEN 1 AND 4000 AND reason~'\S'),
 created_at timestamptz NOT NULL,
 FOREIGN KEY(bid_id,retrospective_id) REFERENCES package_retrospectives(bid_id,id),
 FOREIGN KEY(knowledge_id,knowledge_version_id) REFERENCES retrieval.knowledge_versions(item_id,id)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON package_retrospective_knowledge_links
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE FUNCTION package_retrospective_origin(link design.package_retrospective_knowledge_links)
 RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog,design AS $$
 SELECT jsonb_build_object('retrospective_id',link.retrospective_id,'retrospective_digest',link.retrospective_digest,
  'preview_digest',r.manifest#>'{preview,digest}','source_id',link.source_id)
 FROM design.package_retrospectives r WHERE r.id=link.retrospective_id
$$;

CREATE FUNCTION package_retrospective_human(run uuid,requirement uuid) RETURNS jsonb
 LANGUAGE sql STABLE SET search_path=pg_catalog,design AS $$
 SELECT coalesce((SELECT jsonb_build_object('id',d.id,'digest',d.digest,
  'sequence_no',d.sequence_no,'actor_id',d.actor_id,'created_at',d.manifest->'created_at',
  'state',d.manifest->'state','reason',d.manifest->'reason')
 FROM design.bid_package_review_decision_heads h JOIN design.bid_package_review_decisions d ON d.id=h.decision_id
 WHERE h.run_id=run AND h.requirement_id=requirement),'null'::jsonb)
$$;

CREATE FUNCTION package_retrospective_required_sources(bid uuid,selected jsonb) RETURNS jsonb
 LANGUAGE sql STABLE SET search_path=pg_catalog,design,retrieval,public AS $$
 WITH binding AS (
  SELECT * FROM design.bid_package_submission_bindings WHERE bid_id=bid AND submission_id=(selected->>'submission_id')::uuid
 ), selected_runs AS (
  SELECT input_manifest FROM design.bid_package_review_runs WHERE bid_id=bid AND id IN((selected->>'baseline_run_id')::uuid,(selected->>'submitted_run_id')::uuid)
 ), revisions AS (
  SELECT revision_id AS id FROM binding UNION SELECT authority_revision_id FROM binding
  UNION SELECT (input_manifest#>>'{scope,revision_id}')::uuid FROM selected_runs
  UNION SELECT i.authority_revision_id FROM design.bid_package_requirement_inventories i JOIN selected_runs r ON i.id=(r.input_manifest#>>'{scope,inventory_id}')::uuid AND i.bid_id=bid
 ), members AS (
  SELECT document_version_id,parse_run_id FROM design.bid_package_members WHERE revision_id IN(SELECT id FROM revisions)
 ), chosen_outcome AS (
  SELECT * FROM design.outcomes WHERE bid_id=bid AND id=(selected->>'outcome_id')::uuid
 ), chosen_business AS (
  SELECT * FROM design.audit_entries WHERE bid_id=bid AND id=(selected->>'business_result_id')::uuid AND event_type='metrics.business_result_recorded'
 ), business_verification AS (
  SELECT payload FROM design.audit_entries WHERE bid_id=bid AND event_type='metrics.business_result_verified' AND payload->>'result_id'=selected->>'business_result_id'
  ORDER BY (payload->>'metrics_epoch')::bigint DESC,id DESC LIMIT 1
 ), refs AS (
  SELECT ref FROM design.decision_heads h JOIN design.decisions d ON d.id=h.decision_id
   CROSS JOIN LATERAL jsonb_array_elements(coalesce(d.reason::jsonb#>'{request,evidence_refs}','[]'::jsonb))ref
   WHERE h.bid_id=bid AND h.object_kind='outcome' AND h.object_id=(selected->>'outcome_id')::uuid
  UNION ALL SELECT ref FROM chosen_business b CROSS JOIN LATERAL jsonb_array_elements(coalesce(b.payload->'evidence_refs','[]'::jsonb))ref
  UNION ALL SELECT ref FROM business_verification b CROSS JOIN LATERAL jsonb_array_elements(coalesce(b.payload#>'{details,evidence_refs}','[]'::jsonb))ref
 ), originals AS (
  SELECT document_version_id AS id FROM members
  UNION SELECT (manifest#>>'{evidence,document_version_id}')::uuid FROM binding
  UNION SELECT source_version_id FROM chosen_outcome
  UNION SELECT (payload->>'source_version_id')::uuid FROM chosen_business WHERE payload->>'source_version_id' IS NOT NULL
 ), parses AS (
  SELECT parse_run_id AS id FROM members WHERE parse_run_id IS NOT NULL
  UNION SELECT e.parse_id FROM design.evidence_blocks e JOIN refs r ON e.id=(r.ref->>'evidence_id')::uuid AND e.bid_id=bid
 ), roots AS (
  SELECT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-original:'||id::text)::text AS id FROM originals
  UNION SELECT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-parse:'||id::text)::text FROM parses
 ) SELECT jsonb_build_object('documents',(SELECT coalesce(jsonb_agg(id::text ORDER BY id::text),'[]'::jsonb) FROM originals),
  'sources',(SELECT coalesce(jsonb_agg(id ORDER BY id),'[]'::jsonb) FROM roots))
$$;

CREATE FUNCTION package_retrospective_comparison(bid uuid,left_id uuid,right_id uuid) RETURNS jsonb
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog,design AS $$
DECLARE names text[]:=ARRAY['left','right']; ids uuid[]:=ARRAY[left_id,right_id]; i integer;
 run design.bid_package_review_runs; result design.bid_package_review_results;
 inputs jsonb:='{}'; results jsonb:='{}'; summaries jsonb:='{}'; human jsonb;
 rows jsonb:='[]'; counts jsonb; changes jsonb; item record; a jsonb; b jsonb;
 left_summary jsonb; right_summary jsonb; definition text; modified boolean; transition jsonb;
 row_fields text[]:=ARRAY['requirement_digest','rule_digest','rule_kind','requirement_statement','applicability','target_part_ids','verdict','statement','limitations'];
BEGIN
 IF left_id IS NULL OR right_id IS NULL OR left_id=right_id THEN RETURN NULL; END IF;
 FOR i IN 1..2 LOOP
  SELECT * INTO run FROM design.bid_package_review_runs WHERE id=ids[i] AND bid_id=bid;
  SELECT * INTO result FROM design.bid_package_review_results WHERE run_id=run.id AND bid_id=bid;
  IF result.run_id IS NULL OR NOT EXISTS(SELECT FROM design.operations WHERE id=run.operation_id AND state='succeeded') THEN RETURN NULL; END IF;
  human:=jsonb_build_object('scope',run.input_manifest->'scope','frozen_input_id',run.input_manifest#>'{frozen_input,id}',
   'execution_input_id',run.input_manifest#>'{execution_input,id}','run_id',run.id,'result_digest',result.digest,
   'items',(SELECT jsonb_agg(jsonb_build_object('requirement_id',row->'requirement_id','row_digest',design.package_submission_digest(row),
    'current',design.package_retrospective_human(run.id,(row->>'requirement_id')::uuid)) ORDER BY row->>'requirement_id') FROM jsonb_array_elements(result.manifest->'matrix')row));
  summaries:=summaries||jsonb_build_object(names[i],jsonb_build_object(
   'id',run.id,'actor_id',run.actor_id,'created_at',to_char(run.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
   'scope',run.input_manifest->'scope','frozen_input_id',run.input_manifest#>'{frozen_input,id}',
   'frozen_input_digest',run.input_manifest#>'{frozen_input,digest}','execution_input_id',run.input_manifest#>'{execution_input,id}',
   'execution_input_digest',run.input_manifest#>'{execution_input,digest}','execution_digest',run.input_manifest#>'{execution_input,identity,execution_digest}',
   'input_digest',run.input_digest,'method_digest',run.input_manifest#>'{executor_method,digest}',
   'dependency_plan_id',run.input_manifest#>'{dependency_plan,id}','dependency_plan_digest',run.input_manifest#>'{dependency_plan,digest}',
   'result_digest',result.digest,'requirement_count',result.manifest->'requirement_count','matrix_coverage',result.manifest->'matrix_coverage',
   'overall_coverage',result.manifest->'overall_coverage','human_heads_digest',design.package_submission_digest(human)));
  inputs:=inputs||jsonb_build_object(names[i],run.input_manifest);
  results:=results||jsonb_build_object(names[i],result.manifest);
 END LOOP;
 FOR item IN SELECT coalesce(l.value->>'requirement_id',r.value->>'requirement_id') AS id,l.value AS left_row,r.value AS right_row
  FROM jsonb_array_elements(results#>'{left,matrix}')l FULL JOIN jsonb_array_elements(results#>'{right,matrix}')r ON l.value->>'requirement_id'=r.value->>'requirement_id'
  ORDER BY coalesce(l.value->>'requirement_id',r.value->>'requirement_id') LOOP
  a:=item.left_row; b:=item.right_row;
  definition:=CASE WHEN a IS NULL THEN 'added' WHEN b IS NULL THEN 'removed'
   WHEN a->'requirement_digest'=b->'requirement_digest' AND a->'rule_digest'=b->'rule_digest' THEN 'unchanged' ELSE 'changed' END;
  modified:=CASE WHEN a IS NULL OR b IS NULL THEN NULL ELSE design.package_submission_digest(a)<>design.package_submission_digest(b) END;
  transition:=CASE WHEN a IS NULL OR b IS NULL THEN 'null'::jsonb ELSE jsonb_build_object('from',a->'verdict','to',b->'verdict','changed',a->'verdict'<>b->'verdict') END;
  left_summary:=CASE WHEN a IS NULL THEN 'null'::jsonb ELSE (SELECT jsonb_object_agg(key,value) FROM jsonb_each(a) WHERE key=ANY(row_fields))||jsonb_build_object('row_digest',design.package_submission_digest(a)) END;
  right_summary:=CASE WHEN b IS NULL THEN 'null'::jsonb ELSE (SELECT jsonb_object_agg(key,value) FROM jsonb_each(b) WHERE key=ANY(row_fields))||jsonb_build_object('row_digest',design.package_submission_digest(b)) END;
  rows:=rows||jsonb_build_array(jsonb_build_object('requirement_id',item.id,'definition_change',definition,'machine_row_changed',modified,
   'verdict_transition',transition,'left',left_summary,'right',right_summary,
   'left_human',design.package_retrospective_human(left_id,item.id::uuid),'right_human',design.package_retrospective_human(right_id,item.id::uuid)));
 END LOOP;
 SELECT jsonb_build_object('added',count(*) FILTER(WHERE v->>'definition_change'='added'),'removed',count(*) FILTER(WHERE v->>'definition_change'='removed'),
  'changed',count(*) FILTER(WHERE v->>'definition_change'='changed'),'unchanged',count(*) FILTER(WHERE v->>'definition_change'='unchanged'),
  'machine_row_changed',count(*) FILTER(WHERE v->'machine_row_changed'='true'::jsonb),'verdict_changed',count(*) FILTER(WHERE v#>'{verdict_transition,changed}'='true'::jsonb))
 INTO counts FROM jsonb_array_elements(rows)v;
 a:=inputs->'left'; b:=inputs->'right';
 changes:=jsonb_build_object('run_input',summaries#>'{left,input_digest}'<>summaries#>'{right,input_digest}',
  'scope',a->'scope'<>b->'scope','frozen_input',a->'frozen_input'<>b->'frozen_input',
  'prepared_input',jsonb_build_array(a#>'{execution_input,id}',a#>'{execution_input,digest}')<>jsonb_build_array(b#>'{execution_input,id}',b#>'{execution_input,digest}'),
  'rerun_intent',a#>'{execution_input,identity,rerun}'<>b#>'{execution_input,identity,rerun}',
  'requirements',(SELECT jsonb_object_agg(v->>'requirement_id',jsonb_build_array(v->'requirement_digest',v->'rule_digest')) FROM jsonb_array_elements(results#>'{left,matrix}')v)
    IS DISTINCT FROM (SELECT jsonb_object_agg(v->>'requirement_id',jsonb_build_array(v->'requirement_digest',v->'rule_digest')) FROM jsonb_array_elements(results#>'{right,matrix}')v),
  'submitted_documents',results#>'{left,submitted_documents}'<>results#>'{right,submitted_documents}',
  'selected_facts',a->'selected_facts_digest'<>b->'selected_facts_digest','fact_admission',a->'fact_admission'<>b->'fact_admission',
  'dependency_plan',a->'dependency_plan'<>b->'dependency_plan','inventory_proof',a->'inventory_proof_digest'<>b->'inventory_proof_digest',
  'method',a#>'{executor_method,digest}'<>b#>'{executor_method,digest}',
  'method_fields',(SELECT coalesce(jsonb_agg(key ORDER BY key),'[]'::jsonb) FROM (
   SELECT jsonb_object_keys(a#>'{executor_method,profile}') AS key UNION SELECT jsonb_object_keys(b#>'{executor_method,profile}'))keys
   WHERE a#>ARRAY['executor_method','profile',key] IS DISTINCT FROM b#>ARRAY['executor_method','profile',key]));
 RETURN jsonb_build_object('version','package-review-comparison/1','kind','declared_scope_review_comparison','bid_id',bid,
  'match_policy','exact_requirement_id_and_definition_digests/1','left',summaries->'left','right',summaries->'right',
  'input_changes',changes,'counts',counts,'overall_coverage','partial','risk_resolution_assessed',false,'inventory_complete',false,
  'formal_scoring_eligible',false,'submission_eligible',false,'items',rows);
END $$;

CREATE FUNCTION package_retrospective_inputs_unchanged(m jsonb) RETURNS boolean
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog,design,retrieval AS $$
DECLARE p jsonb:=m#>'{preview,manifest}'; selected jsonb:=p->'selection'; source jsonb; actual record;
 outrow design.outcomes; detail jsonb; decision design.decisions; current_result uuid;
 comparison jsonb:=p#>'{comparison,manifest}'; item jsonb; side text; run uuid;
BEGIN
 IF ((SELECT submission_id::text FROM design.submission_heads WHERE bid_id=(m->>'bid_id')::uuid)=selected->>'submission_id')
   IS DISTINCT FROM (p#>>'{submission,current}')::boolean THEN RETURN false; END IF;
 IF selected->>'outcome_id' IS NOT NULL THEN
  SELECT * INTO outrow FROM design.outcomes WHERE id=(selected->>'outcome_id')::uuid AND bid_id=(m->>'bid_id')::uuid;
  SELECT d.* INTO decision FROM design.decision_heads h JOIN design.decisions d ON d.id=h.decision_id
   WHERE h.bid_id=outrow.bid_id AND h.object_kind='outcome' AND h.object_id=outrow.id;
  IF outrow.id IS NULL OR outrow.submission_id::text<>selected->>'submission_id'
   OR decision.id::text IS DISTINCT FROM p#>>'{outcome,verification_id}'
   OR coalesce(decision.decision,'pending') IS DISTINCT FROM p#>>'{outcome,verification}'
   OR ((SELECT outcome_id=outrow.id FROM design.outcome_heads WHERE bid_id=outrow.bid_id AND submission_id=outrow.submission_id))
      IS DISTINCT FROM (p#>>'{outcome,current}')::boolean
  THEN RETURN false; END IF;
 END IF;
 IF selected->>'business_result_id' IS NOT NULL THEN
  SELECT (payload->>'result_id')::uuid INTO current_result FROM design.audit_entries
   WHERE bid_id=(m->>'bid_id')::uuid AND event_type IN('metrics.business_result_recorded','metrics.business_result_verified')
   AND payload->>'submission_id'=selected->>'submission_id'
   ORDER BY (payload->>'metrics_epoch')::bigint DESC,id DESC LIMIT 1;
  IF (current_result::text=selected->>'business_result_id') IS DISTINCT FROM (p#>>'{business_result,current}')::boolean THEN RETURN false; END IF;
  SELECT id INTO current_result FROM design.audit_entries WHERE bid_id=(m->>'bid_id')::uuid
   AND event_type='metrics.business_result_verified' AND payload->>'result_id'=selected->>'business_result_id'
   ORDER BY (payload->>'metrics_epoch')::bigint DESC,id DESC LIMIT 1;
  IF current_result::text IS DISTINCT FROM p#>>'{business_result,verification_authority_id}' THEN RETURN false; END IF;
 END IF;
 IF comparison IS NOT NULL AND comparison<>'null'::jsonb THEN
  FOR item IN SELECT * FROM jsonb_array_elements(comparison->'items') LOOP
   FOREACH side IN ARRAY ARRAY['left','right'] LOOP
    run:=(comparison#>>ARRAY[side,'id'])::uuid;
    IF item->(side||'_human') IS DISTINCT FROM design.package_retrospective_human(run,(item->>'requirement_id')::uuid) THEN RETURN false; END IF;
   END LOOP;
  END LOOP;
 END IF;
 IF jsonb_array_length(p->'source_snapshot')<>(SELECT count(*) FROM retrieval.source_ancestors a WHERE p->'source_ids' ? a.source_id::text) THEN RETURN false; END IF;
 IF jsonb_array_length(p->'source_snapshot')<>(SELECT count(DISTINCT jsonb_build_array(v->'source_id',v->'ancestor_id')) FROM jsonb_array_elements(p->'source_snapshot')v) THEN RETURN false; END IF;
 FOR source IN SELECT * FROM jsonb_array_elements(p->'source_snapshot') LOOP
  SELECT n.*,d.bid_id AS document_bid_id,h.revision,h.status,h.valid_from,h.valid_until INTO actual
   FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.ancestor_id
   LEFT JOIN retrieval.source_heads h ON h.source_id=n.id LEFT JOIN design.document_versions d ON d.id=n.document_version_id
   WHERE a.source_id=(source->>'source_id')::uuid AND a.ancestor_id=(source->>'ancestor_id')::uuid;
  IF actual.id IS NULL OR actual.document_version_id::text IS DISTINCT FROM source->>'document_version_id'
   OR actual.document_bid_id::text IS DISTINCT FROM source->>'document_bid_id'
   OR actual.kind IS DISTINCT FROM source->>'kind' OR actual.policy_class IS DISTINCT FROM source->>'policy_class'
   OR actual.digest::text IS DISTINCT FROM source->>'digest'
   OR actual.known_at IS DISTINCT FROM (source->>'known_at')::timestamptz
   OR actual.revision IS DISTINCT FROM (source->>'revision')::bigint OR actual.status IS DISTINCT FROM source->>'status'
   OR actual.valid_from IS DISTINCT FROM (source->>'valid_from')::timestamptz OR actual.valid_until IS DISTINCT FROM (source->>'valid_until')::timestamptz
  THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;

CREATE FUNCTION package_retrospective_sources_available(m jsonb) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog,design,retrieval AS $$
 SELECT NOT EXISTS(
  SELECT FROM jsonb_array_elements_text(m#>'{preview,manifest,source_ids}')selected
  WHERE NOT EXISTS(SELECT FROM retrieval.source_ancestors a WHERE a.source_id=selected.value::uuid AND a.ancestor_id=a.source_id))
 AND NOT EXISTS(
  SELECT FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.ancestor_id
  LEFT JOIN retrieval.source_heads h ON h.source_id=n.id
  LEFT JOIN design.document_versions d ON d.id=n.document_version_id
  WHERE m#>'{preview,manifest,source_ids}' ? a.source_id::text
   AND (h.status IS DISTINCT FROM 'published' OR h.valid_from IS NULL OR h.valid_from>clock_timestamp()
    OR n.known_at>clock_timestamp() OR h.valid_until<=clock_timestamp()
    OR d.bid_id IS NOT NULL AND d.bid_id::text<>m->>'bid_id'))
$$;

CREATE FUNCTION package_retrospective_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design,retrieval AS $$
DECLARE m jsonb:=NEW.manifest; p jsonb:=m#>'{preview,manifest}'; selected jsonb:=p->'selection';
 binding design.bid_package_submission_bindings; submission design.submission_records; command design.commands;
 outcome design.outcomes; decision design.decisions; head_revision bigint; detail jsonb;
 business design.audit_entries; verification design.audit_entries; business_head design.audit_entries;
 item jsonb; side text; run design.bid_package_review_runs; result design.bid_package_review_results; native jsonb;
 comparison jsonb:=p#>'{comparison,manifest}'; field text; required uuid[]; expected jsonb; request jsonb; condition text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'retrospective_read_committed_required' USING ERRCODE='25001'; END IF;
 PERFORM id FROM design.bids WHERE id=NEW.bid_id FOR UPDATE;
 PERFORM pg_advisory_xact_lock(90127,1);
 SELECT * INTO binding FROM design.bid_package_submission_bindings WHERE bid_id=NEW.bid_id AND submission_id=NEW.submission_id;
 SELECT * INTO submission FROM design.submission_records WHERE bid_id=NEW.bid_id AND id=NEW.submission_id;
 SELECT * INTO command FROM design.commands WHERE id=NEW.command_id;
 IF NOT design.package_json_keys(m,ARRAY['version','id','bid_id','actor_id','command_id','created_at','state','title','notes','preview','official_deduction_reasons_inferred','risk_resolution_assessed','formal_sample_eligible','model_qualification_granted','knowledge_published'])
 OR NOT design.package_json_keys(m->'notes',ARRAY['observations','hypotheses','next_actions','additional_missing_materials'])
 OR NOT design.package_json_keys(m->'preview',ARRAY['manifest','digest'])
 OR NOT design.package_json_keys(p,ARRAY['version','bid_id','selection','submission','outcome','business_result','comparison','source_ids','source_snapshot','documents','gaps','timing','official_deduction_reasons_inferred','risk_resolution_assessed','formal_sample_eligible','model_qualification_granted','knowledge_published'])
 OR NOT design.package_json_keys(p->'submission',ARRAY['id','package_id','revision_id','package_digest','binding_digest','identity','kind','submitted_at','recorded_at','current','registration_risk_digest','registration_assessed_at','risk_resolution_assessed'])
 OR binding.submission_id IS NULL OR submission.subject_kind<>'bid_package'
 OR p->>'version' IS DISTINCT FROM 'package-retrospective-preview/1' OR p->>'bid_id' IS DISTINCT FROM NEW.bid_id::text
 OR p->>'timing' IS DISTINCT FROM 'post_outcome_retrospective'
 OR m#>>'{preview,digest}' IS DISTINCT FROM design.package_submission_digest(p)
 OR p#>>'{submission,binding_digest}' IS DISTINCT FROM binding.digest::text
 OR p#>>'{submission,package_id}' IS DISTINCT FROM binding.package_id::text
 OR p#>>'{submission,revision_id}' IS DISTINCT FROM binding.revision_id::text
 OR p#>>'{submission,package_digest}' IS DISTINCT FROM binding.manifest#>>'{subject,package_digest}'
 OR p#>'{submission,identity}' IS DISTINCT FROM binding.manifest->'package_identity'
 OR p#>>'{submission,id}' IS DISTINCT FROM NEW.submission_id::text
 OR (p#>>'{submission,submitted_at}')::timestamptz IS DISTINCT FROM submission.submitted_at
 OR (p#>>'{submission,recorded_at}')::timestamptz IS DISTINCT FROM submission.created_at
 OR p#>>'{submission,kind}' IS DISTINCT FROM submission.kind
 OR p#>>'{submission,registration_risk_digest}' IS DISTINCT FROM design.package_submission_digest(binding.manifest#>'{gate,manifest,gates,known_blocking_risks}')
 OR p#>'{submission,registration_assessed_at}' IS DISTINCT FROM binding.manifest->'assessed_at'
 OR p#>'{submission,risk_resolution_assessed}' IS DISTINCT FROM 'false'::jsonb
 OR (m->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at OR NEW.created_at<submission.created_at
 OR length(m->>'title') NOT BETWEEN 1 AND 200 OR (m->>'title'~'\S') IS NOT TRUE
 THEN RAISE EXCEPTION 'retrospective_submission_binding' USING ERRCODE='23514'; END IF;
 FOREACH field IN ARRAY ARRAY['official_deduction_reasons_inferred','risk_resolution_assessed','formal_sample_eligible','model_qualification_granted','knowledge_published'] LOOP
  IF m->field IS DISTINCT FROM 'false'::jsonb OR p->field IS DISTINCT FROM 'false'::jsonb THEN RAISE EXCEPTION 'retrospective_cannot_grant_qualification' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NOT design.package_json_keys(selected,ARRAY['submission_id','outcome_id','outcome_missing_reason','business_result_id','business_result_missing_reason','baseline_run_id','submitted_run_id','reviews_missing_reason'])
 OR (selected->>'outcome_id' IS NULL) IS DISTINCT FROM (selected->>'outcome_missing_reason' IS NOT NULL)
 OR (selected->>'business_result_id' IS NULL) IS DISTINCT FROM (selected->>'business_result_missing_reason' IS NOT NULL)
 OR (selected->>'baseline_run_id' IS NULL) IS DISTINCT FROM (selected->>'submitted_run_id' IS NULL)
 OR (selected->>'baseline_run_id' IS NULL) IS DISTINCT FROM (selected->>'reviews_missing_reason' IS NOT NULL)
 OR (selected->>'outcome_id' IS NULL) IS DISTINCT FROM (p->'outcome'='null'::jsonb)
 OR (selected->>'business_result_id' IS NULL) IS DISTINCT FROM (p->'business_result'='null'::jsonb)
 OR (selected->>'baseline_run_id' IS NULL) IS DISTINCT FROM (p->'comparison'='null'::jsonb)
 OR selected->>'baseline_run_id'=selected->>'submitted_run_id'
 THEN RAISE EXCEPTION 'retrospective_explicit_selection_required' USING ERRCODE='23514'; END IF;
 IF selected->>'outcome_id' IS NOT NULL THEN
  IF NOT design.package_json_keys(p->'outcome',ARRAY['id','submission_id','score_kind','value','maximum','source_version_id','known_at','supersedes_id','verification','verification_revision','verification_id','verification_details_digest','aggregation','published_at','evidence_refs','current','association_reasons']) THEN RAISE EXCEPTION 'retrospective_outcome_keys' USING ERRCODE='23514'; END IF;
  SELECT * INTO outcome FROM design.outcomes WHERE bid_id=NEW.bid_id AND id=(selected->>'outcome_id')::uuid;
  SELECT d.* INTO decision FROM design.decision_heads h JOIN design.decisions d ON d.id=h.decision_id WHERE h.bid_id=NEW.bid_id AND h.object_kind='outcome' AND h.object_id=outcome.id;
  SELECT h.revision INTO head_revision FROM design.decision_heads h WHERE h.bid_id=NEW.bid_id AND h.object_kind='outcome' AND h.object_id=outcome.id;
  detail:=CASE WHEN decision.id IS NULL THEN NULL ELSE decision.reason::jsonb END;
  IF outcome.id IS NULL OR outcome.submission_id<>NEW.submission_id
   OR p#>>'{outcome,id}' IS DISTINCT FROM outcome.id::text
   OR p#>>'{outcome,submission_id}' IS DISTINCT FROM NEW.submission_id::text
   OR p#>>'{outcome,score_kind}' IS DISTINCT FROM outcome.score_kind
   OR (p#>>'{outcome,value}')::numeric IS DISTINCT FROM outcome.value
   OR (p#>>'{outcome,maximum}')::numeric IS DISTINCT FROM outcome.maximum
   OR p#>>'{outcome,source_version_id}' IS DISTINCT FROM outcome.source_version_id::text
   OR (p#>>'{outcome,known_at}')::timestamptz IS DISTINCT FROM outcome.known_at
   OR p#>>'{outcome,supersedes_id}' IS DISTINCT FROM outcome.supersedes_id::text
   OR (p#>>'{outcome,verification_revision}')::bigint IS DISTINCT FROM coalesce(head_revision,0)
   OR p#>>'{outcome,verification_details_digest}' IS DISTINCT FROM (CASE WHEN detail IS NULL THEN NULL ELSE design.package_submission_digest(detail) END)
   OR p#>'{outcome,evidence_refs}' IS DISTINCT FROM coalesce(detail#>'{request,evidence_refs}','[]'::jsonb)
   OR p#>>'{outcome,aggregation}' IS DISTINCT FROM detail#>>'{request,aggregation}'
   OR (p#>>'{outcome,published_at}')::timestamptz IS DISTINCT FROM (detail#>>'{request,published_at}')::timestamptz
  THEN RAISE EXCEPTION 'retrospective_outcome_binding' USING ERRCODE='23514'; END IF;
 END IF;
 IF selected->>'business_result_id' IS NOT NULL THEN
  SELECT * INTO business FROM design.audit_entries WHERE bid_id=NEW.bid_id AND id=(selected->>'business_result_id')::uuid AND event_type='metrics.business_result_recorded';
  SELECT * INTO verification FROM design.audit_entries WHERE bid_id=NEW.bid_id AND event_type='metrics.business_result_verified' AND payload->>'result_id'=selected->>'business_result_id' ORDER BY (payload->>'metrics_epoch')::bigint DESC,id DESC LIMIT 1;
  SELECT * INTO business_head FROM design.audit_entries WHERE bid_id=NEW.bid_id AND event_type IN('metrics.business_result_recorded','metrics.business_result_verified') AND payload->>'submission_id'=NEW.submission_id::text ORDER BY (payload->>'metrics_epoch')::bigint DESC,id DESC LIMIT 1;
  IF NOT design.package_json_keys(p->'business_result',ARRAY['id','bid_id','submission_id','stage','source_type','source_version_id','evidence_refs','announced_at','known_at','reason','supersedes_id','correction_reason','created_by','created_at','verification','verification_authority_id','verification_details','head_revision','head_authority_id','current'])
   OR business.id IS NULL OR business.payload->>'submission_id' IS DISTINCT FROM NEW.submission_id::text
   OR p#>>'{business_result,id}' IS DISTINCT FROM business.id::text OR p#>>'{business_result,bid_id}' IS DISTINCT FROM NEW.bid_id::text
   OR p#>>'{business_result,created_by}' IS DISTINCT FROM business.actor_id::text
   OR (p#>>'{business_result,created_at}')::timestamptz IS DISTINCT FROM business.created_at
   OR p#>>'{business_result,verification}' IS DISTINCT FROM coalesce(verification.payload->>'state','pending')
   OR p#>>'{business_result,verification_authority_id}' IS DISTINCT FROM verification.id::text
   OR p#>'{business_result,verification_details}' IS DISTINCT FROM coalesce(verification.payload->'details','null'::jsonb)
   OR p#>'{business_result,head_revision}' IS DISTINCT FROM business_head.payload->'head_revision'
   OR p#>>'{business_result,head_authority_id}' IS DISTINCT FROM business_head.id::text
  THEN RAISE EXCEPTION 'retrospective_business_result_binding' USING ERRCODE='23514'; END IF;
  FOREACH field IN ARRAY ARRAY['submission_id','stage','source_type','source_version_id','evidence_refs','announced_at','known_at','reason','supersedes_id','correction_reason'] LOOP
   IF p#>ARRAY['business_result',field] IS DISTINCT FROM business.payload->field THEN RAISE EXCEPTION 'retrospective_business_result_native_field' USING ERRCODE='23514'; END IF;
  END LOOP;
 END IF;
 IF comparison IS NOT NULL AND comparison<>'null'::jsonb THEN
  IF NOT design.package_json_keys(p->'comparison',ARRAY['manifest','digest'])
   OR comparison IS DISTINCT FROM design.package_retrospective_comparison(NEW.bid_id,(selected->>'baseline_run_id')::uuid,(selected->>'submitted_run_id')::uuid)
   OR p#>>'{comparison,digest}' IS DISTINCT FROM design.package_submission_digest(comparison)
   OR comparison#>>'{left,id}' IS DISTINCT FROM selected->>'baseline_run_id'
   OR comparison#>>'{right,id}' IS DISTINCT FROM selected->>'submitted_run_id'
   OR comparison#>>'{right,scope,package_id}' IS DISTINCT FROM binding.package_id::text
   OR comparison#>>'{right,scope,revision_id}' IS DISTINCT FROM binding.revision_id::text
   OR comparison->>'bid_id' IS DISTINCT FROM NEW.bid_id::text
   OR comparison->'risk_resolution_assessed' IS DISTINCT FROM 'false'::jsonb
   OR comparison->'formal_scoring_eligible' IS DISTINCT FROM 'false'::jsonb
   OR comparison->'inventory_complete' IS DISTINCT FROM 'false'::jsonb
   OR comparison->'submission_eligible' IS DISTINCT FROM 'false'::jsonb
  THEN RAISE EXCEPTION 'retrospective_comparison_scope' USING ERRCODE='23514'; END IF;
  FOREACH side IN ARRAY ARRAY['left','right'] LOOP
   SELECT * INTO run FROM design.bid_package_review_runs WHERE id=(comparison#>>ARRAY[side,'id'])::uuid AND bid_id=NEW.bid_id;
   SELECT * INTO result FROM design.bid_package_review_results WHERE run_id=run.id;
   IF run.id IS NULL OR result.run_id IS NULL OR comparison#>>ARRAY[side,'input_digest'] IS DISTINCT FROM run.input_digest::text
    OR comparison#>>ARRAY[side,'result_digest'] IS DISTINCT FROM result.digest::text
    OR comparison#>ARRAY[side,'scope'] IS DISTINCT FROM run.input_manifest->'scope'
    OR NOT EXISTS(SELECT FROM design.bid_package_revisions r WHERE r.id=(run.input_manifest#>>'{scope,revision_id}')::uuid AND r.identity_snapshot=binding.manifest->'package_identity')
   THEN RAISE EXCEPTION 'retrospective_review_identity' USING ERRCODE='23514'; END IF;
   FOR native IN SELECT * FROM jsonb_array_elements(result.manifest->'matrix') LOOP
    SELECT value INTO item FROM jsonb_array_elements(comparison->'items') WHERE value->>'requirement_id'=native->>'requirement_id';
    IF item IS NULL OR item#>>ARRAY[side,'row_digest'] IS DISTINCT FROM design.package_submission_digest(native) THEN RAISE EXCEPTION 'retrospective_comparison_row_missing' USING ERRCODE='23514'; END IF;
    FOREACH field IN ARRAY ARRAY['requirement_digest','rule_digest','rule_kind','requirement_statement','applicability','target_part_ids','verdict','statement','limitations'] LOOP
     IF item#>ARRAY[side,field] IS DISTINCT FROM native->field THEN RAISE EXCEPTION 'retrospective_comparison_row_forged' USING ERRCODE='23514'; END IF;
    END LOOP;
   END LOOP;
  END LOOP;
  IF jsonb_array_length(comparison->'items')<>(SELECT count(DISTINCT matrix_row->>'requirement_id') FROM design.bid_package_review_results r CROSS JOIN LATERAL jsonb_array_elements(r.manifest->'matrix')matrix_row WHERE r.run_id IN((selected->>'baseline_run_id')::uuid,(selected->>'submitted_run_id')::uuid)) THEN RAISE EXCEPTION 'retrospective_comparison_row_set' USING ERRCODE='23514'; END IF;
 END IF;
 -- Independently bind every declared original to the current immutable native original.
 IF jsonb_array_length(p->'documents') NOT BETWEEN 1 AND 100 OR jsonb_array_length(p->'source_snapshot')>20000
 OR jsonb_array_length(p->'source_ids')>400 OR jsonb_array_length(p->'source_ids')<>(SELECT count(DISTINCT x) FROM jsonb_array_elements(p->'source_ids')x)
 THEN RAISE EXCEPTION 'retrospective_capacity_or_duplicate' USING ERRCODE='23514'; END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(p->'documents') LOOP
  IF NOT design.package_json_keys(item,ARRAY['id','original_name','digest','byte_size']) OR NOT EXISTS(SELECT FROM design.document_versions d JOIN design.blobs b ON b.id=d.blob_id WHERE d.bid_id=NEW.bid_id AND d.id=(item->>'id')::uuid AND b.digest::text=item->>'digest' AND b.byte_size=(item->>'byte_size')::bigint AND d.original_name=item->>'original_name') THEN RAISE EXCEPTION 'retrospective_original_binding' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR item IN SELECT * FROM jsonb_array_elements(p->'source_snapshot') LOOP
  IF NOT design.package_json_keys(item,ARRAY['source_id','ancestor_id','document_version_id','document_bid_id','kind','policy_class','known_at','digest','revision','status','valid_from','valid_until']) THEN RAISE EXCEPTION 'retrospective_source_keys' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR item IN SELECT * FROM jsonb_array_elements(p->'gaps') LOOP
  IF NOT design.package_json_keys(item,ARRAY['code','message']) OR (item->>'code'~'\S') IS NOT TRUE OR (item->>'message'~'\S') IS NOT TRUE THEN RAISE EXCEPTION 'retrospective_gap_keys' USING ERRCODE='23514'; END IF;
 END LOOP;
 expected:=design.package_retrospective_required_sources(NEW.bid_id,selected);
 IF expected->'sources' IS DISTINCT FROM p->'source_ids'
 OR expected->'documents' IS DISTINCT FROM (SELECT jsonb_agg(d->>'id' ORDER BY d->>'id') FROM jsonb_array_elements(p->'documents')d)
 THEN RAISE EXCEPTION 'retrospective_source_set_incomplete' USING ERRCODE='23514'; END IF;
 -- Every submitted/authority member, receipt and explicitly selected official original is present.
 FOR required IN SELECT ARRAY[d] FROM (
  SELECT document_version_id AS d FROM design.bid_package_members WHERE revision_id IN(binding.revision_id,binding.authority_revision_id)
  UNION SELECT (binding.manifest#>>'{evidence,document_version_id}')::uuid
  UNION SELECT outcome.source_version_id WHERE outcome.id IS NOT NULL
  UNION SELECT (p#>>'{business_result,source_version_id}')::uuid WHERE p#>>'{business_result,source_version_id}' IS NOT NULL
 )q LOOP
  IF NOT EXISTS(SELECT FROM jsonb_array_elements(p->'documents')d WHERE d->>'id'=required[1]::text)
   OR NOT (p->'source_ids' ? public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42'::uuid,'document-original:'||required[1]::text)::text)
  THEN RAISE EXCEPTION 'retrospective_required_original_missing' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NOT design.package_retrospective_inputs_unchanged(m) THEN RAISE EXCEPTION 'retrospective_inputs_changed' USING ERRCODE='23514'; END IF;
 request:=jsonb_build_object('selection',selected,'preview_digest',m#>'{preview,digest}','title',m->'title','notes',m->'notes');
 condition:=format('"package-retrospective-preview:%s:%s"',NEW.bid_id,m#>>'{preview,digest}');
 IF command.actor_id IS DISTINCT FROM NEW.actor_id OR command.command_kind<>'package-retrospective-freeze' OR command.target_id IS DISTINCT FROM NEW.bid_id
 OR command.request_digest::text IS DISTINCT FROM design.package_submission_digest(jsonb_build_object('body',request,'if_match',condition)) THEN RAISE EXCEPTION 'retrospective_command_binding' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER retrospective_context BEFORE INSERT ON package_retrospectives FOR EACH ROW EXECUTE FUNCTION package_retrospective_guard();

CREATE FUNCTION package_retrospective_knowledge_version_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design,retrieval AS $$
DECLARE link design.package_retrospective_knowledge_links; source retrieval.source_nodes; r design.package_retrospectives;
BEGIN
 SELECT * INTO link FROM design.package_retrospective_knowledge_links WHERE knowledge_id=NEW.item_id;
 IF link.knowledge_id IS NULL THEN RETURN NEW; END IF;
 PERFORM id FROM design.bids WHERE id=link.bid_id FOR UPDATE;
 PERFORM pg_advisory_xact_lock(90127,1);
 SELECT * INTO r FROM design.package_retrospectives WHERE id=link.retrospective_id;
 SELECT * INTO source FROM retrieval.source_nodes WHERE id=NEW.source_id;
 IF NOT design.package_retrospective_inputs_unchanged(r.manifest) OR NOT design.package_retrospective_sources_available(r.manifest)
 OR source.policy_class IS DISTINCT FROM 'derived_mixed' OR NOT ('retrospective'=ANY(NEW.categories)) OR 'company_fact'=ANY(NEW.categories)
 OR NEW.applicability->'retrospective_origin' IS DISTINCT FROM design.package_retrospective_origin(link)
 OR NEW.applicability->>'origin_bid_id' IS DISTINCT FROM link.bid_id::text
 OR NOT EXISTS(SELECT FROM retrieval.lineage_edges WHERE child_id=NEW.source_id AND parent_id=link.source_id)
 THEN RAISE EXCEPTION 'retrospective_knowledge_lineage_required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER retrospective_lineage BEFORE INSERT ON retrieval.knowledge_versions FOR EACH ROW EXECUTE FUNCTION package_retrospective_knowledge_version_guard();

CREATE FUNCTION package_retrospective_knowledge_link_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design,retrieval AS $$
DECLARE r design.package_retrospectives; v retrieval.knowledge_versions; n retrieval.source_nodes;
 command design.commands; origin jsonb; marker retrieval.source_nodes;
BEGIN
 PERFORM id FROM design.bids WHERE id=NEW.bid_id FOR UPDATE;
 PERFORM pg_advisory_xact_lock(90127,1);
 SELECT * INTO r FROM design.package_retrospectives WHERE id=NEW.retrospective_id AND bid_id=NEW.bid_id;
 SELECT * INTO v FROM retrieval.knowledge_versions WHERE item_id=NEW.knowledge_id AND id=NEW.knowledge_version_id;
 SELECT * INTO n FROM retrieval.source_nodes WHERE id=v.source_id;
 SELECT * INTO marker FROM retrieval.source_nodes WHERE id=NEW.source_id;
 SELECT * INTO command FROM design.commands WHERE id=NEW.command_id;
 origin:=jsonb_build_object('retrospective_id',r.id,'retrospective_digest',r.digest,'preview_digest',r.manifest#>'{preview,digest}','source_id',NEW.source_id);
 IF current_setting('transaction_isolation')<>'read committed' OR r.id IS NULL OR r.digest<>NEW.retrospective_digest
 OR v.id IS NULL OR v.version_no<>1 OR v.created_by<>NEW.actor_id OR v.categories<>ARRAY['retrospective']::text[]
 OR v.applicability->>'readiness' IS DISTINCT FROM 'needs_applicability' OR v.applicability->>'origin_bid_id' IS DISTINCT FROM NEW.bid_id::text
 OR v.applicability->'retrospective_origin' IS DISTINCT FROM origin
 OR n.policy_class<>'derived_mixed' OR marker.kind<>'summary' OR marker.policy_class<>'post_outcome'
 OR marker.digest<>r.digest OR marker.known_at<r.created_at OR marker.known_at<>NEW.created_at
 OR NOT EXISTS(SELECT FROM retrieval.source_heads WHERE source_id=n.id AND status='candidate')
 OR EXISTS(SELECT FROM retrieval.knowledge_items WHERE id=NEW.knowledge_id AND published_version_id IS NOT NULL)
 OR NOT EXISTS(SELECT FROM retrieval.lineage_edges WHERE child_id=n.id AND parent_id=marker.id)
 OR (SELECT coalesce(jsonb_agg(parent_id::text ORDER BY parent_id::text),'[]'::jsonb) FROM retrieval.lineage_edges WHERE child_id=marker.id) IS DISTINCT FROM r.manifest#>'{preview,manifest,source_ids}'
 OR NOT design.package_retrospective_inputs_unchanged(r.manifest)
 OR NOT design.package_retrospective_sources_available(r.manifest)
 OR EXISTS(SELECT FROM retrieval.source_ancestors a JOIN retrieval.source_nodes s ON s.id=a.ancestor_id LEFT JOIN retrieval.source_heads h ON h.source_id=s.id WHERE a.source_id=marker.id AND (h.status IS DISTINCT FROM 'published' OR s.known_at>clock_timestamp() OR h.valid_from>clock_timestamp() OR h.valid_until<=clock_timestamp()))
 OR command.actor_id IS DISTINCT FROM NEW.actor_id OR command.command_kind<>'package-retrospective-knowledge' OR command.target_id IS DISTINCT FROM r.id
 OR command.request_digest::text IS DISTINCT FROM design.package_submission_digest(jsonb_build_object('body',jsonb_build_object('retrospective_digest',r.digest,'reason',NEW.reason),'if_match',format('"package-retrospective:%s:%s"',r.id,r.digest)))
 THEN RAISE EXCEPTION 'retrospective_knowledge_candidate_binding' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER retrospective_knowledge_context BEFORE INSERT ON package_retrospective_knowledge_links FOR EACH ROW EXECUTE FUNCTION package_retrospective_knowledge_link_guard();

CREATE FUNCTION package_retrospective_publication_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design,retrieval AS $$
DECLARE link design.package_retrospective_knowledge_links; r design.package_retrospectives;
BEGIN
 IF NEW.published_version_id IS NOT DISTINCT FROM OLD.published_version_id OR NEW.published_version_id IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO link FROM design.package_retrospective_knowledge_links WHERE knowledge_id=NEW.id;
 IF link.knowledge_id IS NULL THEN RETURN NEW; END IF;
 PERFORM id FROM design.bids WHERE id=link.bid_id FOR UPDATE;
 PERFORM pg_advisory_xact_lock(90127,1);
 SELECT * INTO r FROM design.package_retrospectives WHERE id=link.retrospective_id;
 IF NOT design.package_retrospective_inputs_unchanged(r.manifest) OR NOT design.package_retrospective_sources_available(r.manifest) THEN RAISE EXCEPTION 'retrospective_publication_source_changed' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER retrospective_publication BEFORE UPDATE OF published_version_id ON retrieval.knowledge_items FOR EACH ROW EXECUTE FUNCTION package_retrospective_publication_guard();

REVOKE ALL ON package_retrospectives,package_retrospective_knowledge_links FROM PUBLIC,tender_worker;
GRANT SELECT,INSERT ON package_retrospectives,package_retrospective_knowledge_links TO tender_api;
REVOKE ALL ON FUNCTION package_retrospective_origin(design.package_retrospective_knowledge_links),package_retrospective_human(uuid,uuid),package_retrospective_required_sources(uuid,jsonb),package_retrospective_comparison(uuid,uuid,uuid),package_retrospective_inputs_unchanged(jsonb),package_retrospective_sources_available(jsonb),package_retrospective_guard(),package_retrospective_knowledge_version_guard(),package_retrospective_knowledge_link_guard(),package_retrospective_publication_guard() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION package_retrospective_origin(design.package_retrospective_knowledge_links),package_retrospective_human(uuid,uuid),package_retrospective_required_sources(uuid,jsonb),package_retrospective_comparison(uuid,uuid,uuid),package_retrospective_inputs_unchanged(jsonb),package_retrospective_sources_available(jsonb),package_retrospective_guard(),package_retrospective_knowledge_version_guard(),package_retrospective_knowledge_link_guard(),package_retrospective_publication_guard() TO tender_api;
COMMIT;
