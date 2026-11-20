-- Optional native saved-plan scope; keep the existing B1/B2 protocol and permissions.
-- Install only after authoring-package-inputs.sql and authoring-package-jobs.sql.
BEGIN;
SET search_path=pg_catalog,design;

CREATE FUNCTION design.authoring_saved_plan_scope_input_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE x jsonb=NEW.context_text::jsonb;
 target jsonb=x#>'{request,target_section}';
 tree jsonb=x#>'{target,snapshot_manifest,authoring_structure}';
 plans jsonb=coalesce(tree->'plans','{}'::jsonb);
 marker text=x#>>'{method,saved_plan_method}';
 item jsonb; ref jsonb; plan_row design.authoring_plan_versions;
BEGIN
 IF plans='{}'::jsonb THEN
  IF marker IS NOT NULL THEN
   RAISE EXCEPTION 'AUTHORING_SAVED_PLAN_SCOPE_INVALID' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF jsonb_typeof(plans) IS DISTINCT FROM 'object'
  OR marker IS DISTINCT FROM 'retained_saved_plan_scope/1'
  OR coalesce(tree#>'{metadata,format_bindings}','[]'::jsonb) IS DISTINCT FROM '[]'::jsonb
  OR coalesce(tree#>'{metadata,word_import_sources}','[]'::jsonb) NOT IN ('[]'::jsonb,'{}'::jsonb)
  OR x#>'{target,snapshot,authoring_structure}' IS DISTINCT FROM tree
  OR NOT EXISTS(SELECT FROM design.authoring_structure_versions v
    WHERE v.bid_id=NEW.bid_id AND v.draft_id=(target->>'draft_id')::uuid
      AND v.snapshot_id=(target->>'snapshot_id')::uuid AND v.id::text=tree->>'id'
      AND v.digest::text=tree->>'digest')
  OR (SELECT count(*) FROM jsonb_object_keys(plans)) <>
    (SELECT count(*) FROM jsonb_array_elements(tree->'nodes') n
      WHERE n.value->'deleted'='false'::jsonb AND n.value->>'plan_version_id' IS NOT NULL)
 THEN RAISE EXCEPTION 'AUTHORING_SAVED_PLAN_SCOPE_INVALID' USING ERRCODE='23514'; END IF;
 FOR item IN SELECT value FROM jsonb_each(plans) p WHERE p.key=p.value->>'id' LOOP
  SELECT * INTO plan_row FROM design.authoring_plan_versions p WHERE p.id=(item->>'id')::uuid
    AND p.bid_id=NEW.bid_id AND p.draft_id=(target->>'draft_id')::uuid;
  IF plan_row.id IS NULL OR (item-'created_at') IS DISTINCT FROM (to_jsonb(plan_row)-'created_at')
   OR (item->>'created_at')::timestamptz IS DISTINCT FROM plan_row.created_at
   OR NOT EXISTS(SELECT FROM jsonb_array_elements(tree->'nodes') n
     WHERE n.value->'deleted'='false'::jsonb AND n.value->>'plan_version_id'=plan_row.id::text
       AND n.value->>'section_id'=plan_row.section_id::text
       AND (plan_row.section_id::text<>target->>'section_id'
         OR plan_row.base_section_revision=(target->>'base_section_revision')::bigint))
   OR EXISTS(SELECT FROM jsonb_array_elements_text(plan_row.payload->'rule_ids') rule
     WHERE NOT EXISTS(SELECT FROM jsonb_array_elements(x#>'{inventory,record,manifest,requirements}') observed
       WHERE observed.value->>'rule_id'=rule.value))
  THEN RAISE EXCEPTION 'AUTHORING_SAVED_PLAN_SCOPE_INVALID' USING ERRCODE='23514'; END IF;
  FOR ref IN SELECT value FROM jsonb_array_elements(plan_row.payload->'source_refs') LOOP
   IF NOT EXISTS(SELECT FROM design.evidence_blocks e
      JOIN design.parse_runs p ON p.id=e.parse_id AND p.bid_id=e.bid_id
      JOIN retrieval.source_heads h ON h.source_id=public.uuid_generate_v5(
        '8d6cdd5c-1a28-45c6-ac26-e293b1d16f42','document-parse:'||p.id::text)
     WHERE e.bid_id=NEW.bid_id AND e.id=(ref->>'evidence_id')::uuid
       AND p.document_version_id=(ref->>'document_version_id')::uuid
       AND h.source_id=(ref->>'source_id')::uuid AND h.revision=(ref->>'source_revision')::bigint
       AND EXISTS(SELECT FROM jsonb_array_elements(x->'documents') doc
        WHERE doc.value->>'package_role'='authority' AND doc.value->>'parse_id'=p.id::text))
   THEN RAISE EXCEPTION 'AUTHORING_SAVED_PLAN_SOURCE_OUTSIDE_SELECTION' USING ERRCODE='23514'; END IF;
  END LOOP;
 END LOOP;
 IF EXISTS(SELECT FROM jsonb_each(plans) p WHERE p.key IS DISTINCT FROM p.value->>'id')
 THEN RAISE EXCEPTION 'AUTHORING_SAVED_PLAN_SCOPE_INVALID' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION design.authoring_saved_plan_scope_job_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE x jsonb; input_marker text; execution_marker text; has_plans boolean;
BEGIN
 SELECT context_text::jsonb INTO x
   FROM design.authoring_package_inputs WHERE id=NEW.input_id AND bid_id=NEW.bid_id;
 input_marker := x#>>'{method,saved_plan_method}';
 has_plans := coalesce(x#>'{target,snapshot_manifest,authoring_structure,plans}','{}'::jsonb)<>'{}'::jsonb;
 SELECT input_manifest#>>'{plan,execution_policy,saved_plan_method}' INTO execution_marker
   FROM design.assistant_jobs WHERE id=NEW.job_id AND bid_id=NEW.bid_id;
 IF x IS NULL
 OR (NOT has_plans AND (input_marker IS NOT NULL OR execution_marker IS NOT NULL))
 OR (has_plans AND (input_marker IS DISTINCT FROM 'retained_saved_plan_scope/1'
   OR execution_marker IS DISTINCT FROM 'retained_saved_plan_projection/1'))
 THEN RAISE EXCEPTION 'AUTHORING_SAVED_PLAN_METHOD_INVALID' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

-- Called inside the existing native job authority transaction, which already
-- holds the bid, draft, source graph and ancestor head locks. A package may
-- still reference an active parse while ordinary authoring scope has changed.
CREATE FUNCTION design.authoring_saved_plan_assert_current(job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE x jsonb; bid uuid; profile design.bid_profiles; item jsonb; ref jsonb; latest uuid;
BEGIN
 SELECT i.bid_id,i.context_text::jsonb INTO bid,x
 FROM design.authoring_package_job_bindings b
 JOIN design.authoring_package_inputs i ON i.bid_id=b.bid_id AND i.id=b.input_id
 WHERE b.job_id=job;
 IF x#>>'{method,saved_plan_method}' IS DISTINCT FROM 'retained_saved_plan_scope/1'
 THEN RAISE EXCEPTION 'AUTHORING_PACKAGE_SAVED_PLAN_UNVERIFIED' USING ERRCODE='23514'; END IF;
 SELECT * INTO profile FROM design.bid_profiles WHERE bid_id=bid;
 FOR item IN SELECT value FROM jsonb_each(x#>'{target,snapshot_manifest,authoring_structure,plans}') LOOP
  FOR ref IN SELECT value FROM jsonb_array_elements(item#>'{payload,source_refs}') LOOP
   SELECT p.id INTO latest FROM design.parse_runs p
    WHERE p.bid_id=bid AND p.document_version_id=(ref->>'document_version_id')::uuid
    ORDER BY p.created_at DESC,p.id DESC LIMIT 1;
   IF latest IS NULL
   OR NOT EXISTS(SELECT FROM design.evidence_blocks e
      WHERE e.bid_id=bid AND e.parse_id=latest AND e.id=(ref->>'evidence_id')::uuid)
   OR EXISTS(SELECT FROM retrieval.source_ancestors parents
     JOIN retrieval.source_nodes a ON a.id=parents.ancestor_id
     WHERE parents.source_id=(ref->>'source_id')::uuid
       AND (a.document_version_id IS NULL OR NOT (
        a.document_version_id IS NOT DISTINCT FROM profile.current_body_id OR EXISTS(
         SELECT FROM design.material_assignments m
         WHERE m.bid_id=bid AND m.snapshot_id=profile.current_material_id
           AND m.document_version_id=a.document_version_id
           AND m.role IN ('tender','supplement','drawing','boq','body','other')))))
   THEN RAISE EXCEPTION 'AUTHORING_PACKAGE_SAVED_PLAN_SOURCE_CHANGED' USING ERRCODE='23514'; END IF;
  END LOOP;
 END LOOP;
END $$;

CREATE CONSTRAINT TRIGGER authoring_saved_plan_scope_input AFTER INSERT ON design.authoring_package_inputs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION design.authoring_saved_plan_scope_input_guard();
CREATE CONSTRAINT TRIGGER authoring_saved_plan_scope_job AFTER INSERT ON design.authoring_package_job_bindings
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION design.authoring_saved_plan_scope_job_guard();
REVOKE ALL ON FUNCTION design.authoring_saved_plan_scope_input_guard(),design.authoring_saved_plan_scope_job_guard()
 FROM PUBLIC,tender_api,tender_worker;
REVOKE ALL ON FUNCTION design.authoring_saved_plan_assert_current(uuid)
 FROM PUBLIC,tender_api,tender_worker;
GRANT EXECUTE ON FUNCTION design.authoring_saved_plan_assert_current(uuid) TO tender_api,tender_worker;
COMMIT;
