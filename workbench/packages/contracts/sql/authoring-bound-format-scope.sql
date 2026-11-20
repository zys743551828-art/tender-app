-- Optional numeric project layout for fixed technical authoring.
-- Object-owner upgrade after B1/B2 and authoring structure tables; never run at application startup.
BEGIN;
SET search_path=pg_catalog,design;

-- Package effectivity is necessary but not sufficient: a parse still present in
-- a package can cease to be the latest parse in the project's writing materials.
CREATE FUNCTION design.authoring_bound_format_source_current(project uuid, ref jsonb) RETURNS boolean
 LANGUAGE sql SET search_path=pg_catalog,design AS $$
 SELECT EXISTS(
  SELECT FROM design.bid_profiles bp
  JOIN design.parse_runs p ON p.bid_id=bp.bid_id
  JOIN design.evidence_blocks e ON e.bid_id=p.bid_id AND e.parse_id=p.id
  JOIN retrieval.source_heads h ON h.source_id=public.uuid_generate_v5(
    '8d6cdd5c-1a28-45c6-ac26-e293b1d16f42','document-parse:'||p.id::text)
  WHERE bp.bid_id=project AND p.document_version_id::text=ref->>'document_version_id'
   AND e.id::text=ref->>'evidence_id' AND h.source_id::text=ref->>'source_id'
   AND h.revision::text=ref->>'source_revision' AND p.coverage<>'failed'
   AND p.id=(SELECT newest.id FROM design.parse_runs newest
    WHERE newest.bid_id=project AND newest.document_version_id=p.document_version_id
    ORDER BY newest.created_at DESC,newest.id DESC LIMIT 1)
   AND NOT EXISTS(SELECT FROM retrieval.source_ancestors ancestors
    LEFT JOIN retrieval.source_nodes n ON n.id=ancestors.ancestor_id
    LEFT JOIN retrieval.source_heads head ON head.source_id=n.id
    WHERE ancestors.source_id=h.source_id
     AND (n.kind IS DISTINCT FROM 'document' OR n.policy_class IS DISTINCT FROM 'prebid_content'
       OR head.status IS DISTINCT FROM 'published' OR head.valid_from IS NULL
       OR n.known_at>statement_timestamp() OR head.valid_from>statement_timestamp()
       OR head.valid_until<=statement_timestamp()
       OR NOT EXISTS(SELECT FROM design.document_versions v
        WHERE v.bid_id=project AND v.id=n.document_version_id
         AND (v.id=bp.current_body_id OR EXISTS(SELECT FROM design.material_assignments m
          WHERE m.bid_id=project AND m.snapshot_id=bp.current_material_id AND m.document_version_id=v.id
           AND m.role IN ('tender','supplement','drawing','boq','body','other'))))))
 )
$$;

