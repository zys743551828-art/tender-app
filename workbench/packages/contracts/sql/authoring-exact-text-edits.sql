-- Optional B5: explicit, single-node human text changes retaining exact provenance.
-- Install only after B1/B2/B3/B4 in an independently verified environment.
-- Existing candidate tables and immutable historical manifests are unchanged.
BEGIN;
SET LOCAL search_path=design,public;

CREATE TABLE authoring_exact_manual_revisions(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL,
 draft_id uuid NOT NULL,
 section_id uuid NOT NULL,
 section_revision_id uuid NOT NULL UNIQUE,
 parent_revision_id uuid NOT NULL,
 parent_qualification_id uuid NOT NULL,
 root_qualification_id uuid NOT NULL REFERENCES authoring_exact_revisions(id),
 input_id uuid NOT NULL REFERENCES authoring_package_inputs(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 actor_id uuid NOT NULL REFERENCES members(id),
 draft_revision bigint NOT NULL CHECK(draft_revision>2),
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
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON authoring_exact_manual_revisions
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE VIEW authoring_exact_revision_records AS
 SELECT id,bid_id,draft_id,section_id,section_revision_id,parent_revision_id,input_id,job_id,
 action_id,command_id,actor_id,draft_revision,manifest,digest,before_action,request_condition,created_at
 FROM design.authoring_exact_revisions
 UNION ALL
 SELECT m.id,m.bid_id,m.draft_id,m.section_id,m.section_revision_id,m.parent_revision_id,m.input_id,r.job_id,
 NULL::uuid,m.command_id,m.actor_id,m.draft_revision,m.manifest,m.digest,m.before_action,m.request_condition,m.created_at
 FROM design.authoring_exact_manual_revisions m JOIN design.authoring_exact_revisions r ON r.id=m.root_qualification_id;

-- Preserve the exact B3 validator as its own private core. Its historical checks
-- still run for every model-candidate root; manual edits never impersonate it.
ALTER FUNCTION authoring_exact_check_revision(uuid) RENAME TO authoring_exact_check_candidate_revision;

CREATE FUNCTION authoring_exact_check_manual_record(selected_revision uuid) RETURNS void
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE q design.authoring_exact_manual_revisions; parentq record; rootq design.authoring_exact_revisions;
 r design.section_revisions; parent design.section_revisions; cmd design.commands;
 snapshot design.draft_snapshots; previous design.draft_snapshots;
 m jsonb; request jsonb; original_node jsonb; node_count bigint; expected jsonb; expected_result jsonb;
 old_structure jsonb; new_structure jsonb; replacement text;
BEGIN
 SELECT * INTO q FROM design.authoring_exact_manual_revisions WHERE section_revision_id=selected_revision;
 SELECT * INTO parentq FROM design.authoring_exact_revision_records WHERE id=q.parent_qualification_id;
 SELECT * INTO rootq FROM design.authoring_exact_revisions WHERE id=q.root_qualification_id;
 SELECT * INTO r FROM design.section_revisions WHERE id=q.section_revision_id;
 SELECT * INTO parent FROM design.section_revisions WHERE id=q.parent_revision_id;
 SELECT * INTO cmd FROM design.commands WHERE id=q.command_id;
 SELECT * INTO snapshot FROM design.draft_snapshots WHERE draft_id=q.draft_id AND revision=q.draft_revision;
 SELECT * INTO previous FROM design.draft_snapshots WHERE draft_id=q.draft_id AND revision=q.draft_revision-1;
 m=q.manifest; request=q.before_action->'request'; replacement=request->>'replacement_text';
 IF q.id IS NULL OR parentq.id IS NULL OR rootq.id IS NULL OR r.id IS NULL OR parent.id IS NULL
  OR cmd.id IS NULL OR snapshot.id IS NULL OR previous.id IS NULL
  OR q.bid_id IS DISTINCT FROM r.bid_id OR q.draft_id IS DISTINCT FROM r.draft_id OR q.section_id IS DISTINCT FROM r.section_id
  OR q.bid_id IS DISTINCT FROM rootq.bid_id OR q.draft_id IS DISTINCT FROM rootq.draft_id OR q.section_id IS DISTINCT FROM rootq.section_id
  OR q.bid_id IS DISTINCT FROM parentq.bid_id OR q.draft_id IS DISTINCT FROM parentq.draft_id OR q.section_id IS DISTINCT FROM parentq.section_id
  OR parentq.section_revision_id IS DISTINCT FROM parent.id OR parent.section_id IS DISTINCT FROM r.section_id
  OR parent.bid_id IS DISTINCT FROM r.bid_id OR parent.draft_id IS DISTINCT FROM r.draft_id
  OR r.revision IS DISTINCT FROM parent.revision+1 OR r.schema_digest IS DISTINCT FROM parent.schema_digest
  OR q.input_id IS DISTINCT FROM rootq.input_id OR parentq.input_id IS DISTINCT FROM q.input_id
  OR r.digest::text IS DISTINCT FROM design.authoring_package_digest(r.content) OR r.created_by IS DISTINCT FROM q.actor_id
  OR q.parent_qualification_id=q.id OR parentq.draft_revision>=q.draft_revision
  OR q.root_qualification_id IS DISTINCT FROM (CASE WHEN parentq.manifest->>'protocol'='authoring-exact-revision/1'
      THEN parentq.id ELSE (parentq.manifest#>>'{origin,root_qualification_id}')::uuid END)
  OR EXISTS(SELECT FROM design.authoring_exact_revisions other WHERE other.id=q.id OR other.section_revision_id=q.section_revision_id
      OR (other.draft_id=q.draft_id AND other.draft_revision=q.draft_revision))
  OR jsonb_typeof(request) IS DISTINCT FROM 'object'
  OR NOT (request ?& ARRAY['base_draft_revision','section_revision_id','node_id','before_node_digest','replacement_text','reason'])
  OR request-ARRAY['base_draft_revision','section_revision_id','node_id','before_node_digest','replacement_text','reason'] <> '{}'::jsonb
  OR request->'base_draft_revision' IS DISTINCT FROM to_jsonb(q.draft_revision-1)
  OR request->>'section_revision_id' IS DISTINCT FROM parent.id::text
  OR jsonb_typeof(request->'node_id') IS DISTINCT FROM 'string' OR length(request->>'node_id') NOT BETWEEN 1 AND 128
  OR jsonb_typeof(request->'replacement_text') IS DISTINCT FROM 'string' OR length(replacement)>20000
  OR regexp_replace(replacement,E'[\n\t]','','g') ~ '[[:cntrl:]]'
  OR jsonb_typeof(request->'reason') IS DISTINCT FROM 'string' OR length(request->>'reason') NOT BETWEEN 1 AND 1000
  OR NOT ((request->>'reason') ~ '[^[:space:]]') OR regexp_replace(request->>'reason',E'[\n\t]','','g') ~ '[[:cntrl:]]'
  OR q.before_action IS DISTINCT FROM jsonb_build_object('request',request,'base_snapshot_id',previous.id,'base_snapshot_digest',previous.digest)
  OR previous.digest::text IS DISTINCT FROM design.authoring_package_digest(previous.manifest)
  OR cmd.actor_id IS DISTINCT FROM q.actor_id OR cmd.command_kind IS DISTINCT FROM 'authoring-exact-text-edit'
  OR cmd.target_id IS DISTINCT FROM q.draft_id
  OR cmd.request_digest::text IS DISTINCT FROM design.authoring_package_digest(jsonb_build_object('body',request,'if_match',q.request_condition))
  OR q.request_condition IS DISTINCT FROM '"draft:'||q.draft_id::text||':'||(q.draft_revision-1)::text||'"' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_BINDING_INVALID' USING ERRCODE='23514'; END IF;
 WITH RECURSIVE nodes(value) AS (
   SELECT parent.content UNION ALL SELECT child FROM nodes n CROSS JOIN LATERAL jsonb_array_elements(coalesce(n.value->'content','[]'::jsonb)) child
 ) SELECT count(*),jsonb_agg(value)->0 INTO node_count,original_node FROM nodes WHERE value#>>'{attrs,id}'=request->>'node_id';
 IF node_count<>1 OR original_node->>'type' NOT IN('paragraph','heading')
  OR design.authoring_package_digest(original_node) IS DISTINCT FROM request->>'before_node_digest'
  OR EXISTS(SELECT FROM jsonb_array_elements(original_node->'content') child
    WHERE child->>'type' IS DISTINCT FROM 'text' OR coalesce(child->'marks','[]'::jsonb)<>'[]'::jsonb)
  OR r.content IS DISTINCT FROM design.authoring_exact_replace(parent.content,request->>'node_id',replacement)
  OR r.content=parent.content OR r.content->'attrs' IS DISTINCT FROM parent.content->'attrs' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_CONTENT_INVALID' USING ERRCODE='23514'; END IF;
 expected=jsonb_build_object('protocol','authoring-exact-manual-revision/1','id',q.id,'bid_id',q.bid_id,'draft_id',q.draft_id,
  'draft_revision',q.draft_revision,'section_id',q.section_id,'section_revision_id',r.id,'section_revision',r.revision,
  'section_digest',r.digest,'schema_digest',r.schema_digest,'parent_section_revision_id',parent.id,
  'parent_section_revision',parent.revision,'parent_section_digest',parent.digest,'input',rootq.manifest->'input',
  'origin',jsonb_build_object('kind','manual_text_edit','parent_qualification_id',parentq.id,'parent_qualification_digest',parentq.digest,
   'root_qualification_id',rootq.id,'root_qualification_digest',rootq.digest,'command_id',cmd.id,'actor_id',q.actor_id,
   'before_action_digest',design.authoring_package_digest(q.before_action),'node_id',request->'node_id',
   'before_node_digest',request->'before_node_digest','replacement_text_digest',encode(sha256(convert_to(replacement,'UTF8')),'hex'),
   'reason',request->'reason'),
  'source_scope','exact_package_context','source_refs_digest',design.authoring_package_digest(r.content#>'{attrs,source_refs}'),
  'rule_ids_digest',design.authoring_package_digest(r.content#>'{attrs,rule_ids}'),'method',m->'method',
  'method_digest',design.authoring_package_digest(m->'method'),'candidate_adopted',false,'content_correctness_certified',false);
 IF m IS DISTINCT FROM expected OR q.digest::text IS DISTINCT FROM design.authoring_package_digest(m)
  OR m#>>'{method,protocol}' IS DISTINCT FROM 'authoring-exact-text-edit-policy/1'
  OR m#>>'{method,supported_content}' IS DISTINCT FROM 'plain_text_stable_node'
  OR jsonb_typeof(m#>'{method,source_sha256}') IS DISTINCT FROM 'object' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_MANIFEST_INVALID' USING ERRCODE='23514'; END IF;
 expected_result=jsonb_build_object('protocol','authoring-exact-text-edit-result/1','bid_id',q.bid_id,
  'draft_id',q.draft_id,'draft_revision',q.draft_revision,'snapshot_id',snapshot.id,'snapshot_digest',snapshot.digest,
  'parent_section_revision_id',parent.id,'section_revision_id',r.id,'section_digest',r.digest,
  'qualification',jsonb_build_object('manifest',m,'digest',q.digest));
 IF cmd.response IS DISTINCT FROM jsonb_build_object('body',expected_result,'status',200,
    'headers',jsonb_build_object('ETag','"draft:'||q.draft_id::text||':'||q.draft_revision::text||'"'))
  OR NOT EXISTS(SELECT FROM design.audit_entries e WHERE e.command_id=cmd.id AND e.actor_id=q.actor_id AND e.bid_id=q.bid_id
    AND e.event_type='authoring.exact_text_edited' AND e.payload=jsonb_build_object('qualification_id',q.id,
     'qualification_digest',q.digest,'section_revision_id',r.id,'snapshot_id',snapshot.id,'snapshot_digest',snapshot.digest)) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_RECEIPT_INVALID' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT FROM design.draft_snapshot_sections WHERE snapshot_id=previous.id AND section_revision_id=parent.id)
  OR NOT EXISTS(SELECT FROM design.draft_snapshot_sections WHERE snapshot_id=snapshot.id AND section_revision_id=r.id)
  OR EXISTS(SELECT FROM design.draft_snapshot_sections old WHERE old.snapshot_id=previous.id AND old.section_revision_id<>parent.id
    AND NOT EXISTS(SELECT FROM design.draft_snapshot_sections cur WHERE cur.snapshot_id=snapshot.id
      AND cur.section_revision_id=old.section_revision_id AND cur.ordinal=old.ordinal))
  OR (SELECT count(*) FROM design.draft_snapshot_sections WHERE snapshot_id=previous.id)
    <> (SELECT count(*) FROM design.draft_snapshot_sections WHERE snapshot_id=snapshot.id)
  OR snapshot.manifest->'title' IS DISTINCT FROM previous.manifest->'title' THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_SNAPSHOT_INVALID' USING ERRCODE='23514'; END IF;
 old_structure=previous.manifest->'authoring_structure'; new_structure=snapshot.manifest->'authoring_structure';
 IF old_structure IS NULL THEN
  IF new_structure IS NOT NULL THEN RAISE EXCEPTION 'AUTHORING_EXACT_STRUCTURE_CHANGED' USING ERRCODE='23514'; END IF;
 ELSE
  expected=jsonb_set(old_structure-'id'-'digest','{nodes}',(
   SELECT jsonb_agg(CASE WHEN n.value->>'section_id'=q.section_id::text THEN jsonb_set(n.value,'{section_revision}',to_jsonb(r.revision))
    ELSE n.value END ORDER BY n.ord) FROM jsonb_array_elements(old_structure->'nodes') WITH ORDINALITY n(value,ord)));
  IF new_structure IS NULL OR new_structure-'id'-'digest' IS DISTINCT FROM expected
   OR new_structure->>'digest' IS DISTINCT FROM design.authoring_package_digest(new_structure-'digest')
   OR NOT EXISTS(SELECT FROM design.authoring_structure_versions v WHERE v.id=(new_structure->>'id')::uuid AND v.bid_id=q.bid_id
    AND v.draft_id=q.draft_id AND v.snapshot_id=snapshot.id AND v.draft_revision=q.draft_revision AND v.digest::text=new_structure->>'digest') THEN
   RAISE EXCEPTION 'AUTHORING_EXACT_STRUCTURE_CHANGED' USING ERRCODE='23514'; END IF;
 END IF;
 IF EXISTS(SELECT FROM jsonb_array_elements(r.content#>'{attrs,source_refs}') ref WHERE NOT EXISTS(
  SELECT FROM retrieval.citations cite WHERE cite.bid_id=q.bid_id AND cite.target_object_id=r.id AND cite.purpose='authoring'
   AND cite.source_id::text=ref.value->>'source_id' AND cite.source_revision::text=ref.value->>'source_revision'
   AND cite.evidence_id::text=ref.value->>'evidence_id')) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_CITATION_BINDING_INVALID' USING ERRCODE='23514'; END IF;
END $$;

CREATE FUNCTION authoring_exact_check_manual_revision(selected_revision uuid) RETURNS void
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE item design.authoring_exact_manual_revisions; selected uuid=selected_revision;
 visited uuid[]='{}'::uuid[]; root_id uuid;
BEGIN
 LOOP
  SELECT * INTO item FROM design.authoring_exact_manual_revisions WHERE section_revision_id=selected;
  IF item.id IS NULL THEN
   IF root_id IS NULL OR NOT EXISTS(SELECT FROM design.authoring_exact_revisions WHERE id=root_id AND section_revision_id=selected) THEN
    RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_ROOT_INVALID' USING ERRCODE='23514'; END IF;
   PERFORM design.authoring_exact_check_candidate_revision(selected);
   RETURN;
  END IF;
  IF item.id=ANY(visited) OR cardinality(visited)>=128 OR (root_id IS NOT NULL AND item.root_qualification_id<>root_id) THEN
   RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_LINEAGE_INVALID' USING ERRCODE='23514'; END IF;
  visited=array_append(visited,item.id); root_id=item.root_qualification_id;
  PERFORM design.authoring_exact_check_manual_record(selected);
  selected=item.parent_revision_id;
 END LOOP;
END $$;

CREATE FUNCTION authoring_exact_check_revision(selected_revision uuid) RETURNS void
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
BEGIN
 IF EXISTS(SELECT FROM design.authoring_exact_manual_revisions WHERE section_revision_id=selected_revision) THEN
  PERFORM design.authoring_exact_check_manual_revision(selected_revision);
 ELSE
  PERFORM design.authoring_exact_check_candidate_revision(selected_revision);
 END IF;
END $$;

CREATE FUNCTION authoring_exact_manual_transition(selected_revision uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE q design.authoring_exact_manual_revisions; previous design.draft_snapshots; snapshot uuid;
BEGIN
 SELECT * INTO q FROM design.authoring_exact_manual_revisions WHERE section_revision_id=selected_revision;
 SELECT * INTO previous FROM design.draft_snapshots WHERE draft_id=q.draft_id AND revision=q.draft_revision-1;
 IF q.id IS NULL OR previous.id IS NULL
  OR NOT EXISTS(SELECT FROM design.drafts d WHERE d.id=q.draft_id AND d.bid_id=q.bid_id AND d.revision=q.draft_revision)
  OR EXISTS(SELECT FROM design.draft_snapshot_sections ss JOIN design.section_revisions r ON r.id=ss.section_revision_id
    LEFT JOIN design.sections s ON s.id=r.section_id AND s.draft_id=q.draft_id AND s.bid_id=q.bid_id
    WHERE ss.snapshot_id=previous.id AND (s.id IS NULL OR s.head_revision IS DISTINCT FROM
     CASE WHEN r.id=q.parent_revision_id THEN r.revision+1 ELSE r.revision END)) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_TEXT_EDIT_TRANSITION_INVALID' USING ERRCODE='23514'; END IF;
 PERFORM design.authoring_exact_assert_revision(selected_revision);
 SELECT s.id INTO snapshot FROM design.draft_snapshots s WHERE s.draft_id=q.draft_id AND s.revision=q.draft_revision;
 PERFORM design.authoring_exact_snapshot_proof(snapshot);
END $$;

CREATE OR REPLACE FUNCTION authoring_exact_assert_revision(selected_revision uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE q record;
BEGIN
 PERFORM design.authoring_exact_check_revision(selected_revision);
 SELECT * INTO q FROM design.authoring_exact_revision_records WHERE section_revision_id=selected_revision;
 PERFORM design.authoring_exact_assert_dependencies(q.input_id);
END $$;

CREATE OR REPLACE FUNCTION authoring_exact_snapshot_proof(snapshot_id uuid) RETURNS jsonb
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE snapshot design.draft_snapshots; section record; bound_sections jsonb='[]'::jsonb; result jsonb;
BEGIN
 SELECT * INTO snapshot FROM design.draft_snapshots s WHERE s.id=snapshot_id;
 IF snapshot.id IS NULL THEN RAISE EXCEPTION 'AUTHORING_EXACT_SNAPSHOT_NOT_FOUND' USING ERRCODE='23514'; END IF;
 FOR section IN SELECT q.*,r.revision,r.digest AS content_digest FROM design.draft_snapshot_sections ss
  JOIN design.section_revisions r ON r.id=ss.section_revision_id AND r.bid_id=ss.bid_id
  JOIN design.authoring_exact_revision_records q ON q.section_revision_id=r.id AND q.bid_id=r.bid_id
  WHERE ss.snapshot_id=snapshot.id ORDER BY ss.ordinal LOOP
  PERFORM design.authoring_exact_check_revision(section.section_revision_id);
  bound_sections=bound_sections||jsonb_build_array(jsonb_build_object('section_id',section.section_id,'section_revision_id',section.section_revision_id,
   'section_revision',section.revision,'section_digest',section.content_digest,'qualification_id',section.id,'qualification_digest',section.digest,
   'authoring_input_id',section.input_id,'authoring_input_digest',section.manifest#>'{input,digest}','source_scope','exact_package_context'));
 END LOOP;
 IF jsonb_array_length(bound_sections)=0 THEN
  IF snapshot.manifest ? 'authoring_exact_sections' OR EXISTS(SELECT FROM design.authoring_exact_revision_records q
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

CREATE OR REPLACE FUNCTION authoring_exact_build_packet(selected_snapshot uuid) RETURNS jsonb
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE snapshot design.draft_snapshots; exact jsonb; original_documents jsonb; inputs uuid[];
 dependencies jsonb; source_ids jsonb; section_digests jsonb; section_revisions jsonb; proof jsonb;
BEGIN
 SELECT * INTO snapshot FROM design.draft_snapshots WHERE id=selected_snapshot;
 exact=design.authoring_exact_snapshot_proof(selected_snapshot);
 IF exact IS NULL THEN RETURN NULL; END IF;
 -- Bind the exact revisions to a real B3 output snapshot. Legacy sections in
 -- this snapshot retain their ordinary source guards in the build service.
 IF NOT EXISTS(SELECT FROM design.authoring_exact_revision_records q WHERE q.bid_id=snapshot.bid_id
   AND q.draft_id=snapshot.draft_id AND q.draft_revision=snapshot.revision
   AND EXISTS(SELECT FROM design.draft_snapshot_sections ss WHERE ss.snapshot_id=snapshot.id AND ss.section_revision_id=q.section_revision_id)) THEN
  RAISE EXCEPTION 'AUTHORING_EXACT_BUILD_SNAPSHOT_UNQUALIFIED' USING ERRCODE='23514'; END IF;
 SELECT array_agg(DISTINCT (value->>'authoring_input_id')::uuid ORDER BY (value->>'authoring_input_id')::uuid)
  INTO inputs FROM jsonb_array_elements(exact->'sections');
 SELECT jsonb_agg(jsonb_build_object('id',i.id,'digest',i.digest,'context_digest',i.context_digest,
   'dependency_digest',design.authoring_exact_build_dependencies(i.id)) ORDER BY i.id)
  INTO dependencies FROM design.authoring_package_inputs i WHERE i.id=ANY(inputs) AND i.bid_id=snapshot.bid_id;
 SELECT jsonb_agg(value ORDER BY value->>'document_version_id',value->>'object_key') INTO original_documents
  FROM (SELECT DISTINCT jsonb_build_object('document_version_id',doc.value->'document_version_id',
     'digest',doc.value->'digest','byte_size',doc.value->'byte_size','object_key',doc.value->'object_key') AS value
   FROM design.authoring_package_inputs i CROSS JOIN LATERAL jsonb_array_elements(i.context_text::jsonb->'documents') doc
   WHERE i.id=ANY(inputs) AND i.bid_id=snapshot.bid_id) originals;
 SELECT jsonb_agg(source_id ORDER BY source_id) INTO source_ids FROM (
  SELECT DISTINCT source.value->>'source_id' AS source_id FROM design.authoring_package_inputs i
  CROSS JOIN LATERAL jsonb_array_elements(i.context_text::jsonb->'sources') source WHERE i.id=ANY(inputs) AND i.bid_id=snapshot.bid_id) ids;
 SELECT jsonb_agg(r.digest ORDER BY ss.ordinal),
  jsonb_agg(jsonb_build_object('section_revision_id',r.id,'section_id',r.section_id,'digest',r.digest) ORDER BY ss.ordinal)
  INTO section_digests,section_revisions FROM design.draft_snapshot_sections ss
  JOIN design.section_revisions r ON r.id=ss.section_revision_id AND r.bid_id=ss.bid_id
  WHERE ss.snapshot_id=snapshot.id AND ss.bid_id=snapshot.bid_id;
 proof=jsonb_build_object('protocol','authoring-exact-build/1','bid_id',snapshot.bid_id,'snapshot_id',snapshot.id,
  'snapshot_digest',snapshot.digest,'exact_sections_digest',exact->'digest','section_digests',section_digests,'section_revisions',section_revisions,
  'input_identities',dependencies,'direct_source_ids',source_ids,'originals_digest',design.authoring_package_digest(original_documents));
 proof=proof||jsonb_build_object('digest',design.authoring_package_digest(proof));
 RETURN jsonb_build_object('proof',proof,'originals',original_documents);
END $$;

CREATE OR REPLACE FUNCTION authoring_exact_commit_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
DECLARE checked_revision uuid; q design.authoring_exact_revisions; snapshot uuid; action uuid; resolution_state text;
BEGIN

 -- An actual immutable manual record selects this branch; no caller mode flag.
 IF TG_TABLE_NAME='authoring_exact_manual_revisions' THEN checked_revision=NEW.section_revision_id;
 ELSIF TG_TABLE_NAME='section_revisions' THEN
  SELECT section_revision_id INTO checked_revision FROM design.authoring_exact_manual_revisions WHERE section_revision_id=NEW.id;
 ELSIF TG_TABLE_NAME='sections' THEN
  IF NEW.head_revision IS DISTINCT FROM OLD.head_revision THEN
   SELECT m.section_revision_id INTO checked_revision FROM design.authoring_exact_manual_revisions m
    JOIN design.section_revisions r ON r.id=m.section_revision_id JOIN design.section_revisions p ON p.id=m.parent_revision_id
    WHERE m.section_id=NEW.id AND r.revision=NEW.head_revision AND p.revision=OLD.head_revision;
  END IF;
 ELSIF TG_TABLE_NAME='drafts' THEN
  IF NEW.revision IS DISTINCT FROM OLD.revision AND NEW.revision=OLD.revision+1 THEN
   SELECT section_revision_id INTO checked_revision FROM design.authoring_exact_manual_revisions WHERE draft_id=NEW.id AND draft_revision=NEW.revision;
  END IF;
 END IF;
 IF checked_revision IS NOT NULL THEN
  PERFORM design.authoring_exact_manual_transition(checked_revision);
  RETURN NEW;
 END IF;
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

CREATE CONSTRAINT TRIGGER authoring_exact_manual_revision_complete AFTER INSERT ON authoring_exact_manual_revisions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_exact_commit_guard();

CREATE FUNCTION authoring_exact_manual_command_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design AS $$
BEGIN
 IF OLD.command_kind='authoring-exact-text-edit' THEN
  IF TG_OP='DELETE' OR (OLD.response IS NOT NULL AND NEW IS DISTINCT FROM OLD)
   OR NEW.id IS DISTINCT FROM OLD.id OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
   OR NEW.command_kind IS DISTINCT FROM OLD.command_kind OR NEW.target_id IS DISTINCT FROM OLD.target_id
   OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key OR NEW.request_digest IS DISTINCT FROM OLD.request_digest THEN
   RAISE EXCEPTION 'AUTHORING_EXACT_COMMAND_IMMUTABLE' USING ERRCODE='55000'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER authoring_exact_manual_command_immutable BEFORE UPDATE OR DELETE ON commands
 FOR EACH ROW EXECUTE FUNCTION authoring_exact_manual_command_guard();

REVOKE ALL ON authoring_exact_manual_revisions,authoring_exact_revision_records FROM PUBLIC,tender_api,tender_worker;
GRANT SELECT,INSERT ON authoring_exact_manual_revisions TO tender_api;
GRANT SELECT ON authoring_exact_revision_records TO tender_api;
REVOKE ALL ON FUNCTION authoring_exact_check_candidate_revision(uuid),authoring_exact_check_manual_record(uuid),
 authoring_exact_check_manual_revision(uuid),authoring_exact_check_revision(uuid),authoring_exact_manual_transition(uuid),
 authoring_exact_manual_command_guard() FROM PUBLIC,tender_api,tender_worker;
GRANT EXECUTE ON FUNCTION authoring_exact_check_revision(uuid) TO tender_api;
-- Existing B3/B4 narrow snapshot and build RPC grants remain unchanged.
COMMIT;
