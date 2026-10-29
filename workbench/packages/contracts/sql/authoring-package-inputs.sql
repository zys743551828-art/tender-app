-- Optional B1 authoring input storage. No job, budget, publication or save permission.
BEGIN;
SET search_path=design,public;

CREATE FUNCTION authoring_package_digest(value jsonb) RETURNS text LANGUAGE sql IMMUTABLE
 SET search_path=pg_catalog,design AS $$
 SELECT encode(sha256(convert_to(design.package_canonical_json(value),'UTF8')),'hex')
$$;

CREATE TABLE authoring_package_inputs(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL REFERENCES bids(id),
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 manifest jsonb NOT NULL,
 digest sha256 NOT NULL,
 context_text text NOT NULL CHECK(octet_length(context_text)<=33554432),
 context_digest sha256 NOT NULL,
 UNIQUE(bid_id,id),
 CHECK(authoring_package_digest(manifest)=digest),
 CHECK(encode(sha256(convert_to(context_text,'UTF8')),'hex')=context_digest)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON authoring_package_inputs
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE TABLE authoring_package_fact_scopes(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL,
 input_id uuid NOT NULL,
 fact_id uuid NOT NULL,
 revision bigint NOT NULL CHECK(revision>0),
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL REFERENCES commands(id),
 manifest jsonb NOT NULL,
 digest sha256 NOT NULL,
 FOREIGN KEY(bid_id,input_id) REFERENCES authoring_package_inputs(bid_id,id),
 FOREIGN KEY(bid_id,fact_id) REFERENCES fact_items(bid_id,id),
 UNIQUE(input_id,fact_id,revision),
 CHECK(authoring_package_digest(manifest)=digest)
);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON authoring_package_fact_scopes
 FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE FUNCTION authoring_package_input_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design,retrieval AS $$
DECLARE m jsonb=NEW.manifest; x jsonb=NEW.context_text::jsonb; b jsonb=m->'selection';
 role_name text; frozen jsonb; ref jsonb; member jsonb; doc jsonb; selected jsonb;
 source jsonb; actual record; package_row record; snap record; sec record;
 item jsonb; fact_row record; decision_row record; scope_item jsonb; cmd design.commands;
 expected_count bigint; matched_count bigint; direct_ids uuid[]; wanted_ids uuid[];
 identity_name text; identity_names text[]=ARRAY['procurement_issuer_identifier','procurement_project_identifier','procurement_lot_identifier','procurement_round_identifier','bidder_identity_identifier'];
 assembled text=''; normalized_value text; frozen_rule jsonb; native jsonb; rule_decision jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'authoring_package_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 PERFORM pg_advisory_xact_lock(90127,1);
 IF EXISTS(SELECT FROM design.bid_profiles WHERE bid_id=NEW.bid_id AND
  (archived_at IS NOT NULL OR phase IN('closed','terminated'))) THEN
  RAISE EXCEPTION 'authoring_package_closed' USING ERRCODE='23514'; END IF;
 IF NOT design.package_json_keys(m,ARRAY['protocol','id','bid_id','actor_id','command_id','saved_at','originals_verified_at','selection','scope','identity_digest','context_digest','method_digest','counts','fact_declarations','generation_available','publication_authorized','apply_available','build_available','formal_decisions_allowed'])
 OR m->>'protocol' IS DISTINCT FROM 'package-authoring-input/1'
 OR m->>'id' IS DISTINCT FROM NEW.id::text OR m->>'bid_id' IS DISTINCT FROM NEW.bid_id::text
 OR m->>'actor_id' IS DISTINCT FROM NEW.actor_id::text OR m->>'command_id' IS DISTINCT FROM NEW.command_id::text
 OR m->>'context_digest' IS DISTINCT FROM NEW.context_digest::text
 OR NOT design.package_json_keys(x,ARRAY['protocol','bid_id','request','packages','identity','documents','inventory','facts','target','sources','method','method_digest'])
 OR x->>'protocol' IS DISTINCT FROM 'package-authoring-context/1'
 OR x->>'bid_id' IS DISTINCT FROM NEW.bid_id::text OR x->'request' IS DISTINCT FROM b
 OR b->>'protocol' IS DISTINCT FROM 'package-authoring-input-request/1'
 OR b->>'purpose' IS DISTINCT FROM 'authoring'
 OR b->>'target_relation' IS DISTINCT FROM 'draft_using_package_context'
 OR NOT design.package_json_keys(b,ARRAY['protocol','purpose','target_relation','package_context','target_section','facts'])
 OR NOT design.package_json_keys(b->'package_context',ARRAY['target','authority','inventory'])
 OR m->>'method_digest' IS DISTINCT FROM x->>'method_digest'
 OR x->>'method_digest' IS DISTINCT FROM design.authoring_package_digest(x->'method')
 OR x#>>'{method,protocol}' IS DISTINCT FROM 'package-authoring-input-policy/1'
 OR x#>>'{method,purpose}' IS DISTINCT FROM 'authoring'
 OR x#>>'{method,target_relation}' IS DISTINCT FROM 'draft_using_package_context'
 OR x#>'{method,complete_package_required}' IS DISTINCT FROM 'true'::jsonb
 OR x#>'{method,implicit_source_selection}' IS DISTINCT FROM 'false'::jsonb
 OR (m->>'originals_verified_at')::timestamptz>(m->>'saved_at')::timestamptz
 OR (m->>'saved_at')::timestamptz>clock_timestamp() THEN
  RAISE EXCEPTION 'authoring_package_input_shape' USING ERRCODE='23514'; END IF;
 FOREACH role_name IN ARRAY ARRAY['generation_available','publication_authorized','apply_available','build_available','formal_decisions_allowed'] LOOP
  IF m->role_name IS DISTINCT FROM 'false'::jsonb THEN
   RAISE EXCEPTION 'authoring_package_input_never_authorized' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF x->'identity' IS DISTINCT FROM design.identity_snapshot_v2(NEW.bid_id)
 OR x#>>'{identity,binding_status}' IS DISTINCT FROM 'confirmed'
 OR m->>'identity_digest' IS DISTINCT FROM x#>>'{identity,digest}' THEN
  RAISE EXCEPTION 'authoring_package_identity_changed' USING ERRCODE='23514'; END IF;
 expected_count:=0;
 FOREACH role_name IN ARRAY ARRAY['target','authority'] LOOP
  ref:=b#>ARRAY['package_context',role_name]; frozen:=x#>ARRAY['packages',role_name];
  SELECT r.*,p.bid_id,p.kind INTO package_row FROM design.bid_package_revisions r
   JOIN design.bid_packages p ON p.id=r.package_id WHERE r.id=(ref->>'revision_id')::uuid;
  IF package_row.id IS NULL OR package_row.bid_id<>NEW.bid_id
  OR package_row.package_id::text IS DISTINCT FROM ref->>'package_id'
  OR package_row.kind IS DISTINCT FROM (CASE WHEN role_name='target' THEN 'bid' ELSE 'authority' END)
  OR package_row.manifest IS DISTINCT FROM frozen->'manifest'
  OR package_row.digest::text IS DISTINCT FROM ref->>'manifest_digest'
  OR package_row.digest::text IS DISTINCT FROM frozen->>'digest'
  OR package_row.identity_snapshot IS DISTINCT FROM frozen->'identity'
  OR package_row.identity_snapshot IS DISTINCT FROM x->'identity'
  OR package_row.manifest->'scope' IS DISTINCT FROM m->'scope' THEN
   RAISE EXCEPTION 'authoring_package_selection_changed' USING ERRCODE='23514'; END IF;
  FOR member IN SELECT value FROM jsonb_array_elements(package_row.manifest->'members') LOOP
   expected_count:=expected_count+1;
   SELECT count(*) INTO matched_count FROM jsonb_array_elements(x->'documents') q
    WHERE q.value->>'package_role'=role_name AND q.value->>'member_id'=member->>'member_id';
   IF matched_count<>1 THEN RAISE EXCEPTION 'authoring_package_document_count' USING ERRCODE='23514'; END IF;
   SELECT value INTO doc FROM jsonb_array_elements(x->'documents') q
    WHERE q.value->>'package_role'=role_name AND q.value->>'member_id'=member->>'member_id';
   SELECT p.*,v.artifact_kind,v.blob_id,blob.digest AS original_digest,blob.byte_size,blob.object_key INTO actual
    FROM design.parse_runs p JOIN design.document_versions v ON v.id=p.document_version_id AND v.bid_id=p.bid_id
    JOIN design.blobs blob ON blob.id=v.blob_id
    JOIN design.bid_package_parse_bindings binding ON binding.parse_run_id=p.id AND binding.bid_id=p.bid_id
    WHERE p.bid_id=NEW.bid_id AND p.id=(member#>>'{parse,parse_run_id}')::uuid
     AND binding.evidence_digest::text=member#>>'{parse,evidence_digest}'
     AND binding.parser_digest=p.parser_digest AND binding.config_digest=p.config_digest;
   IF actual.id IS NULL OR actual.artifact_kind NOT IN('source_original','bid_body')
   OR EXISTS(SELECT FROM design.build_outputs WHERE bid_id=NEW.bid_id AND document_version_id=actual.document_version_id)
   OR member#>>'{parse,status}' IS DISTINCT FROM 'frozen'
   OR actual.document_version_id::text IS DISTINCT FROM member->>'document_version_id'
   OR actual.original_digest::text IS DISTINCT FROM member->>'file_digest'
   OR doc->>'document_version_id' IS DISTINCT FROM actual.document_version_id::text
   OR doc->>'parse_id' IS DISTINCT FROM actual.id::text OR doc->>'blob_id' IS DISTINCT FROM actual.blob_id::text
   OR doc->>'parser_digest' IS DISTINCT FROM actual.parser_digest::text
   OR doc->>'config_digest' IS DISTINCT FROM actual.config_digest::text
   OR doc->>'digest' IS DISTINCT FROM actual.original_digest::text
   OR (doc->>'byte_size')::bigint IS DISTINCT FROM actual.byte_size
   OR doc->>'object_key' IS DISTINCT FROM actual.object_key
   OR (doc->>'page_count')::integer IS DISTINCT FROM actual.page_count
   OR actual.coverage IS DISTINCT FROM 'complete' OR actual.gaps IS DISTINCT FROM '[]'::jsonb
   OR doc->'gaps' IS DISTINCT FROM actual.gaps OR doc->>'coverage' IS DISTINCT FROM actual.coverage THEN
    RAISE EXCEPTION 'authoring_package_parse_binding' USING ERRCODE='23514'; END IF;
   IF (SELECT count(*) FROM design.uploads u JOIN design.document_file_versions v
     ON v.bid_id=u.bid_id AND v.version_id=u.verified_version_id
     JOIN design.document_files file ON file.bid_id=v.bid_id AND file.id=v.file_id
     WHERE u.bid_id=NEW.bid_id AND u.verified_version_id=actual.document_version_id AND u.state='verified'
     AND u.role=file.role AND u.declared_digest=actual.original_digest AND u.declared_size=actual.byte_size
     AND doc->'qualification'=jsonb_build_object('kind','verified_upload','upload',
       jsonb_build_object('id',u.id,'role',u.role,'declared_digest',u.declared_digest,'declared_size',u.declared_size)))<>1 THEN
    RAISE EXCEPTION 'authoring_package_upload_qualification' USING ERRCODE='23514'; END IF;
   IF doc->'pages' IS DISTINCT FROM (SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY physical_page),'[]'::jsonb) FROM
    (SELECT physical_page,printed_label,width::text,height::text,rotation,quality,gaps::text AS gaps_jsonb_text
     FROM design.pages WHERE bid_id=NEW.bid_id AND parse_id=actual.id) q)
   OR doc->'blocks' IS DISTINCT FROM (SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY physical_page,ordinal,id),'[]'::jsonb) FROM
    (SELECT id,physical_page,ordinal,kind,text_content,bbox::text AS bbox_jsonb_text,structure::text AS structure_jsonb_text,digest
     FROM design.evidence_blocks WHERE bid_id=NEW.bid_id AND parse_id=actual.id) q)
   OR jsonb_array_length(doc->'pages')<>actual.page_count OR jsonb_array_length(doc->'blocks')=0 THEN
    RAISE EXCEPTION 'authoring_package_full_evidence' USING ERRCODE='23514'; END IF;
   IF EXISTS(SELECT FROM generate_series(1,actual.page_count) page_number WHERE NOT EXISTS(
    SELECT FROM jsonb_array_elements(member->'parts') part
    WHERE page_number BETWEEN (part.value->>'first_page')::integer AND (part.value->>'last_page')::integer)) THEN
    RAISE EXCEPTION 'authoring_package_full_physical_range' USING ERRCODE='23514'; END IF;
  END LOOP;
 END LOOP;
 IF jsonb_array_length(x->'documents')<>expected_count THEN
  RAISE EXCEPTION 'authoring_package_document_count' USING ERRCODE='23514'; END IF;
 ref:=b#>'{package_context,inventory}';
 SELECT i.* INTO actual FROM design.bid_package_requirement_inventories i
  JOIN design.bid_package_requirement_heads h ON h.inventory_id=i.id
  JOIN design.bid_profiles p ON p.bid_id=i.bid_id AND p.current_rule_set_id=i.rule_set_id
  WHERE i.bid_id=NEW.bid_id AND i.id=(ref->>'id')::uuid;
 IF actual.id IS NULL OR actual.digest::text IS DISTINCT FROM ref->>'digest'
 OR actual.rule_set_id::text IS DISTINCT FROM ref->>'rule_set_id'
 OR actual.target_revision_id::text IS DISTINCT FROM b#>>'{package_context,target,revision_id}'
 OR actual.authority_revision_id::text IS DISTINCT FROM b#>>'{package_context,authority,revision_id}'
 OR x#>'{inventory,record,manifest}' IS DISTINCT FROM actual.manifest
 OR x#>>'{inventory,record,digest}' IS DISTINCT FROM actual.digest::text
 OR actual.manifest->>'version' NOT IN('bid-package-requirements/2','bid-package-requirements/3') THEN
  RAISE EXCEPTION 'authoring_package_inventory' USING ERRCODE='23514'; END IF;
 IF jsonb_array_length(actual.manifest->'requirements') IS DISTINCT FROM
  (SELECT count(*) FROM design.rule_items WHERE bid_id=NEW.bid_id AND rule_set_id=actual.rule_set_id)::integer THEN
  RAISE EXCEPTION 'authoring_package_full_rules' USING ERRCODE='23514'; END IF;
 FOR frozen_rule IN SELECT value FROM jsonb_array_elements(actual.manifest->'requirements') LOOP
  SELECT to_jsonb(dec) INTO rule_decision FROM design.rule_items r
   LEFT JOIN design.decision_heads h ON h.bid_id=r.bid_id AND h.object_kind='rule' AND h.object_id=r.id
   LEFT JOIN design.rule_carryovers carry ON carry.bid_id=r.bid_id AND carry.new_rule_id=r.id
   JOIN design.decisions dec ON dec.id=coalesce(h.decision_id,carry.from_decision_id) AND dec.bid_id=r.bid_id
   WHERE r.id=(frozen_rule->>'rule_id')::uuid AND r.bid_id=NEW.bid_id AND r.rule_set_id=actual.rule_set_id;
  IF NOT EXISTS(SELECT FROM design.rule_items r WHERE r.id=(frozen_rule->>'rule_id')::uuid
   AND r.bid_id=NEW.bid_id AND r.rule_set_id=actual.rule_set_id
   AND frozen_rule->'rule_snapshot'=to_jsonb(r)||jsonb_build_object('max_points',r.max_points::text))
  OR frozen_rule#>>'{rule_snapshot,provenance_status}' IS DISTINCT FROM 'effective'
  OR rule_decision->>'decision' IS DISTINCT FROM 'confirmed'
  OR frozen_rule->'decision_snapshot' IS DISTINCT FROM rule_decision
  OR frozen_rule->>'decision_id' IS DISTINCT FROM rule_decision->>'id'
  OR frozen_rule->'source_bound' IS DISTINCT FROM 'true'::jsonb THEN
   RAISE EXCEPTION 'authoring_package_rules_changed' USING ERRCODE='23514'; END IF;
 END LOOP;
 native:=x#>'{inventory,native_receipt}';
 IF NOT EXISTS(SELECT FROM design.bid_package_requirement_extraction_runs run
   JOIN design.operations op ON op.id=run.operation_id AND op.bid_id=run.bid_id
   JOIN design.effect_receipts effect ON effect.operation_id=op.id AND effect.effect_key='extract-rules'
   WHERE run.bid_id=NEW.bid_id AND run.id=(native#>>'{run,id}')::uuid
   AND native->'run'=jsonb_build_object('id',run.id,'bid_id',run.bid_id,'authority_revision_id',run.authority_revision_id,
    'authority_digest',run.authority_digest,'input_blob_id',run.input_blob_id,'input_digest',run.input_digest,
    'input_manifest',run.input_manifest,'operation_id',run.operation_id,'operation_input_digest',run.operation_input_digest,
    'rule_set_id',run.rule_set_id,'result_digest',run.result_digest,'result',run.result)
   AND native->'operation'=jsonb_build_object('id',op.id,'bid_id',op.bid_id,'input_digest',op.input_digest,'handler_version',op.handler_version,'state',op.state)
   AND native->'effect'=effect.result AND op.state='succeeded' AND op.handler_version='prepare/1'
   AND run.authority_revision_id::text=b#>>'{package_context,authority,revision_id}'
   AND run.result->>'extraction_coverage'='complete'
   AND run.result->>'range_status'='all_frozen_evidence_submitted') THEN
  RAISE EXCEPTION 'authoring_package_extraction_receipt' USING ERRCODE='23514'; END IF;
 ref:=b->'target_section';
 SELECT s.* INTO snap FROM design.draft_snapshots s JOIN design.drafts d ON d.id=s.draft_id AND d.bid_id=s.bid_id
  WHERE s.bid_id=NEW.bid_id AND s.id=(ref->>'snapshot_id')::uuid AND d.revision=s.revision;
 SELECT r.* INTO sec FROM design.section_revisions r JOIN design.sections s ON s.id=r.section_id AND s.bid_id=r.bid_id
  JOIN design.draft_snapshot_sections link ON link.section_revision_id=r.id AND link.bid_id=r.bid_id
  WHERE link.snapshot_id=snap.id AND r.id=(ref->>'section_revision_id')::uuid AND s.head_revision=r.revision;
 IF snap.id IS NULL OR sec.id IS NULL OR snap.draft_id::text IS DISTINCT FROM ref->>'draft_id'
 OR snap.digest::text IS DISTINCT FROM ref->>'snapshot_digest'
 OR snap.revision IS DISTINCT FROM (ref->>'base_draft_revision')::bigint
 OR sec.section_id::text IS DISTINCT FROM ref->>'section_id'
 OR sec.revision IS DISTINCT FROM (ref->>'base_section_revision')::bigint
 OR sec.digest::text IS DISTINCT FROM ref->>'section_digest'
 OR sec.schema_digest::text IS DISTINCT FROM ref->>'schema_digest'
 OR x#>'{target,snapshot_manifest}' IS DISTINCT FROM snap.manifest
 OR x#>>'{target,snapshot,snapshot_digest}' IS DISTINCT FROM snap.digest::text
 OR x#>'{target,sections}' IS DISTINCT FROM (SELECT jsonb_agg(to_jsonb(q)-'ordinal' ORDER BY q.ordinal) FROM
  (SELECT r.id,r.section_id,r.revision,r.schema_digest,r.content,r.digest,s.head_revision,link.ordinal
   FROM design.draft_snapshot_sections link JOIN design.section_revisions r ON r.id=link.section_revision_id
   JOIN design.sections s ON s.id=r.section_id WHERE link.snapshot_id=snap.id) q) THEN
  RAISE EXCEPTION 'authoring_package_target' USING ERRCODE='23514';
 END IF;
 IF (SELECT count(*) FROM jsonb_path_query(sec.content,'strict $.** ? (@.attrs.id == $id)',jsonb_build_object('id',ref->'node_id')) node
  WHERE node->>'type' IN('paragraph','heading') AND design.authoring_package_digest(node)=ref->>'before_node_digest')<>1 THEN
  RAISE EXCEPTION 'authoring_package_target_node' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT FROM design.fact_heads h JOIN design.fact_sets s ON s.id=h.fact_set_id AND s.bid_id=h.bid_id
  WHERE h.bid_id=NEW.bid_id AND h.fact_set_id=(b#>>'{facts,fact_set_id}')::uuid
  AND h.revision=(b#>>'{facts,fact_head_revision}')::bigint
  AND x#>'{facts,head}'=jsonb_build_object('fact_set_id',h.fact_set_id,'revision',h.revision,'fact_set_digest',s.digest)) THEN
  RAISE EXCEPTION 'authoring_package_fact_head' USING ERRCODE='23514'; END IF;
 IF jsonb_array_length(b#>'{facts,identity_fact_ids}')<>5
 OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(b#>'{facts,identity_fact_ids}'))<>5
 OR (SELECT count(DISTINCT value#>>'{item,fact,id}') FROM jsonb_array_elements(x#>'{facts,items}'))<>jsonb_array_length(x#>'{facts,items}')
 OR (SELECT count(*) FROM jsonb_array_elements(x#>'{facts,items}')) IS DISTINCT FROM
  (SELECT count(DISTINCT id) FROM (SELECT value#>>'{}' AS id FROM jsonb_array_elements(b#>'{facts,identity_fact_ids}')
    UNION SELECT value->>'fact_id' FROM jsonb_array_elements(b#>'{facts,uses}')) q) THEN
  RAISE EXCEPTION 'authoring_package_fact_count' USING ERRCODE='23514'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(x#>'{facts,items}') LOOP
  selected:=item#>'{item,fact}';
  IF NOT EXISTS(SELECT FROM jsonb_array_elements(b#>'{facts,identity_fact_ids}') q WHERE q.value#>>'{}'=selected->>'id')
   AND NOT EXISTS(SELECT FROM jsonb_array_elements(b#>'{facts,uses}') q WHERE q.value->>'fact_id'=selected->>'id') THEN
   RAISE EXCEPTION 'authoring_package_fact_count' USING ERRCODE='23514'; END IF;
  SELECT f.*,s.digest AS fact_set_digest INTO fact_row FROM design.fact_items f JOIN design.fact_sets s ON s.id=f.fact_set_id AND s.bid_id=f.bid_id
   WHERE f.bid_id=NEW.bid_id AND f.id=(selected->>'id')::uuid AND f.fact_set_id=(b#>>'{facts,fact_set_id}')::uuid;
  SELECT dec.*,h.revision AS decision_revision INTO decision_row FROM design.decision_heads h JOIN design.decisions dec ON dec.id=h.decision_id
   WHERE h.bid_id=NEW.bid_id AND h.object_kind='fact' AND h.object_id=fact_row.id;
  IF fact_row.id IS NULL OR decision_row.id IS NULL OR decision_row.decision IS DISTINCT FROM 'confirmed'
  OR selected IS DISTINCT FROM jsonb_build_object('id',fact_row.id,'bid_id',fact_row.bid_id,'fact_set_id',fact_row.fact_set_id,
    'subject',fact_row.subject,'scope',fact_row.scope,'name',fact_row.name,'value_jsonb_text',fact_row.value::text,'unit',fact_row.unit,
    'evidence_ids',fact_row.evidence_ids,'fact_set_digest',fact_row.fact_set_digest)
  OR (item#>'{item,decision}')-'created_at' IS DISTINCT FROM to_jsonb(decision_row)-'created_at'
  OR (item#>>'{item,decision,created_at}')::timestamptz IS DISTINCT FROM decision_row.created_at
  OR item#>>'{item,scope_binding}' IS DISTINCT FROM 'selected_frozen_parse'
  OR item->>'item_digest' IS DISTINCT FROM design.authoring_package_digest(item->'item')
  OR item->>'proof_digest' IS DISTINCT FROM design.authoring_package_digest(item->'proof')
  OR item#>'{proof,decision_binding}' IS DISTINCT FROM 'true'::jsonb
  OR item#>'{proof,sources_effective}' IS DISTINCT FROM 'true'::jsonb
  OR item#>'{proof,evidence_usable}' IS DISTINCT FROM 'true'::jsonb
  OR (SELECT count(*) FROM design.audit_entries a WHERE a.bid_id=NEW.bid_id AND a.event_type='human.decision_recorded'
    AND a.payload->>'decision_id'=decision_row.id::text AND (a.payload->'basis')::text=item#>>'{item,decision_basis_jsonb_text}')<>1 THEN
   RAISE EXCEPTION 'authoring_package_fact_binding' USING ERRCODE='23514'; END IF;
  IF EXISTS(SELECT FROM unnest(fact_row.evidence_ids) eid LEFT JOIN design.evidence_blocks block ON block.id=eid AND block.bid_id=NEW.bid_id
   WHERE block.id IS NULL OR NOT EXISTS(SELECT FROM jsonb_array_elements(x->'documents') docx WHERE docx.value->>'parse_id'=block.parse_id::text)) THEN
   RAISE EXCEPTION 'authoring_package_fact_parse' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOREACH identity_name IN ARRAY identity_names LOOP
  SELECT count(*) INTO matched_count FROM design.fact_items f
   WHERE f.bid_id=NEW.bid_id AND f.fact_set_id=(b#>>'{facts,fact_set_id}')::uuid AND f.name=identity_name
   AND f.id::text IN(SELECT value#>>'{}' FROM jsonb_array_elements(b#>'{facts,identity_fact_ids}'))
   AND jsonb_typeof(f.value)='string';
  IF matched_count<>1 THEN RAISE EXCEPTION 'authoring_package_identity_facts' USING ERRCODE='23514'; END IF;
  SELECT btrim(regexp_replace(normalize(replace(replace(f.value#>>'{}',chr(13)||chr(10),chr(10)),chr(13),chr(10)),NFKC),'[[:space:]]+',' ','g'))
   INTO normalized_value FROM design.fact_items f WHERE f.bid_id=NEW.bid_id AND f.fact_set_id=(b#>>'{facts,fact_set_id}')::uuid
   AND f.name=identity_name AND f.id::text IN(SELECT value#>>'{}' FROM jsonb_array_elements(b#>'{facts,identity_fact_ids}'));
  IF length(normalized_value)=0 THEN RAISE EXCEPTION 'authoring_package_identity_facts' USING ERRCODE='23514'; END IF;
  IF assembled<>'' THEN assembled:=assembled||chr(31); END IF;
  assembled:=assembled||identity_name||'='||normalized_value;
 END LOOP;
 IF x#>>'{facts,canonical_project_key}' IS DISTINCT FROM encode(sha256(convert_to(assembled,'UTF8')),'hex') THEN
  RAISE EXCEPTION 'authoring_package_canonical_identity' USING ERRCODE='23514'; END IF;
 FOR scope_item IN SELECT value FROM jsonb_array_elements(b#>'{facts,uses}') LOOP
  IF scope_item#>>'{subject,id}' IS DISTINCT FROM x#>>ARRAY['identity',CASE scope_item#>>'{subject,kind}'
    WHEN 'engineering_project' THEN 'engineering_project_id' WHEN 'lot' THEN 'lot_id'
    WHEN 'round' THEN 'round_id' WHEN 'bidder' THEN 'bidder_id' ELSE '__invalid__' END] THEN
   RAISE EXCEPTION 'authoring_package_fact_subject' USING ERRCODE='23514'; END IF;
 END LOOP;
 SELECT array_agg(DISTINCT (value->>'source_id')::uuid) INTO direct_ids FROM jsonb_array_elements(x->'sources');
 SELECT array_agg(DISTINCT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42','document-parse:'||(value->>'parse_id')))
  INTO wanted_ids FROM jsonb_array_elements(x->'documents');
 IF direct_ids IS DISTINCT FROM wanted_ids THEN
  RAISE EXCEPTION 'authoring_package_source_count' USING ERRCODE='23514'; END IF;
 FOR doc IN SELECT value FROM jsonb_array_elements(x->'documents') LOOP
  IF NOT EXISTS(SELECT FROM retrieval.source_nodes node JOIN retrieval.lineage_edges edge ON edge.child_id=node.id
   JOIN retrieval.source_nodes root ON root.id=edge.parent_id
   WHERE node.id=public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42','document-parse:'||(doc->>'parse_id'))
   AND root.id=public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42','document-original:'||(doc->>'document_version_id'))
   AND node.document_version_id::text=doc->>'document_version_id' AND root.document_version_id=node.document_version_id
   AND node.digest::text=doc->>'digest' AND root.digest=node.digest) THEN
   RAISE EXCEPTION 'authoring_package_source_root' USING ERRCODE='23514'; END IF;
 END LOOP;
 PERFORM h.source_id FROM retrieval.source_heads h WHERE h.source_id IN
  (SELECT ancestor_id FROM retrieval.source_ancestors WHERE source_id=ANY(direct_ids)) ORDER BY h.source_id FOR UPDATE;
 IF (SELECT count(*) FROM retrieval.source_ancestors WHERE source_id=ANY(direct_ids)) IS DISTINCT FROM jsonb_array_length(x->'sources')::bigint
 OR (SELECT count(DISTINCT (value->>'source_id',value->>'id')) FROM jsonb_array_elements(x->'sources'))<>jsonb_array_length(x->'sources') THEN
  RAISE EXCEPTION 'authoring_package_source_count' USING ERRCODE='23514'; END IF;
 FOR source IN SELECT value FROM jsonb_array_elements(x->'sources') LOOP
  SELECT n.*,h.revision,h.status,h.valid_from,h.valid_until INTO actual
   FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.ancestor_id
   LEFT JOIN retrieval.source_heads h ON h.source_id=n.id
   WHERE a.source_id=(source->>'source_id')::uuid AND a.ancestor_id=(source->>'id')::uuid;
  IF actual.id IS NULL OR actual.revision IS NULL OR actual.valid_from IS NULL OR actual.known_at IS NULL
  OR actual.kind IS DISTINCT FROM 'document' OR actual.policy_class IS DISTINCT FROM 'prebid_content'
  OR actual.document_version_id::text IS DISTINCT FROM source->>'document_version_id'
  OR actual.digest::text IS DISTINCT FROM source->>'digest' OR actual.revision IS DISTINCT FROM (source->>'revision')::bigint
  OR actual.status IS DISTINCT FROM 'published' OR actual.status IS DISTINCT FROM source->>'status'
  OR actual.known_at IS DISTINCT FROM (source->>'known_at')::timestamptz
  OR actual.valid_from IS DISTINCT FROM (source->>'valid_from')::timestamptz
  OR actual.valid_until IS DISTINCT FROM (source->>'valid_until')::timestamptz
  OR actual.known_at>clock_timestamp() OR actual.valid_from>clock_timestamp() OR actual.valid_until<=clock_timestamp()
  OR NOT EXISTS(SELECT FROM jsonb_array_elements(x->'documents') docx WHERE docx.value->>'document_version_id'=actual.document_version_id::text) THEN
   RAISE EXCEPTION 'authoring_package_source_changed' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF m->'counts' IS DISTINCT FROM jsonb_build_object('logical_members',jsonb_array_length(x->'documents'),
  'physical_pages',(SELECT sum((value->>'page_count')::bigint) FROM jsonb_array_elements(x->'documents')),
  'evidence_blocks',(SELECT sum(jsonb_array_length(value->'blocks')) FROM jsonb_array_elements(x->'documents')),
  'facts',jsonb_array_length(x#>'{facts,items}'),'requirements',jsonb_array_length(x#>'{inventory,record,manifest,requirements}'),
  'context_bytes',octet_length(NEW.context_text)) THEN
  RAISE EXCEPTION 'authoring_package_counts' USING ERRCODE='23514'; END IF;
 IF jsonb_array_length(m->'fact_declarations')<>jsonb_array_length(b#>'{facts,uses}') THEN
  RAISE EXCEPTION 'authoring_package_declaration_count' USING ERRCODE='23514'; END IF;
 FOR scope_item IN SELECT value FROM jsonb_array_elements(m->'fact_declarations') LOOP
  IF NOT EXISTS(SELECT FROM design.authoring_package_fact_scopes s WHERE s.input_id=NEW.id AND s.bid_id=NEW.bid_id
   AND s.id=(scope_item#>>'{manifest,id}')::uuid AND s.manifest=scope_item->'manifest' AND s.digest::text=scope_item->>'digest' AND s.revision=1) THEN
   RAISE EXCEPTION 'authoring_package_declaration_missing' USING ERRCODE='23514'; END IF;
 END LOOP;
 SELECT * INTO cmd FROM design.commands WHERE id=NEW.command_id;
 IF cmd.actor_id IS DISTINCT FROM NEW.actor_id OR cmd.command_kind IS DISTINCT FROM 'authoring-package-input-save'
 OR cmd.target_id IS DISTINCT FROM NEW.bid_id
 OR cmd.request_digest::text IS DISTINCT FROM design.authoring_package_digest(jsonb_build_object('body',b,'if_match',NULL))
 OR cmd.response->>'status' IS DISTINCT FROM '201'
 OR cmd.response->'body' IS DISTINCT FROM jsonb_build_object('manifest',m,'digest',NEW.digest)
 OR (SELECT count(*) FROM design.audit_entries a WHERE a.command_id=cmd.id AND a.bid_id=NEW.bid_id
  AND a.actor_id=NEW.actor_id AND a.event_type='authoring.package_input_saved'
  AND a.payload=jsonb_build_object('input_id',NEW.id,'input_digest',NEW.digest,'context_digest',NEW.context_digest))<>1 THEN
  RAISE EXCEPTION 'authoring_package_input_ack' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER authoring_package_input_complete AFTER INSERT ON authoring_package_inputs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_package_input_guard();

CREATE FUNCTION authoring_package_fact_scope_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE input design.authoring_package_inputs; m jsonb=NEW.manifest; request jsonb; selected jsonb;
 previous design.authoring_package_fact_scopes; cmd design.commands;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'authoring_package_requires_read_committed' USING ERRCODE='25001'; END IF;
 PERFORM design.lock_worker_bid(NEW.bid_id);
 SELECT * INTO input FROM design.authoring_package_inputs WHERE id=NEW.input_id AND bid_id=NEW.bid_id;
 SELECT * INTO cmd FROM design.commands WHERE id=NEW.command_id;
 IF input.id IS NULL OR NOT design.package_json_keys(m,ARRAY['protocol','id','bid_id','input_id','fact_id','purpose','revision','action','previous_digest','actor_id','command_id','recorded_at','basis_digest','fact_item_digest','proof_digest','subject','reason'])
 OR m->>'protocol' IS DISTINCT FROM 'authoring-package-fact-scope/1' OR m->>'purpose' IS DISTINCT FROM 'authoring'
 OR m->>'id' IS DISTINCT FROM NEW.id::text OR m->>'bid_id' IS DISTINCT FROM NEW.bid_id::text
 OR m->>'input_id' IS DISTINCT FROM NEW.input_id::text OR m->>'fact_id' IS DISTINCT FROM NEW.fact_id::text
 OR (m->>'revision')::bigint IS DISTINCT FROM NEW.revision OR m->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
 OR m->>'command_id' IS DISTINCT FROM NEW.command_id::text OR m->>'basis_digest' IS DISTINCT FROM input.context_digest::text
 OR cmd.actor_id IS DISTINCT FROM NEW.actor_id OR (m->>'recorded_at')::timestamptz>clock_timestamp()
 OR length(btrim(m->>'reason')) NOT BETWEEN 1 AND 2000 THEN
  RAISE EXCEPTION 'authoring_package_fact_scope_shape' USING ERRCODE='23514'; END IF;
 SELECT value INTO selected FROM jsonb_array_elements(input.manifest#>'{selection,facts,uses}') WHERE value->>'fact_id'=NEW.fact_id::text;
 IF selected IS NULL OR selected->'subject' IS DISTINCT FROM m->'subject'
 OR selected->>'fact_item_digest' IS DISTINCT FROM m->>'fact_item_digest'
 OR NOT EXISTS(SELECT FROM jsonb_array_elements((input.context_text::jsonb)#>'{facts,items}') item
  WHERE item.value#>>'{item,fact,id}'=NEW.fact_id::text AND item.value->>'item_digest'=m->>'fact_item_digest'
   AND item.value->>'proof_digest'=m->>'proof_digest') THEN
  RAISE EXCEPTION 'authoring_package_fact_scope_binding' USING ERRCODE='23514'; END IF;
 IF NEW.revision=1 THEN
  IF m->>'action' IS DISTINCT FROM 'bind' OR m->'previous_digest' IS DISTINCT FROM 'null'::jsonb
  OR cmd.id IS DISTINCT FROM input.command_id OR cmd.command_kind IS DISTINCT FROM 'authoring-package-input-save'
  OR NOT EXISTS(SELECT FROM jsonb_array_elements(input.manifest->'fact_declarations') v WHERE
    v.value=jsonb_build_object('manifest',m,'digest',NEW.digest)) THEN
   RAISE EXCEPTION 'authoring_package_fact_scope_original' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO previous FROM design.authoring_package_fact_scopes
   WHERE input_id=NEW.input_id AND fact_id=NEW.fact_id AND revision=NEW.revision-1;
  request:=jsonb_build_object('input_digest',input.digest,'fact_id',NEW.fact_id,
    'declaration_digest',previous.digest,'reason',m->'reason');
  IF NEW.revision<>2 OR previous.id IS NULL OR previous.manifest->>'action' IS DISTINCT FROM 'bind'
  OR m->>'action' IS DISTINCT FROM 'withdraw' OR m->>'previous_digest' IS DISTINCT FROM previous.digest::text
  OR (m-ARRAY['id','revision','action','previous_digest','actor_id','command_id','recorded_at','reason']) IS DISTINCT FROM
   (previous.manifest-ARRAY['id','revision','action','previous_digest','actor_id','command_id','recorded_at','reason'])
  OR cmd.command_kind IS DISTINCT FROM 'authoring-package-fact-withdraw' OR cmd.target_id IS DISTINCT FROM NEW.input_id
  OR cmd.request_digest::text IS DISTINCT FROM design.authoring_package_digest(jsonb_build_object('body',request,'if_match',NULL))
  OR cmd.response->>'status' IS DISTINCT FROM '201'
  OR cmd.response->'body' IS DISTINCT FROM jsonb_build_object('manifest',m,'digest',NEW.digest) THEN
   RAISE EXCEPTION 'authoring_package_fact_scope_withdraw' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER authoring_package_fact_scope_complete AFTER INSERT ON authoring_package_fact_scopes
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION authoring_package_fact_scope_guard();

REVOKE ALL ON authoring_package_inputs,authoring_package_fact_scopes FROM PUBLIC,tender_api,tender_worker;
GRANT SELECT,INSERT ON authoring_package_inputs,authoring_package_fact_scopes TO tender_api;
REVOKE ALL ON FUNCTION authoring_package_input_guard(),authoring_package_fact_scope_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION authoring_package_digest(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION authoring_package_digest(jsonb) TO tender_api;
COMMIT;