CREATE FUNCTION design.authoring_bound_format_metadata(x jsonb) RETURNS boolean
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,design AS $$
 SELECT coalesce(x#>'{target,snapshot_manifest,authoring_structure,metadata,format_bindings}','[]')<>'[]'
     OR coalesce(x#>'{target,snapshot_manifest,authoring_structure,metadata,format_binding_manifest}','[]')<>'[]'
$$;

CREATE FUNCTION design.authoring_bound_format_input_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE x jsonb=NEW.context_text::jsonb; marker text=x#>>'{method,bound_format_method}';
 target jsonb=x#>'{request,target_section}'; tree jsonb=x#>'{target,snapshot_manifest,authoring_structure}';
 frozen_metadata jsonb=tree->'metadata'; bindings jsonb=frozen_metadata->'format_bindings';
 proofs jsonb=frozen_metadata->'format_binding_manifest'; expected_style jsonb;
 binding jsonb; basis jsonb; rule jsonb; refs jsonb; ref jsonb; field_name text;
 allowed text[]=ARRAY['font_size_halfpoints','paragraph_after_twips','margin_top_twips',
   'margin_right_twips','margin_bottom_twips','margin_left_twips'];
BEGIN
 IF NOT design.authoring_bound_format_metadata(x) THEN
  IF marker IS NOT NULL THEN
   RAISE EXCEPTION 'AUTHORING_PACKAGE_BOUND_FORMAT_INVALID' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'ASSISTANT_REQUIRES_READ_COMMITTED' USING ERRCODE='25000'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 PERFORM id FROM design.drafts WHERE id=(target->>'draft_id')::uuid AND bid_id=NEW.bid_id FOR UPDATE;
 PERFORM pg_advisory_xact_lock(90127,1);
 PERFORM h.source_id FROM retrieval.source_heads h
  WHERE h.source_id IN(SELECT (s.value->>'id')::uuid FROM jsonb_array_elements(x->'sources') s)
  ORDER BY h.source_id FOR UPDATE;
 SELECT t.config INTO expected_style
  FROM design.draft_snapshots s JOIN design.authoring_structure_versions v
   ON v.bid_id=s.bid_id AND v.draft_id=s.draft_id AND v.snapshot_id=s.id AND v.draft_revision=s.revision
  JOIN design.template_versions t ON t.id=v.style_template_version_id AND t.kind='layout'
  WHERE s.bid_id=NEW.bid_id AND s.draft_id=(target->>'draft_id')::uuid AND s.id=(target->>'snapshot_id')::uuid
   AND s.digest::text=target->>'snapshot_digest' AND s.manifest=x#>'{target,snapshot_manifest}'
   AND v.id::text=tree->>'id' AND v.digest::text=tree->>'digest' AND v.metadata=frozen_metadata
   AND t.id::text=tree#>>'{style_template,id}' AND t.config=tree#>'{style_template,config}';
 IF marker IS DISTINCT FROM 'retained_numeric_project_format/1' OR x#>>'{method,saved_plan_method}' IS NOT NULL
  OR tree->'plans' IS DISTINCT FROM '{}'::jsonb
  OR coalesce(frozen_metadata->'word_import_sources','[]') NOT IN ('[]'::jsonb,'{}'::jsonb)
  OR x#>'{target,snapshot,authoring_structure}' IS DISTINCT FROM tree OR expected_style IS NULL
  OR jsonb_typeof(bindings) IS DISTINCT FROM 'array' OR jsonb_typeof(proofs) IS DISTINCT FROM 'array'
  OR coalesce(frozen_metadata->>'format_review_ack','') !~ '^[0-9a-f]{64}$'
 THEN RAISE EXCEPTION 'AUTHORING_PACKAGE_BOUND_FORMAT_INVALID' USING ERRCODE='23514'; END IF;
 IF jsonb_array_length(bindings) NOT BETWEEN 1 AND 6
  OR (SELECT count(DISTINCT value->>'field') FROM jsonb_array_elements(bindings))<>jsonb_array_length(bindings)
  OR bindings IS DISTINCT FROM (SELECT jsonb_agg(value-'basis'-'interpretation' ORDER BY ord)
       FROM jsonb_array_elements(proofs) WITH ORDINALITY p(value,ord))
 THEN RAISE EXCEPTION 'AUTHORING_PACKAGE_BOUND_FORMAT_INVALID' USING ERRCODE='23514'; END IF;
 FOR binding IN SELECT value FROM jsonb_array_elements(proofs) LOOP
  field_name := binding->>'field'; basis := binding->'basis'; refs := basis#>'{evidence_basis,references}';
  SELECT item.value INTO rule FROM jsonb_array_elements(x#>'{inventory,record,manifest,requirements}') item
   WHERE item.value->>'rule_id'=binding->>'rule_id';
  IF NOT(field_name=ANY(allowed)) OR (binding->>'value') !~ '^[0-9]{1,5}$'
   OR jsonb_typeof(binding->'value') IS DISTINCT FROM 'number' OR NOT(expected_style ? field_name)
   OR binding->>'interpretation' IS DISTINCT FROM 'human_bound_field_semantics_not_automatically_verified'
   OR (CASE field_name
      WHEN 'font_size_halfpoints' THEN (binding->>'value')::numeric BETWEEN 16 AND 48
      WHEN 'paragraph_after_twips' THEN (binding->>'value')::numeric BETWEEN 0 AND 720
      ELSE (binding->>'value')::numeric BETWEEN 360 AND 4320 END) IS DISTINCT FROM true
   OR rule IS NULL OR basis->>'rule_id' IS DISTINCT FROM rule->>'rule_id'
   OR basis->>'decision_id' IS DISTINCT FROM rule->>'decision_id'
   OR rule#>>'{decision_snapshot,object_id}' IS DISTINCT FROM rule->>'rule_id'
   OR NOT EXISTS(SELECT FROM design.decision_heads h
    JOIN design.decisions d ON d.id=h.decision_id AND d.bid_id=h.bid_id
    WHERE h.bid_id=NEW.bid_id AND h.object_kind='rule' AND h.object_id::text=rule->>'rule_id'
     AND d.id::text=basis->>'decision_id' AND h.revision::text=basis->>'decision_revision'
     AND d.object_id=h.object_id AND d.object_kind='rule' AND d.decision='confirmed'
     AND to_jsonb(d)=rule->'decision_snapshot')
   OR (SELECT count(*) FROM design.audit_entries a WHERE a.bid_id=NEW.bid_id
    AND a.event_type='human.decision_recorded' AND a.payload->>'decision_id'=basis->>'decision_id')<>1
   OR NOT EXISTS(SELECT FROM design.audit_entries a WHERE a.bid_id=NEW.bid_id
    AND a.event_type='human.decision_recorded' AND a.payload->>'decision_id'=basis->>'decision_id'
    AND a.payload->>'object_id'=rule->>'rule_id' AND a.payload->>'decision'='confirmed'
    AND a.payload->'basis'=basis->'evidence_basis' AND a.actor_id::text=rule#>>'{decision_snapshot,actor_id}')
   OR jsonb_typeof(refs) IS DISTINCT FROM 'array' OR jsonb_typeof(binding->'source_refs') IS DISTINCT FROM 'array'
  THEN RAISE EXCEPTION 'AUTHORING_PACKAGE_BOUND_FORMAT_INVALID' USING ERRCODE='23514'; END IF;
  IF jsonb_array_length(refs)=0 OR jsonb_array_length(binding->'source_refs')=0
   OR NOT(refs @> (binding->'source_refs'))
   OR (SELECT jsonb_agg(r.value->>'evidence_id' ORDER BY r.value->>'evidence_id') FROM jsonb_array_elements(refs) r)
      IS DISTINCT FROM (SELECT jsonb_agg(e.value ORDER BY e.value) FROM jsonb_array_elements(rule#>'{rule_snapshot,evidence_ids}') e)
   OR basis#>>'{evidence_basis,source_closure_digest}' IS DISTINCT FROM
    (SELECT design.authoring_package_digest(jsonb_agg(s.value ORDER BY s.value->>'source_id',s.value->>'id'))
      FROM jsonb_array_elements(x->'sources') s WHERE s.value->>'source_id' IN
      (SELECT r.value->>'source_id' FROM jsonb_array_elements(refs) r))
  THEN RAISE EXCEPTION 'AUTHORING_PACKAGE_BOUND_FORMAT_OUTSIDE_SELECTION' USING ERRCODE='23514'; END IF;
  FOR ref IN SELECT value FROM jsonb_array_elements(refs) LOOP
   IF NOT design.authoring_bound_format_source_current(NEW.bid_id,ref)
    OR NOT EXISTS(SELECT FROM jsonb_array_elements(x->'documents') d
     WHERE d.value->>'package_role'='authority' AND d.value->>'document_version_id'=ref->>'document_version_id'
      AND public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42','document-parse:'||(d.value->>'parse_id'))::text=ref->>'source_id'
      AND EXISTS(SELECT FROM jsonb_array_elements(d.value->'blocks') e WHERE e.value->>'id'=ref->>'evidence_id'))
   THEN RAISE EXCEPTION 'AUTHORING_PACKAGE_BOUND_FORMAT_OUTSIDE_SELECTION' USING ERRCODE='23514'; END IF;
  END LOOP;
  expected_style := jsonb_set(expected_style,ARRAY[field_name],binding->'value',false);
 END LOOP;
 IF expected_style IS DISTINCT FROM frozen_metadata->'effective_style' THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_BOUND_FORMAT_INVALID' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION design.authoring_bound_format_job_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE x jsonb; method jsonb; input_marker text; execution_marker text;
BEGIN
 SELECT context_text::jsonb INTO x FROM design.authoring_package_inputs
  WHERE id=NEW.input_id AND bid_id=NEW.bid_id;
 SELECT input_manifest#>'{plan,execution_policy}' INTO method FROM design.assistant_jobs
  WHERE id=NEW.job_id AND bid_id=NEW.bid_id;
 input_marker := x#>>'{method,bound_format_method}';
 execution_marker := method->>'bound_format_method';
 IF x IS NULL OR (design.authoring_bound_format_metadata(x) AND (
     input_marker IS DISTINCT FROM 'retained_numeric_project_format/1'
     OR execution_marker IS DISTINCT FROM 'retained_numeric_project_format_projection/1'
     OR method->>'saved_plan_method' IS NOT NULL))
  OR (NOT design.authoring_bound_format_metadata(x) AND (input_marker IS NOT NULL OR execution_marker IS NOT NULL))
 THEN RAISE EXCEPTION 'AUTHORING_PACKAGE_BOUND_FORMAT_INVALID' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

-- Invoked only inside the native job authority while bid/draft/source locks
-- are still held. Principal, immutable binding and complete input have already been checked.
CREATE FUNCTION design.authoring_bound_format_assert_current(job uuid) RETURNS void
 LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
DECLARE x jsonb; project uuid; proof jsonb; ref jsonb;
BEGIN
 SELECT i.bid_id,i.context_text::jsonb INTO project,x
 FROM design.authoring_package_job_bindings b
 JOIN design.authoring_package_inputs i ON i.bid_id=b.bid_id AND i.id=b.input_id
 WHERE b.job_id=job;
 IF x#>>'{method,bound_format_method}' IS DISTINCT FROM 'retained_numeric_project_format/1'
 THEN RAISE EXCEPTION 'AUTHORING_PACKAGE_BOUND_FORMAT_UNVERIFIED' USING ERRCODE='23514'; END IF;
 FOR proof IN SELECT value FROM jsonb_array_elements(
  x#>'{target,snapshot_manifest,authoring_structure,metadata,format_binding_manifest}') LOOP
  IF NOT EXISTS(SELECT FROM design.decision_heads h WHERE h.bid_id=project AND h.object_kind='rule'
   AND h.object_id::text=proof->>'rule_id' AND h.decision_id::text=proof#>>'{basis,decision_id}'
   AND h.revision::text=proof#>>'{basis,decision_revision}')
  THEN RAISE EXCEPTION 'AUTHORING_PACKAGE_BOUND_FORMAT_RULE_CHANGED' USING ERRCODE='23514'; END IF;
  FOR ref IN SELECT value FROM jsonb_array_elements(proof#>'{basis,evidence_basis,references}') LOOP
   IF NOT design.authoring_bound_format_source_current(project,ref) THEN
    RAISE EXCEPTION 'AUTHORING_PACKAGE_BOUND_FORMAT_SOURCE_CHANGED' USING ERRCODE='23514'; END IF;
  END LOOP;
 END LOOP;
END $$;

-- Keep the B2 RPC body and existing authorization limits; add only the known optional dispatch case.
-- This also covers native budget reserve/dispatch and native candidate consumption/publishing paths.
CREATE OR REPLACE FUNCTION design.authoring_package_assert_job(job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE binding design.authoring_package_job_bindings; j design.assistant_jobs; i design.assistant_logical_intents; op design.operations;
BEGIN
 PERFORM design.authoring_package_check_job_binding(job);
 SELECT * INTO binding FROM design.authoring_package_job_bindings WHERE job_id=job;
 SELECT * INTO j FROM design.assistant_jobs WHERE id=job;
 SELECT * INTO i FROM design.assistant_logical_intents WHERE job_id=job;
 PERFORM design.lock_worker_bid(binding.bid_id);
 SELECT * INTO op FROM design.operations WHERE id=j.operation_id AND bid_id=binding.bid_id FOR UPDATE;
 IF i.id IS NULL OR i.actor_id IS DISTINCT FROM binding.actor_id OR i.target IS DISTINCT FROM j.input_manifest#>'{logical_intent,target}'
  OR op.id IS NULL OR op.cancel_requested_at IS NOT NULL OR op.state NOT IN('queued','running','succeeded') THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_EXECUTION_STALE' USING ERRCODE='23514'; END IF;
 PERFORM design.authoring_package_assert_input(binding.input_id);
 PERFORM design.assistant_check_target(i.target,i.actor_id);
 IF j.input_manifest#>>'{plan,execution_policy,bound_format_method}' IS NOT NULL THEN
  IF j.input_manifest#>>'{plan,execution_policy,bound_format_method}' IS DISTINCT FROM
    'retained_numeric_project_format_projection/1' THEN
   RAISE EXCEPTION 'AUTHORING_PACKAGE_BOUND_FORMAT_UNVERIFIED' USING ERRCODE='23514'; END IF;
  PERFORM design.authoring_bound_format_assert_current(job);
 END IF;
END $$;

CREATE CONSTRAINT TRIGGER authoring_bound_format_input AFTER INSERT ON design.authoring_package_inputs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION design.authoring_bound_format_input_guard();
CREATE CONSTRAINT TRIGGER authoring_bound_format_job AFTER INSERT ON design.authoring_package_job_bindings
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION design.authoring_bound_format_job_guard();
REVOKE ALL ON FUNCTION design.authoring_bound_format_source_current(uuid,jsonb),
 design.authoring_bound_format_metadata(jsonb),design.authoring_bound_format_input_guard(),
 design.authoring_bound_format_job_guard(),design.authoring_bound_format_assert_current(uuid)
 FROM PUBLIC,tender_api,tender_worker;
COMMIT;
