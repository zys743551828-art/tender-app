-- Optional B3. Requires B1 inputs and B2 job/action bindings; never BASE-only authority.
BEGIN;
SET LOCAL search_path=design,public;

CREATE TABLE authoring_exact_revisions(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL,
 draft_id uuid NOT NULL,
 section_id uuid NOT NULL,
 section_revision_id uuid NOT NULL UNIQUE,
 parent_revision_id uuid NOT NULL,
 input_id uuid NOT NULL REFERENCES authoring_package_inputs(id),
 job_id uuid NOT NULL REFERENCES authoring_package_job_bindings(job_id),
 action_id uuid NOT NULL UNIQUE REFERENCES authoring_package_action_bindings(action_id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 actor_id uuid NOT NULL REFERENCES members(id),
 draft_revision bigint NOT NULL CHECK(draft_revision>1),
 manifest jsonb NOT NULL CHECK(jsonb_typeof(manifest)='object'),
 digest sha256 NOT NULL,
 before_action jsonb NOT NULL CHECK(jsonb_typeof(before_action)='object'),
 request_condition text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(bid_id,draft_id,section_id) REFERENCES sections(bid_id,draft_id,id),
 FOREIGN KEY(bid_id,draft_id,section_revision_id) REFERENCES section_revisions(bid_id,draft_id,id),
 FOREIGN KEY(bid_id,draft_id,parent_revision_id) REFERENCES section_revisions(bid_id,draft_id,id),
 UNIQUE(bid_id,id), UNIQUE(draft_id,draft_revision)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON authoring_exact_revisions
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE FUNCTION authoring_exact_replace(node jsonb, selected_node text, replacement text) RETURNS jsonb
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,design AS $$
DECLARE children jsonb;
BEGIN
 IF node#>>'{attrs,id}'=selected_node THEN
  IF node->>'type' NOT IN('paragraph','heading') THEN
   RAISE EXCEPTION 'AUTHORING_EXACT_CONTENT_UNSUPPORTED' USING ERRCODE='23514'; END IF;
  RETURN jsonb_set(node,'{content}',CASE WHEN replacement='' THEN '[]'::jsonb
    ELSE jsonb_build_array(jsonb_build_object('type','text','text',replacement)) END);
 END IF;
 IF node ? 'content' THEN
  SELECT coalesce(jsonb_agg(design.authoring_exact_replace(value,selected_node,replacement) ORDER BY ord),'[]'::jsonb)
   INTO children FROM jsonb_array_elements(node->'content') WITH ORDINALITY AS child(value,ord);
  RETURN jsonb_set(node,'{content}',children);
 END IF;
 RETURN node;
END $$;

CREATE FUNCTION authoring_exact_materialized(job uuid) RETURNS jsonb
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE j design.assistant_jobs; o design.assistant_outputs; content jsonb; result jsonb;
 target jsonb; candidate jsonb; count_nodes bigint; before_hash text; refs jsonb; ref jsonb;
 block_id jsonb; doc jsonb; source jsonb; parse_source uuid;
BEGIN
 SELECT * INTO j FROM design.assistant_jobs WHERE id=job;
 SELECT * INTO o FROM design.assistant_outputs WHERE job_id=job;
 IF j.id IS NULL OR o.job_id IS NULL OR NOT EXISTS(SELECT FROM design.authoring_package_job_bindings WHERE job_id=job)
  OR o.digest::text IS DISTINCT FROM design.authoring_package_digest(o.payload) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_JOB_REQUIRED' USING ERRCODE='23514'; END IF;
 content=j.input_manifest#>'{plan,original_content}'; target=j.input_manifest#>'{plan,target}'; candidate=o.payload;
 WITH RECURSIVE nodes(value) AS (
  SELECT content UNION ALL SELECT child FROM nodes n CROSS JOIN LATERAL jsonb_array_elements(coalesce(n.value->'content','[]'::jsonb)) child
 ) SELECT count(*),min(design.authoring_package_digest(value)) INTO count_nodes,before_hash
  FROM nodes WHERE value#>>'{attrs,id}'=target->>'node_id';
 IF count_nodes<>1 OR before_hash IS DISTINCT FROM target->>'before_node_digest'
  OR candidate->>'node_id' IS DISTINCT FROM target->>'node_id'
  OR candidate->>'before_digest' IS DISTINCT FROM before_hash THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_NODE_IDENTITY_INVALID' USING ERRCODE='23514'; END IF;
 result=design.authoring_exact_replace(content,target->>'node_id',candidate->>'replacement_text');
 refs=content#>'{attrs,source_refs}';
 FOR block_id IN SELECT value FROM jsonb_array_elements(candidate->'evidence_ids') LOOP
  SELECT d.value INTO doc FROM jsonb_array_elements(j.input_manifest#>'{plan,context,documents}') d
   WHERE EXISTS(SELECT FROM jsonb_array_elements(d.value->'blocks') b WHERE b.value->'id'=block_id) LIMIT 1;
  IF doc IS NULL THEN RAISE EXCEPTION 'AUTHORING_EXACT_EVIDENCE_OUTSIDE_INPUT' USING ERRCODE='23514'; END IF;
  parse_source=public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42','document-parse:'||(doc->>'parse_id'));
  SELECT value INTO source FROM jsonb_array_elements(j.input_manifest#>'{plan,context,sources}')
   WHERE value->>'id'=parse_source::text AND value->>'source_id'=parse_source::text;
  IF source IS NULL THEN RAISE EXCEPTION 'AUTHORING_EXACT_SOURCE_OUTSIDE_INPUT' USING ERRCODE='23514'; END IF;
  ref=jsonb_build_object('source_id',parse_source,'source_revision',source->'revision','evidence_id',block_id,'document_version_id',doc->'document_version_id');
  IF NOT EXISTS(SELECT FROM jsonb_array_elements(refs) WHERE value=ref) THEN refs=refs||jsonb_build_array(ref); END IF;
 END LOOP;
 -- Python preserves the first occurrence while removing duplicate original refs too.
 SELECT coalesce(jsonb_agg(value ORDER BY first_ord),'[]'::jsonb) INTO refs FROM (
  SELECT value,min(ord) AS first_ord FROM jsonb_array_elements(refs) WITH ORDINALITY r(value,ord) GROUP BY value
 ) deduplicated;
 result=jsonb_set(result,'{attrs,source_refs}',refs);
 IF result=content THEN RAISE EXCEPTION 'AUTHORING_EXACT_NO_CHANGE' USING ERRCODE='23514'; END IF;
 RETURN result;
END $$;

CREATE FUNCTION authoring_exact_assert_dependencies(selected_id uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE input design.authoring_package_inputs; x jsonb; b jsonb; target jsonb; frozen jsonb;
 actual record; decision jsonb; source jsonb; direct_ids uuid[]; authority_clock timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'ASSISTANT_REQUIRES_READ_COMMITTED' USING ERRCODE='25000'; END IF;
 SELECT * INTO input FROM design.authoring_package_inputs WHERE id=selected_id;
 IF input.id IS NULL OR design.authoring_package_digest(input.manifest) IS DISTINCT FROM input.digest::text
 OR encode(sha256(convert_to(input.context_text,'UTF8')),'hex') IS DISTINCT FROM input.context_digest::text THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_INPUT_BINDING_INVALID' USING ERRCODE='23514'; END IF;
 x=input.context_text::jsonb; b=input.manifest->'selection'; target=b->'target_section';
 PERFORM design.lock_worker_bid(input.bid_id);
 PERFORM id FROM design.drafts WHERE id=(target->>'draft_id')::uuid AND bid_id=input.bid_id FOR UPDATE;
 PERFORM pg_advisory_xact_lock(90127,1);
 IF NOT EXISTS(SELECT FROM design.bid_profiles WHERE bid_id=input.bid_id AND archived_at IS NULL AND phase NOT IN('closed','terminated')) THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_PROJECT_CLOSED' USING ERRCODE='23514'; END IF;
 IF x->'identity' IS DISTINCT FROM design.identity_snapshot_v2(input.bid_id) THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_IDENTITY_CHANGED' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT FROM design.bid_package_requirement_inventories i
  JOIN design.bid_package_requirement_heads h ON h.inventory_id=i.id
  JOIN design.bid_profiles p ON p.bid_id=i.bid_id AND p.current_rule_set_id=i.rule_set_id
  WHERE i.id=(b#>>'{package_context,inventory,id}')::uuid AND i.bid_id=input.bid_id
   AND i.digest::text=b#>>'{package_context,inventory,digest}' AND i.manifest=x#>'{inventory,record,manifest}') THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_INVENTORY_CHANGED' USING ERRCODE='23514'; END IF;
 FOR frozen IN SELECT value FROM jsonb_array_elements(x#>'{inventory,record,manifest,requirements}') LOOP
  SELECT to_jsonb(dec) INTO decision FROM design.rule_items r
   LEFT JOIN design.decision_heads h ON h.bid_id=r.bid_id AND h.object_kind='rule' AND h.object_id=r.id
   LEFT JOIN design.rule_carryovers carry ON carry.bid_id=r.bid_id AND carry.new_rule_id=r.id
   JOIN design.decisions dec ON dec.id=coalesce(h.decision_id,carry.from_decision_id) AND dec.bid_id=r.bid_id
   WHERE r.id=(frozen->>'rule_id')::uuid AND r.bid_id=input.bid_id
    AND r.rule_set_id=(b#>>'{package_context,inventory,rule_set_id}')::uuid;
  IF decision IS DISTINCT FROM frozen->'decision_snapshot' OR decision->>'decision' IS DISTINCT FROM 'confirmed' THEN
   RAISE EXCEPTION 'AUTHORING_PACKAGE_RULE_CHANGED' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT FROM design.fact_heads h WHERE h.bid_id=input.bid_id
  AND h.fact_set_id=(b#>>'{facts,fact_set_id}')::uuid AND h.revision=(b#>>'{facts,fact_head_revision}')::bigint) THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_FACT_HEAD_CHANGED' USING ERRCODE='23514'; END IF;
 FOR frozen IN SELECT value FROM jsonb_array_elements(x#>'{facts,items}') LOOP
  SELECT dec.*,h.revision AS decision_revision INTO actual FROM design.decision_heads h
   JOIN design.decisions dec ON dec.id=h.decision_id WHERE h.bid_id=input.bid_id
    AND h.object_kind='fact' AND h.object_id=(frozen#>>'{item,fact,id}')::uuid;
  IF actual.id IS NULL OR (to_jsonb(actual)-'created_at') IS DISTINCT FROM ((frozen#>'{item,decision}')-'created_at')
   OR actual.created_at IS DISTINCT FROM (frozen#>>'{item,decision,created_at}')::timestamptz THEN
   RAISE EXCEPTION 'AUTHORING_PACKAGE_FACT_CHANGED' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR frozen IN SELECT value FROM jsonb_array_elements(input.manifest->'fact_declarations') LOOP
  SELECT * INTO actual FROM design.authoring_package_fact_scopes s WHERE s.input_id=input.id
   AND s.bid_id=input.bid_id AND s.fact_id=(frozen#>>'{manifest,fact_id}')::uuid ORDER BY revision DESC LIMIT 1;
  IF actual.id IS NULL OR actual.digest::text IS DISTINCT FROM frozen->>'digest'
   OR actual.manifest IS DISTINCT FROM frozen->'manifest' OR actual.manifest->>'action' IS DISTINCT FROM 'bind' THEN
   RAISE EXCEPTION 'AUTHORING_PACKAGE_FACT_DECLARATION_WITHDRAWN' USING ERRCODE='23514'; END IF;
 END LOOP;
 SELECT array_agg(DISTINCT (value->>'source_id')::uuid) INTO direct_ids FROM jsonb_array_elements(x->'sources');
 PERFORM h.source_id FROM retrieval.source_heads h WHERE h.source_id IN
  (SELECT ancestor_id FROM retrieval.source_ancestors WHERE source_id=ANY(direct_ids)) ORDER BY h.source_id FOR UPDATE;
 IF (SELECT count(*) FROM retrieval.source_ancestors WHERE source_id=ANY(direct_ids)) IS DISTINCT FROM jsonb_array_length(x->'sources')::bigint
 OR (SELECT count(DISTINCT (value->>'source_id',value->>'id')) FROM jsonb_array_elements(x->'sources')) IS DISTINCT FROM jsonb_array_length(x->'sources')::bigint THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_SOURCE_CHANGED' USING ERRCODE='23514'; END IF;
 FOR source IN SELECT value FROM jsonb_array_elements(x->'sources') LOOP
  SELECT n.*,h.revision,h.status,h.valid_from,h.valid_until INTO actual FROM retrieval.source_ancestors a
   JOIN retrieval.source_nodes n ON n.id=a.ancestor_id LEFT JOIN retrieval.source_heads h ON h.source_id=n.id
   WHERE a.source_id=(source->>'source_id')::uuid AND a.ancestor_id=(source->>'id')::uuid;
  IF actual.id IS NULL OR actual.revision IS NULL OR actual.valid_from IS NULL
   OR actual.kind IS DISTINCT FROM 'document' OR actual.policy_class IS DISTINCT FROM 'prebid_content'
   OR actual.document_version_id::text IS DISTINCT FROM source->>'document_version_id'
   OR actual.digest::text IS DISTINCT FROM source->>'digest' OR actual.revision IS DISTINCT FROM (source->>'revision')::bigint
   OR actual.status IS DISTINCT FROM 'published' OR actual.status IS DISTINCT FROM source->>'status'
   OR actual.known_at IS DISTINCT FROM (source->>'known_at')::timestamptz
   OR actual.valid_from IS DISTINCT FROM (source->>'valid_from')::timestamptz
   OR actual.valid_until IS DISTINCT FROM (source->>'valid_until')::timestamptz THEN
   RAISE EXCEPTION 'AUTHORING_PACKAGE_SOURCE_CHANGED' USING ERRCODE='23514'; END IF;
 END LOOP;
 authority_clock=clock_timestamp();
 IF EXISTS(SELECT FROM jsonb_array_elements(x->'sources') frozen
  JOIN retrieval.source_nodes n ON n.id=(frozen.value->>'id')::uuid
  JOIN retrieval.source_heads h ON h.source_id=n.id
  WHERE n.known_at>authority_clock OR h.valid_from>authority_clock OR h.valid_until<=authority_clock) THEN
  RAISE EXCEPTION 'AUTHORING_PACKAGE_SOURCE_EXPIRED' USING ERRCODE='23514'; END IF;
END $$;



CREATE FUNCTION authoring_exact_check_revision(selected_revision uuid) RETURNS void
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE q design.authoring_exact_revisions; r design.section_revisions; parent design.section_revisions;
 input design.authoring_package_inputs; j design.assistant_jobs; a design.proposed_actions;
 b design.authoring_package_action_bindings; o design.assistant_outputs; cmd design.commands;
 consumed design.action_consumptions; link design.assistant_action_links; snapshot design.draft_snapshots;
 m jsonb; expected jsonb; domain_result jsonb; resolution jsonb; before jsonb; old_structure jsonb; new_structure jsonb;
BEGIN
 SELECT * INTO q FROM design.authoring_exact_revisions WHERE section_revision_id=selected_revision;
 SELECT * INTO r FROM design.section_revisions WHERE id=selected_revision;
 SELECT * INTO parent FROM design.section_revisions WHERE id=q.parent_revision_id;
 SELECT * INTO input FROM design.authoring_package_inputs WHERE id=q.input_id;
 SELECT * INTO j FROM design.assistant_jobs WHERE id=q.job_id;
 SELECT * INTO a FROM design.proposed_actions WHERE id=q.action_id;
 SELECT * INTO b FROM design.authoring_package_action_bindings WHERE action_id=q.action_id;
 SELECT * INTO o FROM design.assistant_outputs WHERE job_id=q.job_id;
 SELECT * INTO cmd FROM design.commands WHERE id=q.command_id;
 SELECT * INTO consumed FROM design.action_consumptions WHERE action_id=q.action_id;
 SELECT * INTO link FROM design.assistant_action_links WHERE action_id=q.action_id;
 SELECT * INTO snapshot FROM design.draft_snapshots WHERE draft_id=q.draft_id AND revision=q.draft_revision;
 IF j.id IS NOT NULL THEN PERFORM design.authoring_package_check_job_binding(j.id); END IF;
 m=q.manifest; before=q.before_action;
 IF q.id IS NULL OR r.id IS NULL OR parent.id IS NULL OR input.id IS NULL OR j.id IS NULL OR a.id IS NULL
  OR b.action_id IS NULL OR o.job_id IS NULL OR cmd.id IS NULL OR consumed.action_id IS NULL OR link.action_id IS NULL OR snapshot.id IS NULL
  OR q.bid_id IS DISTINCT FROM r.bid_id OR q.draft_id IS DISTINCT FROM r.draft_id OR q.section_id IS DISTINCT FROM r.section_id
  OR parent.section_id IS DISTINCT FROM r.section_id OR r.revision<>parent.revision+1
  OR parent.id::text IS DISTINCT FROM j.input_manifest#>>'{plan,target,section_revision_id}'
  OR parent.revision::text IS DISTINCT FROM j.input_manifest#>>'{plan,target,base_section_revision}'
  OR parent.digest::text IS DISTINCT FROM j.input_manifest#>>'{plan,target,section_digest}'
  OR parent.content IS DISTINCT FROM j.input_manifest#>'{plan,original_content}'
  OR r.schema_digest IS DISTINCT FROM parent.schema_digest
  OR r.content IS DISTINCT FROM design.authoring_exact_materialized(j.id)
  OR r.digest::text IS DISTINCT FROM design.authoring_package_digest(r.content)
  OR r.created_by IS DISTINCT FROM q.actor_id
  OR q.draft_revision<>(j.input_manifest#>>'{plan,target,base_draft_revision}')::bigint+1
  OR b.job_id IS DISTINCT FROM j.id OR b.input_id IS DISTINCT FROM input.id OR b.bid_id IS DISTINCT FROM q.bid_id
  OR b.input_digest IS DISTINCT FROM input.digest OR b.action_digest IS DISTINCT FROM a.request_digest
  OR b.candidate_digest IS DISTINCT FROM o.digest OR a.request_digest::text IS DISTINCT FROM design.authoring_package_digest(a.payload)
  OR input.bid_id IS DISTINCT FROM q.bid_id OR j.bid_id IS DISTINCT FROM q.bid_id OR a.bid_id IS DISTINCT FROM q.bid_id
  OR j.input_digest::text IS DISTINCT FROM design.authoring_package_digest(j.input_manifest)
  OR NOT EXISTS(SELECT FROM design.assistant_publications p WHERE p.job_id=j.id AND p.action_id=a.id AND p.state='published')
  OR NOT EXISTS(SELECT FROM design.operations op WHERE op.id=j.operation_id AND op.state='succeeded' AND op.cancel_requested_at IS NULL)
  OR NOT EXISTS(SELECT FROM design.assistant_budget_reservations br WHERE br.job_id=j.id AND br.state='settled' AND NOT br.requires_manual_reconciliation)
  OR NOT EXISTS(SELECT FROM design.model_calls mc WHERE mc.id=o.project_call_id AND mc.operation_id=j.operation_id AND mc.state='succeeded' AND mc.response_ref IS NOT NULL)
  OR cmd.actor_id IS DISTINCT FROM q.actor_id OR cmd.command_kind IS DISTINCT FROM 'assistant-action-resolve' OR cmd.target_id IS DISTINCT FROM a.id
  OR cmd.request_digest::text IS DISTINCT FROM design.authoring_package_digest(jsonb_build_object('body',jsonb_build_object('decision','confirm'),'if_match',q.request_condition))
  OR q.request_condition IS DISTINCT FROM '"assistant-action:'||a.id::text||':'||design.authoring_package_digest(before)||'"'
  OR before->>'action_id' IS DISTINCT FROM a.id::text OR before->>'job_id' IS DISTINCT FROM j.id::text
  OR before->>'target_bid_id' IS DISTINCT FROM q.bid_id::text OR before->>'tool' IS DISTINCT FROM 'authoring.apply_patch'
  OR before->>'state' IS DISTINCT FROM 'pending' OR before->'revision' IS DISTINCT FROM '1'::jsonb
  OR before->>'request_digest' IS DISTINCT FROM a.request_digest::text OR before->'base_revision' IS DISTINCT FROM to_jsonb(a.base_revision)
  OR (before->>'expires_at')::timestamptz IS DISTINCT FROM a.expires_at OR before->'result' IS DISTINCT FROM 'null'::jsonb
  OR before#>'{preview,before}' IS DISTINCT FROM parent.content OR before#>'{preview,after}' IS DISTINCT FROM r.content
  OR before#>>'{preview,kind}' IS DISTINCT FROM 'package_authoring_patch'
  OR before#>>'{preview,authoring_input_id}' IS DISTINCT FROM input.id::text OR before#>>'{preview,authoring_input_digest}' IS DISTINCT FROM input.digest::text
  OR before#>>'{preview,section_id}' IS DISTINCT FROM q.section_id::text
  OR before#>>'{preview,base_section_revision}' IS DISTINCT FROM parent.revision::text
  OR consumed.command_id IS DISTINCT FROM cmd.id OR consumed.consumed_by IS DISTINCT FROM q.actor_id
  OR consumed.consumed_at>a.expires_at OR link.resolved_at>a.expires_at OR q.created_at>a.expires_at
  OR link.job_id IS DISTINCT FROM j.id OR link.state IS DISTINCT FROM 'executed' OR link.revision<>2
  OR link.resolved_by IS DISTINCT FROM q.actor_id OR link.tool IS DISTINCT FROM 'authoring.apply_patch' OR link.error_code IS NOT NULL THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_QUALIFICATION_BINDING_INVALID' USING ERRCODE='23514'; END IF;
 expected=jsonb_build_object('protocol','authoring-exact-revision/1','id',q.id,'bid_id',q.bid_id,'draft_id',q.draft_id,
  'draft_revision',q.draft_revision,'section_id',q.section_id,'section_revision_id',r.id,'section_revision',r.revision,
  'section_digest',r.digest,'schema_digest',r.schema_digest,'parent_section_revision_id',parent.id,
  'parent_section_revision',parent.revision,'parent_section_digest',parent.digest,
  'input',jsonb_build_object('id',input.id,'digest',input.digest,'context_digest',input.context_digest),
  'origin',jsonb_build_object('kind','model_candidate_adoption','job_id',j.id,'job_input_digest',j.input_digest,
   'action_id',a.id,'action_digest',a.request_digest,'candidate_digest',o.digest,'command_id',cmd.id,'actor_id',q.actor_id,
   'before_action_digest',design.authoring_package_digest(before)),
  'source_scope','exact_package_context','source_refs_digest',design.authoring_package_digest(r.content#>'{attrs,source_refs}'),
  'rule_ids_digest',design.authoring_package_digest(r.content#>'{attrs,rule_ids}'),'method',m->'method',
  'method_digest',design.authoring_package_digest(m->'method'),'candidate_adopted',true,'content_correctness_certified',false);
 IF m IS DISTINCT FROM expected OR q.digest::text IS DISTINCT FROM design.authoring_package_digest(m)
  OR m#>>'{method,protocol}' IS DISTINCT FROM 'authoring-exact-adoption-policy/1'
  OR m#>>'{method,supported_content}' IS DISTINCT FROM 'plain_text_stable_node'
  OR jsonb_typeof(m#>'{method,source_sha256}') IS DISTINCT FROM 'object' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_QUALIFICATION_MANIFEST_INVALID' USING ERRCODE='23514'; END IF;
 domain_result=jsonb_build_object('draft_id',q.draft_id,'draft_revision',q.draft_revision,'snapshot_id',snapshot.id,'snapshot_digest',snapshot.digest);
 resolution=jsonb_build_object('assistant_resolution',jsonb_build_object('action_id',a.id,'state','executed','tool','authoring.apply_patch',
  'target_bid_id',q.bid_id,'domain_result',domain_result,'error_code',NULL,'http_status',200,'business_effect_executed',true));
 IF consumed.result IS DISTINCT FROM resolution OR cmd.response->'status' IS DISTINCT FROM '200'::jsonb
  OR cmd.response#>'{body,result}' IS DISTINCT FROM resolution OR cmd.response#>>'{body,action_id}' IS DISTINCT FROM a.id::text
  OR cmd.response#>>'{body,job_id}' IS DISTINCT FROM j.id::text OR cmd.response#>>'{body,state}' IS DISTINCT FROM 'executed'
  OR cmd.response#>'{body,revision}' IS DISTINCT FROM '2'::jsonb OR cmd.response#>>'{body,resolved_by}' IS DISTINCT FROM q.actor_id::text
  OR cmd.response#>>'{headers,ETag}' IS DISTINCT FROM '"assistant-action:'||a.id::text||':'||design.authoring_package_digest(cmd.response->'body')||'"'
  OR NOT EXISTS(SELECT FROM design.audit_entries e WHERE e.command_id=cmd.id AND e.actor_id=q.actor_id AND e.bid_id=q.bid_id
    AND e.event_type='authoring.exact_candidate_adopted' AND e.payload=jsonb_build_object('action_id',a.id,
      'qualification_id',q.id,'qualification_digest',q.digest,'section_revision_id',r.id,'snapshot_id',snapshot.id,'snapshot_digest',snapshot.digest)) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_ADOPTION_RECEIPT_INVALID' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT FROM design.draft_snapshot_sections ss WHERE ss.snapshot_id=snapshot.id AND ss.section_revision_id=r.id)
  OR EXISTS(SELECT FROM jsonb_array_elements(j.input_manifest#>'{plan,context,target,sections}') frozen_section
    WHERE frozen_section.value->>'section_id'<>q.section_id::text AND NOT EXISTS(
      SELECT FROM design.draft_snapshot_sections ss WHERE ss.snapshot_id=snapshot.id AND ss.section_revision_id=(frozen_section.value->>'id')::uuid))
  OR (SELECT count(*) FROM design.draft_snapshot_sections WHERE snapshot_id=snapshot.id)<>jsonb_array_length(j.input_manifest#>'{plan,context,target,sections}')
  OR snapshot.manifest->>'title' IS DISTINCT FROM j.input_manifest#>>'{plan,context,target,snapshot_manifest,title}' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_SNAPSHOT_TRANSITION_INVALID' USING ERRCODE='23514'; END IF;
 old_structure=j.input_manifest#>'{plan,context,target,snapshot_manifest,authoring_structure}';
 new_structure=snapshot.manifest->'authoring_structure';
 IF old_structure IS NULL THEN
  IF new_structure IS NOT NULL THEN
   RAISE EXCEPTION 'AUTHORING_EXACT_STRUCTURE_CHANGED' USING ERRCODE='23514'; END IF;
 ELSE
  expected=jsonb_set(old_structure-'id'-'digest','{nodes}',(
   SELECT jsonb_agg(CASE WHEN n.value->>'section_id'=q.section_id::text THEN jsonb_set(n.value,'{section_revision}',to_jsonb(r.revision))
     ELSE n.value END ORDER BY n.ord) FROM jsonb_array_elements(old_structure->'nodes') WITH ORDINALITY n(value,ord)));
  IF new_structure IS NULL OR new_structure-'id'-'digest' IS DISTINCT FROM expected
   OR new_structure->>'digest' IS DISTINCT FROM design.authoring_package_digest(new_structure-'digest')
   OR NOT EXISTS(SELECT FROM design.authoring_structure_versions v WHERE v.id=(new_structure->>'id')::uuid
    AND v.bid_id=q.bid_id AND v.draft_id=q.draft_id AND v.snapshot_id=snapshot.id AND v.draft_revision=q.draft_revision
    AND v.digest::text=new_structure->>'digest') THEN
   RAISE EXCEPTION 'AUTHORING_EXACT_STRUCTURE_CHANGED' USING ERRCODE='23514'; END IF;
 END IF;
 -- Every inherited citation and newly adopted evidence remains bound to this real revision.
 IF EXISTS(SELECT FROM jsonb_array_elements(r.content#>'{attrs,source_refs}') ref WHERE NOT EXISTS(
  SELECT FROM retrieval.citations cite WHERE cite.bid_id=q.bid_id AND cite.target_object_id=r.id AND cite.purpose='authoring'
   AND cite.source_id::text=ref.value->>'source_id' AND cite.source_revision::text=ref.value->>'source_revision'
   AND cite.evidence_id::text=ref.value->>'evidence_id')) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_CITATION_BINDING_INVALID' USING ERRCODE='23514'; END IF;
END $$;

CREATE FUNCTION authoring_exact_assert_revision(selected_revision uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE q design.authoring_exact_revisions;
BEGIN
 PERFORM design.authoring_exact_check_revision(selected_revision);
 SELECT * INTO q FROM design.authoring_exact_revisions WHERE section_revision_id=selected_revision;
 PERFORM design.authoring_exact_assert_dependencies(q.input_id);
END $$;

CREATE FUNCTION authoring_exact_snapshot_proof(snapshot_id uuid) RETURNS jsonb
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE snapshot design.draft_snapshots; section record; bound_sections jsonb='[]'::jsonb; result jsonb;
BEGIN
 SELECT * INTO snapshot FROM design.draft_snapshots s WHERE s.id=snapshot_id;
 IF snapshot.id IS NULL THEN RAISE EXCEPTION 'AUTHORING_EXACT_SNAPSHOT_NOT_FOUND' USING ERRCODE='23514'; END IF;
 FOR section IN SELECT q.*,r.revision,r.digest AS content_digest FROM design.draft_snapshot_sections ss
  JOIN design.section_revisions r ON r.id=ss.section_revision_id AND r.bid_id=ss.bid_id
  JOIN design.authoring_exact_revisions q ON q.section_revision_id=r.id AND q.bid_id=r.bid_id
  WHERE ss.snapshot_id=snapshot.id ORDER BY ss.ordinal LOOP
  PERFORM design.authoring_exact_check_revision(section.section_revision_id);
  bound_sections=bound_sections||jsonb_build_array(jsonb_build_object('section_id',section.section_id,'section_revision_id',section.section_revision_id,
   'section_revision',section.revision,'section_digest',section.content_digest,'qualification_id',section.id,'qualification_digest',section.digest,
   'authoring_input_id',section.input_id,'authoring_input_digest',section.manifest#>'{input,digest}','source_scope','exact_package_context'));
 END LOOP;
 IF jsonb_array_length(bound_sections)=0 THEN
  IF snapshot.manifest ? 'authoring_exact_sections' OR EXISTS(SELECT FROM design.authoring_exact_revisions q
    WHERE q.draft_id=snapshot.draft_id AND q.draft_revision<=snapshot.revision) THEN
   RAISE EXCEPTION 'AUTHORING_EXACT_QUALIFICATION_MISSING' USING ERRCODE='23514'; END IF;
  RETURN NULL;
 END IF;
 result=jsonb_build_object('protocol','authoring-exact-snapshot/1','sections',bound_sections);
 result=result||jsonb_build_object('digest',design.authoring_package_digest(result));
 IF snapshot.digest::text IS DISTINCT FROM design.authoring_package_digest(snapshot.manifest)
  OR snapshot.manifest->'authoring_exact_sections' IS DISTINCT FROM result THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_SNAPSHOT_CORRUPT' USING ERRCODE='23514'; END IF;
 RETURN result;
END $$;

CREATE FUNCTION authoring_exact_commit_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE checked_revision uuid; q design.authoring_exact_revisions; snapshot uuid; action uuid; resolution_state text;
BEGIN
 IF TG_TABLE_NAME='authoring_exact_revisions' THEN
  checked_revision=NEW.section_revision_id;
 ELSIF TG_TABLE_NAME IN('action_consumptions','assistant_action_links') THEN
  action=NEW.action_id;
  IF NOT EXISTS(SELECT FROM design.authoring_package_action_bindings b WHERE b.action_id=action) THEN RETURN NEW; END IF;
  IF TG_TABLE_NAME='assistant_action_links' THEN resolution_state=NEW.state;
  ELSE resolution_state=coalesce(NEW.result#>>'{assistant_resolution,state}','executed'); END IF;
  IF resolution_state<>'executed' THEN
   IF EXISTS(SELECT FROM design.authoring_exact_revisions WHERE action_id=action) THEN
    RAISE EXCEPTION 'AUTHORING_EXACT_ACTION_STATE_INVALID' USING ERRCODE='23514'; END IF;
   RETURN NEW;
  END IF;
  SELECT section_revision_id INTO checked_revision FROM design.authoring_exact_revisions WHERE action_id=action;
 ELSIF TG_TABLE_NAME='section_revisions' THEN
  IF NOT EXISTS(SELECT FROM design.authoring_exact_revisions WHERE draft_id=NEW.draft_id) THEN RETURN NEW; END IF;
  checked_revision=NEW.id;
 ELSIF TG_TABLE_NAME='sections' THEN
  IF NEW.head_revision=OLD.head_revision OR NOT EXISTS(SELECT FROM design.authoring_exact_revisions WHERE draft_id=NEW.draft_id) THEN RETURN NEW; END IF;
  SELECT r.id INTO checked_revision FROM design.section_revisions r WHERE r.section_id=NEW.id AND r.revision=NEW.head_revision;
  IF NOT EXISTS(SELECT FROM design.authoring_exact_revisions qual JOIN design.section_revisions p ON p.id=qual.parent_revision_id
   WHERE qual.section_revision_id=checked_revision AND p.revision=OLD.head_revision) THEN
   RAISE EXCEPTION 'AUTHORING_EXACT_REVISION_OPERATION_UNSUPPORTED' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='drafts' THEN
  IF NEW.revision=OLD.revision OR NOT EXISTS(SELECT FROM design.authoring_exact_revisions WHERE draft_id=NEW.id) THEN RETURN NEW; END IF;
  SELECT section_revision_id INTO checked_revision FROM design.authoring_exact_revisions WHERE draft_id=NEW.id AND draft_revision=NEW.revision;
  IF checked_revision IS NULL OR NEW.revision<>OLD.revision+1 THEN
   RAISE EXCEPTION 'AUTHORING_EXACT_REVISION_OPERATION_UNSUPPORTED' USING ERRCODE='23514'; END IF;
 ELSE
  IF TG_TABLE_NAME='draft_snapshots' THEN snapshot=NEW.id; ELSE snapshot=NEW.snapshot_id; END IF;
  PERFORM design.authoring_exact_snapshot_proof(snapshot);
  RETURN NEW;
 END IF;
 SELECT * INTO q FROM design.authoring_exact_revisions WHERE section_revision_id=checked_revision;
 IF q.id IS NULL THEN RAISE EXCEPTION 'AUTHORING_EXACT_REVISION_OPERATION_UNSUPPORTED' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT FROM design.drafts d WHERE d.id=q.draft_id AND d.bid_id=q.bid_id AND d.revision=q.draft_revision)
  OR EXISTS(SELECT FROM jsonb_array_elements((SELECT j.input_manifest#>'{plan,context,target,sections}' FROM design.assistant_jobs j WHERE j.id=q.job_id)) frozen_section
    LEFT JOIN design.sections s ON s.id=(frozen_section.value->>'section_id')::uuid AND s.draft_id=q.draft_id AND s.bid_id=q.bid_id
    WHERE s.id IS NULL OR s.head_revision IS DISTINCT FROM CASE WHEN s.id=q.section_id THEN (frozen_section.value->>'revision')::bigint+1
      ELSE (frozen_section.value->>'revision')::bigint END) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TARGET_TRANSITION_INVALID' USING ERRCODE='23514'; END IF;
 PERFORM design.authoring_exact_assert_revision(checked_revision);
 IF clock_timestamp()> (SELECT expires_at FROM design.proposed_actions WHERE id=q.action_id) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_ACTION_EXPIRED' USING ERRCODE='23514'; END IF;
 SELECT s.id INTO snapshot FROM design.draft_snapshots s WHERE s.draft_id=q.draft_id AND s.revision=q.draft_revision;
 PERFORM design.authoring_exact_snapshot_proof(snapshot);
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER authoring_exact_qualification_complete AFTER INSERT ON authoring_exact_revisions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_exact_commit_guard();
CREATE CONSTRAINT TRIGGER authoring_exact_section_complete AFTER INSERT ON section_revisions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_exact_commit_guard();
CREATE CONSTRAINT TRIGGER authoring_exact_section_head_complete AFTER UPDATE ON sections
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_exact_commit_guard();
CREATE CONSTRAINT TRIGGER authoring_exact_draft_complete AFTER UPDATE ON drafts
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_exact_commit_guard();
CREATE CONSTRAINT TRIGGER authoring_exact_snapshot_complete AFTER INSERT ON draft_snapshots
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_exact_commit_guard();
CREATE CONSTRAINT TRIGGER authoring_exact_snapshot_section_complete AFTER INSERT ON draft_snapshot_sections
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_exact_commit_guard();
CREATE CONSTRAINT TRIGGER authoring_exact_consumption_complete AFTER INSERT ON action_consumptions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_exact_commit_guard();
CREATE CONSTRAINT TRIGGER authoring_exact_action_resolution_complete AFTER UPDATE ON assistant_action_links
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_exact_commit_guard();

CREATE FUNCTION authoring_exact_command_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
BEGIN
 IF OLD.command_kind='assistant-action-resolve' AND EXISTS(SELECT FROM design.authoring_package_action_bindings WHERE action_id=OLD.target_id) THEN
  IF TG_OP='DELETE' OR (OLD.response IS NOT NULL AND NEW IS DISTINCT FROM OLD)
   OR NEW.id IS DISTINCT FROM OLD.id OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
   OR NEW.command_kind IS DISTINCT FROM OLD.command_kind OR NEW.target_id IS DISTINCT FROM OLD.target_id
   OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key OR NEW.request_digest IS DISTINCT FROM OLD.request_digest THEN
   RAISE EXCEPTION 'AUTHORING_EXACT_COMMAND_IMMUTABLE' USING ERRCODE='55000'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER authoring_exact_command_immutable BEFORE UPDATE OR DELETE ON commands
 FOR EACH ROW EXECUTE FUNCTION authoring_exact_command_guard();

REVOKE ALL ON authoring_exact_revisions FROM PUBLIC,tender_api,tender_worker;
GRANT SELECT,INSERT ON authoring_exact_revisions TO tender_api;
REVOKE ALL ON FUNCTION authoring_exact_replace(jsonb,text,text),authoring_exact_materialized(uuid),authoring_exact_assert_dependencies(uuid),
 authoring_exact_check_revision(uuid),authoring_exact_assert_revision(uuid),authoring_exact_snapshot_proof(uuid),authoring_exact_commit_guard(),authoring_exact_command_guard()
 FROM PUBLIC,tender_api,tender_worker;
GRANT EXECUTE ON FUNCTION authoring_exact_check_revision(uuid),authoring_exact_assert_revision(uuid),authoring_exact_snapshot_proof(uuid) TO tender_api;
-- Worker can obtain only revision identities/digests of a real immutable snapshot, never B1 facts or the qualification table.
GRANT EXECUTE ON FUNCTION authoring_exact_snapshot_proof(uuid) TO tender_worker;
COMMIT;
