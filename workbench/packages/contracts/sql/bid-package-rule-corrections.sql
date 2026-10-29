-- Fresh reviewed exact-package human derivations. Install after requirements,
-- dependency plans and roles. No model result is manufactured or rewritten.
BEGIN;
SET search_path=design,public;

CREATE TABLE bid_package_rule_corrections(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL REFERENCES bid_profiles(bid_id),
 package_id uuid NOT NULL,
 revision_id uuid NOT NULL,
 base_inventory_id uuid NOT NULL,
 result_inventory_id uuid NOT NULL UNIQUE,
 root_inventory_id uuid NOT NULL,
 base_rule_set_id uuid NOT NULL,
 result_rule_set_id uuid NOT NULL UNIQUE,
 previous_id uuid REFERENCES bid_package_rule_corrections(id),
 sequence_no integer NOT NULL CHECK(sequence_no BETWEEN 1 AND 32),
 actor_id uuid NOT NULL REFERENCES members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES commands(id),
 manifest jsonb NOT NULL,
 digest sha256 NOT NULL,
 created_at timestamptz NOT NULL,
 FOREIGN KEY(package_id,bid_id) REFERENCES bid_packages(id,bid_id),
 FOREIGN KEY(package_id,revision_id) REFERENCES bid_package_revisions(package_id,id),
 FOREIGN KEY(bid_id,base_inventory_id) REFERENCES bid_package_requirement_inventories(bid_id,id),
 FOREIGN KEY(bid_id,result_inventory_id) REFERENCES bid_package_requirement_inventories(bid_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(bid_id,root_inventory_id) REFERENCES bid_package_requirement_inventories(bid_id,id),
 FOREIGN KEY(bid_id,base_rule_set_id) REFERENCES rule_sets(bid_id,id),
 FOREIGN KEY(bid_id,result_rule_set_id) REFERENCES rule_sets(bid_id,id),
 CHECK(base_inventory_id<>result_inventory_id AND base_rule_set_id<>result_rule_set_id),
 CHECK((sequence_no=1)=(previous_id IS NULL)),
 CHECK(encode(sha256(convert_to(package_canonical_json(manifest),'UTF8')),'hex')=digest),
 UNIQUE(bid_id,id)
);
CREATE INDEX package_rule_correction_history ON bid_package_rule_corrections(bid_id,package_id,revision_id,root_inventory_id,created_at DESC,id DESC);
CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON bid_package_rule_corrections
 FOR EACH ROW EXECUTE FUNCTION append_only();
CREATE VIEW bid_package_rule_correction_command_receipts WITH (security_barrier=true) AS
 SELECT c.id,c.actor_id,c.command_kind,c.target_id,c.idempotency_key,c.request_digest,c.response
 FROM design.commands c JOIN design.bid_package_rule_corrections r ON r.command_id=c.id
 WHERE c.command_kind='package-rule-correction-apply' AND c.actor_id=r.actor_id
 AND c.target_id=r.base_inventory_id;

CREATE FUNCTION package_rule_json_digest(value jsonb) RETURNS text LANGUAGE sql IMMUTABLE
 SET search_path=pg_catalog,design AS $$
 SELECT encode(sha256(convert_to(design.package_canonical_json(value),'UTF8')),'hex')
$$;

CREATE FUNCTION package_rule_text(value jsonb,max_chars integer) RETURNS boolean LANGUAGE sql IMMUTABLE
 SET search_path=pg_catalog AS $$
 SELECT coalesce(jsonb_typeof(value)='string' AND length(value#>>'{}') BETWEEN 1 AND max_chars AND btrim(value#>>'{}')<>'',false)
$$;

CREATE FUNCTION package_rule_semantic(value jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE
 SET search_path=pg_catalog AS $$
 SELECT value-ARRAY['id','bid_id','rule_set_id','origin_kind','manual_origin_rule_id']
$$;

CREATE FUNCTION package_rule_root_basis(value jsonb,fingerprint text) RETURNS jsonb LANGUAGE sql IMMUTABLE
 SET search_path=pg_catalog AS $$
 SELECT CASE WHEN value->>'version'='bid-package-requirements/3' THEN value->'extraction_basis'
 ELSE jsonb_build_object('inventory_id',value->'id','inventory_digest',fingerprint,
 'rule_set_id',value->'rule_set_id','rule_set_digest',value->'rule_set_digest',
 'extraction_result_id',value->'extraction_result_id','extraction_input_digest',value->'extraction_input_digest',
 'extraction_result_digest',value->'extraction_result_digest','extraction_range_status',value->'extraction_range_status',
 'extraction_coverage',value->'extraction_coverage','extraction_quality_status',value->'extraction_quality_status') END
$$;

CREATE FUNCTION package_rule_quote_guard(bid uuid,authority uuid,quotes jsonb) RETURNS jsonb LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE q jsonb; row record; result jsonb='[]'; parts jsonb;
BEGIN
 IF jsonb_typeof(quotes) IS DISTINCT FROM 'array' OR jsonb_array_length(quotes) NOT BETWEEN 1 AND 50
 OR (SELECT count(*) FROM jsonb_array_elements(quotes))<>(SELECT count(DISTINCT v) FROM jsonb_array_elements(quotes) x(v))
 THEN RAISE EXCEPTION 'package_rule_correction_quote_shape' USING ERRCODE='23514'; END IF;
 FOR q IN SELECT value FROM jsonb_array_elements(quotes) LOOP
  IF NOT design.package_json_keys(q,ARRAY['evidence_id','quote']) OR NOT design.package_rule_text(q->'quote',8000)
  OR length(q->>'quote')>8000 OR btrim(q->>'quote')='' THEN
   RAISE EXCEPTION 'package_rule_correction_quote_shape' USING ERRCODE='23514'; END IF;
  SELECT e.id,e.physical_page,e.text_content,e.digest,m.member_id,m.document_version_id,m.parse_run_id
  INTO row FROM design.evidence_blocks e JOIN design.bid_package_members m ON m.bid_id=e.bid_id AND m.parse_run_id=e.parse_id
  WHERE e.bid_id=bid AND e.id::text=q->>'evidence_id' AND m.revision_id=authority;
  IF row.id IS NULL OR strpos(row.text_content,q->>'quote')=0
  OR row.digest::text<>encode(sha256(convert_to(row.text_content,'UTF8')),'hex') THEN
   RAISE EXCEPTION 'package_rule_correction_quote_scope' USING ERRCODE='23514'; END IF;
  SELECT coalesce(jsonb_agg(p.part_id ORDER BY p.part_id),'[]') INTO parts FROM design.bid_package_parts p
  WHERE p.revision_id=authority AND p.member_id=row.member_id AND row.physical_page BETWEEN p.first_page AND p.last_page;
  IF jsonb_array_length(parts)=0 THEN RAISE EXCEPTION 'package_rule_correction_quote_scope' USING ERRCODE='23514'; END IF;
  result=result||jsonb_build_array(jsonb_build_object('evidence_id',row.id,'member_id',row.member_id,
   'document_version_id',row.document_version_id,'parse_run_id',row.parse_run_id,'physical_page',row.physical_page,
   'evidence_digest',row.digest,'part_ids',parts,'quote',q->'quote'));
 END LOOP;
 RETURN result;
END $$;

CREATE FUNCTION package_rule_expected(bid uuid,target_set uuid,target_id uuid,input jsonb) RETURNS jsonb LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE quotes jsonb; refs jsonb; joined text; value jsonb; band jsonb; maximum numeric;
BEGIN
 IF NOT design.package_json_keys(input,ARRAY['kind','statement','conditions','exceptions','scope','maximum','bands','evidence_quotes'])
 OR (input->>'kind' IN('disqualification','mandatory','scoring','advisory')) IS NOT TRUE
 OR NOT design.package_rule_text(input->'statement',16000) OR btrim(input->>'statement')='' OR length(input->>'statement')>16000
 OR NOT design.package_json_keys(input->'scope',ARRAY['bid_id','description'])
 OR input#>>'{scope,bid_id}' IS DISTINCT FROM bid::text OR NOT design.package_rule_text(input#>'{scope,description}',2000)
 OR btrim(input#>>'{scope,description}')='' OR length(input#>>'{scope,description}')>2000
 OR jsonb_typeof(input->'conditions') IS DISTINCT FROM 'array' OR jsonb_array_length(input->'conditions')>50
 OR jsonb_typeof(input->'exceptions') IS DISTINCT FROM 'array' OR jsonb_array_length(input->'exceptions')>50
 OR jsonb_typeof(input->'bands') IS DISTINCT FROM 'array' OR jsonb_array_length(input->'bands')>100
 THEN RAISE EXCEPTION 'package_rule_correction_rule_shape' USING ERRCODE='23514'; END IF;
 quotes=input->'evidence_quotes';
 SELECT string_agg(v->>'quote',E'\n' ORDER BY n) INTO joined FROM jsonb_array_elements(quotes) WITH ORDINALITY x(v,n);
 SELECT coalesce(jsonb_agg(id ORDER BY first),'[]') INTO refs FROM (
  SELECT v->>'evidence_id' AS id,min(n) AS first FROM jsonb_array_elements(quotes) WITH ORDINALITY x(v,n) GROUP BY v->>'evidence_id') q;
 FOR value IN SELECT v FROM jsonb_array_elements((input->'conditions')||(input->'exceptions')) x(v) LOOP
  IF NOT design.package_rule_text(value,8000) OR length(value#>>'{}')>8000 OR strpos(joined,value#>>'{}')=0
  THEN RAISE EXCEPTION 'package_rule_correction_condition_unquoted' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF input->>'kind'='scoring' THEN
  IF jsonb_typeof(input->'maximum') IS DISTINCT FROM 'string'
  OR (input->>'maximum' ~ '^([1-9][0-9]*(\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*)$') IS NOT TRUE
  OR joined !~ ('(?<![0-9.])'||replace(input->>'maximum','.','\.')||'(?![0-9.])') THEN
   RAISE EXCEPTION 'package_rule_correction_points_unquoted' USING ERRCODE='23514'; END IF;
  maximum=(input->>'maximum')::numeric;
 ELSE
  IF input->'maximum' IS DISTINCT FROM 'null'::jsonb OR jsonb_array_length(input->'bands')<>0 THEN
   RAISE EXCEPTION 'package_rule_correction_rule_shape' USING ERRCODE='23514'; END IF;
 END IF;
 FOR band IN SELECT v FROM jsonb_array_elements(input->'bands') x(v) LOOP
  IF NOT design.package_json_keys(band,ARRAY['label','description','points','evidence_ids'])
  OR NOT design.package_rule_text(band->'label',8000) OR NOT design.package_rule_text(band->'description',8000)
  OR jsonb_typeof(band->'points') IS DISTINCT FROM 'string' OR (band->>'points' ~ '^(0|[1-9][0-9]*)(\.[0-9]+)?$') IS NOT TRUE
  OR (band->>'points')::numeric>maximum OR strpos(joined,band->>'description')=0
  OR NOT design.bid_requirement_uuid_array(band->'evidence_ids') OR jsonb_array_length(band->'evidence_ids')=0
  OR NOT ((band->'evidence_ids')<@refs) THEN
   RAISE EXCEPTION 'package_rule_correction_band_unquoted' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN jsonb_build_object('id',target_id,'bid_id',bid,'rule_set_id',target_set,
 'kind',input->'kind','statement',input->'statement','conditions',input->'conditions','exceptions',input->'exceptions',
 'max_points',CASE WHEN maximum IS NULL THEN 'null'::jsonb ELSE to_jsonb(maximum::text) END,
 'evidence_ids',refs,'bands',input->'bands','applicability_scope',input->'scope',
 'origin_kind','human_added','manual_origin_rule_id',target_id,'provenance_status','effective');
END $$;

CREATE FUNCTION package_rule_correction_check(identity uuid) RETURNS void LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE r design.bid_package_rule_corrections; b design.bid_package_requirement_inventories; root design.bid_package_requirement_inventories;
 result_inv design.bid_package_requirement_inventories; prev design.bid_package_rule_corrections; base_set design.rule_sets; result_set design.rule_sets;
 m jsonb; x jsonb; change jsonb; binding jsonb; old jsonb; expected jsonb; actual jsonb; actual_rules jsonb;
 quotes jsonb; changes jsonb='[]'; mappings jsonb; additions jsonb; new_ids jsonb='[]'; seen jsonb='[]'; new_id uuid;
 before_value jsonb; after_value jsonb; quoted_ids jsonb; current_decision uuid; decision jsonb; decision_ref jsonb;
 body jsonb; preview jsonb; counts jsonb; limits jsonb; previous jsonb; request_digest text; kind text;
 i integer; added integer=0; replaced integer=0; withdrawn integer=0; active integer; carry_count integer=0;
 carry record; command record; state text;
BEGIN
 SELECT * INTO r FROM design.bid_package_rule_corrections WHERE id=identity;
 IF NOT FOUND THEN RAISE EXCEPTION 'package_rule_correction_missing' USING ERRCODE='23514'; END IF;
 SELECT * INTO b FROM design.bid_package_requirement_inventories WHERE id=r.base_inventory_id AND bid_id=r.bid_id;
 SELECT * INTO root FROM design.bid_package_requirement_inventories WHERE id=r.root_inventory_id AND bid_id=r.bid_id;
 SELECT * INTO result_inv FROM design.bid_package_requirement_inventories WHERE id=r.result_inventory_id AND bid_id=r.bid_id;
 SELECT * INTO base_set FROM design.rule_sets WHERE id=r.base_rule_set_id AND bid_id=r.bid_id;
 SELECT * INTO result_set FROM design.rule_sets WHERE id=r.result_rule_set_id AND bid_id=r.bid_id;
 m=r.manifest;
 IF b.id IS NULL OR root.id IS NULL OR result_inv.id IS NULL OR base_set.id IS NULL OR result_set.id IS NULL
 OR b.manifest->>'version' NOT IN('bid-package-requirements/2','bid-package-requirements/3')
 OR root.manifest->>'version' IS DISTINCT FROM 'bid-package-requirements/2'
 OR root.authority_revision_id<>b.authority_revision_id OR root.manifest->>'identity_digest' IS DISTINCT FROM b.manifest->>'identity_digest'
 OR b.package_id<>r.package_id OR b.target_revision_id<>r.revision_id OR b.rule_set_id<>r.base_rule_set_id
 OR result_inv.package_id<>r.package_id OR result_inv.target_revision_id<>r.revision_id OR result_inv.rule_set_id<>r.result_rule_set_id
 OR result_inv.revision<>b.revision+1 OR result_inv.predecessor_digest<>b.digest
 OR base_set.material_id<>result_set.material_id OR base_set.coverage<>result_set.coverage
 OR result_set.revision<=base_set.revision
 OR result_inv.manifest->'source_snapshot' IS DISTINCT FROM b.manifest->'source_snapshot'
 OR result_inv.manifest->>'version' IS DISTINCT FROM 'bid-package-requirements/3'
 OR result_inv.manifest->>'rule_set_digest' IS DISTINCT FROM result_set.digest::text
 OR result_inv.actor_id<>r.actor_id THEN
  RAISE EXCEPTION 'package_rule_correction_base_binding' USING ERRCODE='23514'; END IF;
 IF NOT design.package_json_keys(m,ARRAY['version','id','scope','base','authority','extraction_basis','previous','sequence_no','policy_digest','request','request_digest','source_snapshot_digest','preview_digest','actor_id','command_id','created_at','result','mappings','additions','decision_bindings'])
 OR m->>'version' IS DISTINCT FROM 'package-rule-correction/1' OR m->>'id' IS DISTINCT FROM r.id::text
 OR m->>'actor_id' IS DISTINCT FROM r.actor_id::text OR m->>'command_id' IS DISTINCT FROM r.command_id::text
 OR (m->>'created_at')::timestamptz IS DISTINCT FROM r.created_at
 OR m->'scope' IS DISTINCT FROM jsonb_build_object('bid_id',r.bid_id,'package_id',r.package_id,'revision_id',r.revision_id,'inventory_id',r.base_inventory_id)
 OR m->'base' IS DISTINCT FROM jsonb_build_object('inventory_digest',b.digest,'rule_set_id',b.rule_set_id,'rule_set_digest',base_set.digest)
 OR m->'authority' IS DISTINCT FROM jsonb_build_object('revision_id',b.authority_revision_id,'digest',b.manifest->'authority_digest','identity_digest',b.manifest->'identity_digest')
 OR m->'extraction_basis' IS DISTINCT FROM design.package_rule_root_basis(root.manifest,root.digest)
 OR m->'extraction_basis' IS DISTINCT FROM design.package_rule_root_basis(b.manifest,b.digest)
 OR result_inv.manifest->'extraction_basis' IS DISTINCT FROM m->'extraction_basis'
 OR m->>'source_snapshot_digest' IS DISTINCT FROM design.package_rule_json_digest(b.manifest->'source_snapshot')
 OR (m->>'policy_digest' ~ '^[a-f0-9]{64}$') IS NOT TRUE OR (m->>'preview_digest' ~ '^[a-f0-9]{64}$') IS NOT TRUE
 OR (m->>'sequence_no')::integer<>r.sequence_no
 THEN RAISE EXCEPTION 'package_rule_correction_shape' USING ERRCODE='23514'; END IF;
 previous='null'::jsonb;
 IF r.previous_id IS NOT NULL THEN
  SELECT * INTO prev FROM design.bid_package_rule_corrections WHERE id=r.previous_id AND bid_id=r.bid_id;
  IF prev.id IS NULL OR prev.sequence_no+1<>r.sequence_no OR prev.result_rule_set_id<>r.base_rule_set_id
  OR prev.root_inventory_id<>r.root_inventory_id OR prev.manifest->'authority' IS DISTINCT FROM m->'authority' THEN
   RAISE EXCEPTION 'package_rule_correction_chain' USING ERRCODE='23514'; END IF;
  previous=jsonb_build_object('id',prev.id,'digest',prev.digest);
  IF b.manifest->'human_derivation' IS DISTINCT FROM jsonb_build_object('version','package-rule-derivation/1','head_id',prev.id,'head_digest',prev.digest,'length',prev.sequence_no) THEN
   RAISE EXCEPTION 'package_rule_correction_chain' USING ERRCODE='23514'; END IF;
 ELSIF b.id<>root.id OR r.sequence_no<>1 THEN
  RAISE EXCEPTION 'package_rule_correction_root' USING ERRCODE='23514';
 END IF;
 IF m->'previous' IS DISTINCT FROM previous
 OR result_inv.manifest->'human_derivation' IS DISTINCT FROM jsonb_build_object('version','package-rule-derivation/1','head_id',r.id,'head_digest',r.digest,'length',r.sequence_no)
 THEN RAISE EXCEPTION 'package_rule_correction_chain' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM design.bid_package_requirement_extraction_runs e
 JOIN design.operations o ON o.id=e.operation_id AND o.bid_id=e.bid_id
 JOIN design.effect_receipts f ON f.operation_id=o.id AND f.effect_key='extract-rules'
 WHERE e.id::text=root.manifest->>'extraction_result_id' AND e.bid_id=r.bid_id
 AND e.rule_set_id=root.rule_set_id AND e.authority_revision_id=b.authority_revision_id
 AND e.authority_digest::text=root.manifest->>'authority_digest'
 AND e.input_digest::text=root.manifest->>'extraction_input_digest'
 AND e.result_digest::text=root.manifest->>'extraction_result_digest'
 AND e.result->>'extraction_coverage'=root.manifest->>'extraction_coverage'
 AND e.result->>'quality_status'='not_measured' AND e.result->>'range_status'='all_frozen_evidence_submitted'
 AND o.state='succeeded' AND o.handler_version='prepare/1' AND o.input_digest=e.operation_input_digest
 AND f.result->>'result_ref'=root.rule_set_id::text AND f.result->>'extraction_input_digest'=e.input_digest::text
 AND f.result->>'method_digest'=e.result->>'method_digest') THEN
  RAISE EXCEPTION 'package_rule_correction_extraction_root' USING ERRCODE='23514'; END IF;
 body=m->'request';
 IF NOT design.package_json_keys(body,ARRAY['base_inventory_digest','base_rule_set_digest','reason','changes'])
 OR body->>'base_inventory_digest' IS DISTINCT FROM b.digest::text OR body->>'base_rule_set_digest' IS DISTINCT FROM base_set.digest::text
 OR NOT design.package_rule_text(body->'reason',2000) OR length(body->>'reason')>2000 OR btrim(body->>'reason')='' OR btrim(body->>'reason')<>body->>'reason'
 OR jsonb_typeof(body->'changes') IS DISTINCT FROM 'array' OR jsonb_array_length(body->'changes') NOT BETWEEN 1 AND 100
 OR octet_length(convert_to(design.package_canonical_json(body),'UTF8'))>1048576
 OR m->>'request_digest' IS DISTINCT FROM design.package_rule_json_digest(body)
 OR jsonb_typeof(m->'mappings') IS DISTINCT FROM 'array' OR jsonb_typeof(m->'additions') IS DISTINCT FROM 'array'
 OR jsonb_typeof(m->'decision_bindings') IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'package_rule_correction_request' USING ERRCODE='23514'; END IF;
 mappings=m->'mappings'; additions=m->'additions';
 IF jsonb_array_length(mappings)<>jsonb_array_length(b.manifest->'requirements')
 OR jsonb_array_length(mappings)<>(SELECT count(DISTINCT v->>'from_rule_id') FROM jsonb_array_elements(mappings) x(v))
 OR (SELECT count(*) FROM design.rule_items WHERE rule_set_id=r.base_rule_set_id)<>jsonb_array_length(mappings)
 OR jsonb_array_length(mappings)+jsonb_array_length(additions)>10000 THEN
  RAISE EXCEPTION 'package_rule_correction_missing_rows' USING ERRCODE='23514'; END IF;
 FOR x IN SELECT v FROM jsonb_array_elements(mappings) q(v) LOOP
  IF NOT design.package_json_keys(x,ARRAY['from_rule_id','from_rule_digest','to_rule_id','to_rule_digest','op','change_index']) THEN
   RAISE EXCEPTION 'package_rule_correction_mapping_shape' USING ERRCODE='23514'; END IF;
  SELECT v INTO binding FROM jsonb_array_elements(b.manifest->'requirements') q(v) WHERE v->>'rule_id'=x->>'from_rule_id';
  SELECT to_jsonb(q)||jsonb_build_object('max_points',q.max_points::text) INTO old FROM design.rule_items q
   WHERE q.id::text=x->>'from_rule_id' AND q.rule_set_id=r.base_rule_set_id AND q.bid_id=r.bid_id;
  SELECT to_jsonb(q)||jsonb_build_object('max_points',q.max_points::text) INTO actual FROM design.rule_items q
   WHERE q.id::text=x->>'to_rule_id' AND q.rule_set_id=r.result_rule_set_id AND q.bid_id=r.bid_id;
  IF binding IS NULL OR old IS NULL OR actual IS NULL OR old IS DISTINCT FROM binding->'rule_snapshot'
  OR x->>'from_rule_digest' IS DISTINCT FROM design.package_rule_json_digest(old)
  OR x->>'to_rule_digest' IS DISTINCT FROM design.package_rule_json_digest(actual) THEN
   RAISE EXCEPTION 'package_rule_correction_mapping_binding' USING ERRCODE='23514'; END IF;
  new_id=(x->>'to_rule_id')::uuid; new_ids=new_ids||jsonb_build_array(new_id);
  expected=old||jsonb_build_object('id',new_id,'rule_set_id',r.result_rule_set_id);
  IF old->>'origin_kind'<>'model_extracted' THEN expected=expected||jsonb_build_object('origin_kind','carried_human'); END IF;
  IF x->>'op'='carry' THEN
   IF x->'change_index' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'package_rule_correction_mapping_shape' USING ERRCODE='23514'; END IF;
   carry_count=carry_count+1;
  ELSIF x->>'op' IN('replace','withdraw') THEN
   i=(x->>'change_index')::integer; change=body->'changes'->i;
   IF change IS NULL OR old->>'provenance_status'<>'effective' OR change->>'op' IS DISTINCT FROM x->>'op'
   OR change->>'rule_id' IS DISTINCT FROM x->>'from_rule_id' OR change->>'rule_digest' IS DISTINCT FROM x->>'from_rule_digest'
   THEN RAISE EXCEPTION 'package_rule_correction_mapping_change' USING ERRCODE='23514'; END IF;
   IF x->>'op'='withdraw' THEN expected=expected||jsonb_build_object('provenance_status','superseded');
   ELSE expected=design.package_rule_expected(r.bid_id,r.result_rule_set_id,new_id,change->'rule'); END IF;
  ELSE RAISE EXCEPTION 'package_rule_correction_mapping_shape' USING ERRCODE='23514'; END IF;
  IF expected IS DISTINCT FROM actual THEN RAISE EXCEPTION 'package_rule_correction_changed_unselected' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR x IN SELECT v FROM jsonb_array_elements(additions) q(v) LOOP
  IF NOT design.package_json_keys(x,ARRAY['change_index','to_rule_id','to_rule_digest']) THEN RAISE EXCEPTION 'package_rule_correction_addition_shape' USING ERRCODE='23514'; END IF;
  i=(x->>'change_index')::integer; change=body->'changes'->i; new_id=(x->>'to_rule_id')::uuid;
  IF change->>'op' IS DISTINCT FROM 'add' THEN RAISE EXCEPTION 'package_rule_correction_addition_shape' USING ERRCODE='23514'; END IF;
  expected=design.package_rule_expected(r.bid_id,r.result_rule_set_id,new_id,change->'rule');
  SELECT to_jsonb(q)||jsonb_build_object('max_points',q.max_points::text) INTO actual FROM design.rule_items q WHERE q.id=new_id AND q.rule_set_id=r.result_rule_set_id AND q.bid_id=r.bid_id;
  IF actual IS DISTINCT FROM expected OR x->>'to_rule_digest' IS DISTINCT FROM design.package_rule_json_digest(actual) THEN
   RAISE EXCEPTION 'package_rule_correction_addition_binding' USING ERRCODE='23514'; END IF;
  new_ids=new_ids||jsonb_build_array(new_id);
 END LOOP;
 IF jsonb_array_length(new_ids)<>(SELECT count(DISTINCT v) FROM jsonb_array_elements(new_ids) x(v))
 OR jsonb_array_length(new_ids)<>(SELECT count(*) FROM design.rule_items WHERE rule_set_id=r.result_rule_set_id) THEN
  RAISE EXCEPTION 'package_rule_correction_missing_rows' USING ERRCODE='23514'; END IF;
 FOR change,i IN SELECT v,n::integer-1 FROM jsonb_array_elements(body->'changes') WITH ORDINALITY q(v,n) LOOP
  kind=change->>'op'; before_value='null'::jsonb;
  IF kind='add' THEN
   IF NOT design.package_json_keys(change,ARRAY['op','rule']) THEN RAISE EXCEPTION 'package_rule_correction_request' USING ERRCODE='23514'; END IF;
   SELECT v INTO x FROM jsonb_array_elements(additions) q(v) WHERE (v->>'change_index')::integer=i;
   IF x IS NULL OR (SELECT count(*) FROM jsonb_array_elements(additions) q(v) WHERE (v->>'change_index')::integer=i)<>1 THEN RAISE EXCEPTION 'package_rule_correction_missing_change' USING ERRCODE='23514'; END IF;
   added=added+1;
  ELSE
   IF (kind='replace' AND NOT design.package_json_keys(change,ARRAY['op','rule_id','rule_digest','rule']))
   OR (kind='withdraw' AND NOT design.package_json_keys(change,ARRAY['op','rule_id','rule_digest','evidence_quotes']))
   OR kind NOT IN('replace','withdraw') OR seen ? (change->>'rule_id') THEN
    RAISE EXCEPTION 'package_rule_correction_request' USING ERRCODE='23514'; END IF;
   seen=seen||jsonb_build_array(change->>'rule_id');
   SELECT v INTO x FROM jsonb_array_elements(mappings) q(v) WHERE (v->>'change_index')::integer=i;
   IF x IS NULL OR (SELECT count(*) FROM jsonb_array_elements(mappings) q(v) WHERE (v->>'change_index')::integer=i)<>1 THEN RAISE EXCEPTION 'package_rule_correction_missing_change' USING ERRCODE='23514'; END IF;
   SELECT v->'rule_snapshot' INTO old FROM jsonb_array_elements(b.manifest->'requirements') q(v) WHERE v->>'rule_id'=change->>'rule_id';
   before_value=design.package_rule_semantic(old);
   IF kind='replace' THEN replaced=replaced+1; ELSE withdrawn=withdrawn+1; END IF;
  END IF;
  SELECT to_jsonb(q)||jsonb_build_object('max_points',q.max_points::text) INTO actual FROM design.rule_items q WHERE q.id::text=x->>'to_rule_id' AND q.rule_set_id=r.result_rule_set_id;
  after_value=design.package_rule_semantic(actual);
  quotes=design.package_rule_quote_guard(r.bid_id,b.authority_revision_id,CASE WHEN kind='withdraw' THEN change->'evidence_quotes' ELSE change#>'{rule,evidence_quotes}' END);
  changes=changes||jsonb_build_array(jsonb_build_object('index',i,'op',kind,'rule_id',change->'rule_id','rule_digest',change->'rule_digest','before',before_value,'after',after_value,'quotes',quotes));
 END LOOP;
 SELECT coalesce(jsonb_agg(to_jsonb(q)||jsonb_build_object('max_points',q.max_points::text) ORDER BY q.kind,q.id),'[]'),count(*) FILTER(WHERE q.provenance_status='effective')
 INTO actual_rules,active FROM design.rule_items q WHERE q.rule_set_id=r.result_rule_set_id;
 counts=jsonb_build_object('before',jsonb_array_length(mappings),'after',jsonb_array_length(actual_rules),'carried',carry_count,'added',added,'replaced',replaced,'withdrawn',withdrawn,'active_after',active);
 limits='["INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED","HUMAN_INTERPRETATION_NOT_AUTHORITY_AMENDMENT","ORIGINAL_BYTES_NOT_VERIFIED_BY_PREVIEW"]';
 IF m#>>'{extraction_basis,extraction_coverage}'<>'complete' THEN limits=limits||jsonb_build_array('ROOT_EXTRACTION_'||upper(m#>>'{extraction_basis,extraction_coverage}')); END IF;
 preview=(m-ARRAY['id','preview_digest','actor_id','command_id','created_at','result','mappings','additions','decision_bindings'])||
 jsonb_build_object('version','package-rule-correction-preview/1','changes',changes,'counts',counts,'limitations',limits,'inventory_complete',false,'review_ready',false,'original_bytes_verified',false);
 IF m->>'preview_digest' IS DISTINCT FROM design.package_rule_json_digest(preview)
 OR octet_length(convert_to(design.package_canonical_json(preview),'UTF8'))>4194304
 OR m->'result' IS DISTINCT FROM jsonb_build_object('inventory_id',r.result_inventory_id,'rule_set_id',r.result_rule_set_id,'rule_set_digest',result_set.digest,'rule_count',jsonb_array_length(actual_rules),'rules_digest',design.package_rule_json_digest(actual_rules))
 OR result_set.digest::text IS DISTINCT FROM design.package_rule_json_digest(jsonb_build_object('version','package-human-rule-set/1','base',m->'base','authority',m->'authority','preview_digest',m->'preview_digest','rule_set_id',r.result_rule_set_id,'rules_digest',design.package_rule_json_digest(actual_rules)))
 THEN RAISE EXCEPTION 'package_rule_correction_preview_binding' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM jsonb_array_elements(actual_rules) x(v) WHERE v->>'provenance_status'='effective')<>(SELECT count(DISTINCT design.package_rule_json_digest((design.package_rule_semantic(v)-ARRAY['provenance_status','evidence_ids'])||jsonb_build_object('evidence_ids',(SELECT jsonb_agg(e ORDER BY e) FROM jsonb_array_elements(v->'evidence_ids') q(e))))) FROM jsonb_array_elements(actual_rules) x(v) WHERE v->>'provenance_status'='effective') THEN
  RAISE EXCEPTION 'package_rule_correction_duplicate_rule' USING ERRCODE='23514'; END IF;
 IF jsonb_array_length(m->'decision_bindings')<>(SELECT count(DISTINCT v->>'rule_id') FROM jsonb_array_elements(m->'decision_bindings') x(v))
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(m->'decision_bindings') z(v) WHERE NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements(mappings||additions) y(v) WHERE y.v->>'to_rule_id'=z.v->>'rule_id')) THEN
  RAISE EXCEPTION 'package_rule_correction_decision_binding' USING ERRCODE='23514'; END IF;
 FOR x IN SELECT value FROM jsonb_array_elements(mappings||additions) LOOP
  SELECT v INTO decision_ref FROM jsonb_array_elements(m->'decision_bindings') q(v) WHERE v->>'rule_id'=x->>'to_rule_id';
  -- Historical derivations bind their original decision, never a later head.
  current_decision=(decision_ref->>'decision_id')::uuid;
  IF x->>'op'='carry' THEN
   SELECT v INTO binding FROM jsonb_array_elements(b.manifest->'requirements') q(v) WHERE v->>'rule_id'=x->>'from_rule_id';
   IF binding->'decision_id'='null'::jsonb THEN
    IF decision_ref IS NOT NULL OR current_decision IS NOT NULL
    OR EXISTS(SELECT 1 FROM design.rule_carryovers WHERE new_rule_id::text=x->>'to_rule_id')
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(result_inv.manifest->'requirements') z(v) WHERE v->>'rule_id'=x->>'to_rule_id' AND v->'decision_snapshot' IS DISTINCT FROM 'null'::jsonb)
    THEN RAISE EXCEPTION 'package_rule_correction_invented_decision' USING ERRCODE='23514'; END IF;
    CONTINUE;
   END IF;
   SELECT * INTO carry FROM design.rule_carryovers WHERE new_rule_id::text=x->>'to_rule_id' AND bid_id=r.bid_id;
   IF carry.new_rule_id IS NULL OR carry.from_rule_id::text IS DISTINCT FROM x->>'from_rule_id'
   OR carry.from_decision_id::text IS DISTINCT FROM binding->>'decision_id'
   OR decision_ref->>'mode' IS DISTINCT FROM 'carried'
   OR carry.equivalence_digest::text IS DISTINCT FROM design.package_rule_json_digest(jsonb_build_object('version','package-rule-carryover/1','from_rule_id',x->'from_rule_id','from_rule_digest',x->'from_rule_digest','to_rule_id',x->'to_rule_id','to_rule_digest',x->'to_rule_digest','decision_id',binding->'decision_id','authority_digest',m#>'{authority,digest}','source_snapshot_digest',m->'source_snapshot_digest')) THEN
    RAISE EXCEPTION 'package_rule_correction_carryover' USING ERRCODE='23514'; END IF;
  END IF;
  SELECT to_jsonb(d) INTO decision FROM design.decisions d WHERE d.id=current_decision AND d.bid_id=r.bid_id;
  IF decision IS NULL OR NOT design.package_json_keys(decision_ref,ARRAY['rule_id','decision_id','decision_digest','mode'])
  OR decision_ref->>'decision_id' IS DISTINCT FROM current_decision::text OR decision_ref->>'decision_digest' IS DISTINCT FROM design.package_rule_json_digest(decision) THEN
   RAISE EXCEPTION 'package_rule_correction_decision_binding' USING ERRCODE='23514'; END IF;
  IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(result_inv.manifest->'requirements') z(v)
    WHERE v->>'rule_id'=x->>'to_rule_id' AND v->>'decision_id'=current_decision::text AND v->'decision_snapshot'=decision) THEN
   RAISE EXCEPTION 'package_rule_correction_decision_binding' USING ERRCODE='23514'; END IF;
  IF x->>'op'='carry' THEN
   IF decision IS DISTINCT FROM binding->'decision_snapshot' THEN RAISE EXCEPTION 'package_rule_correction_carryover' USING ERRCODE='23514'; END IF;
  ELSE
   i=(x->>'change_index')::integer; change=body->'changes'->i; kind=change->>'op';
   SELECT jsonb_agg(id ORDER BY first) INTO quoted_ids FROM (
    SELECT q->>'evidence_id' AS id,min(n) AS first FROM jsonb_array_elements(CASE WHEN kind='withdraw' THEN change->'evidence_quotes' ELSE change#>'{rule,evidence_quotes}' END) WITH ORDINALITY z(q,n) GROUP BY q->>'evidence_id') q;
   state=CASE WHEN kind='withdraw' THEN 'rejected' ELSE 'confirmed' END;
   IF decision->>'object_kind' IS DISTINCT FROM 'rule' OR decision->>'object_id' IS DISTINCT FROM x->>'to_rule_id'
   OR decision->>'actor_id' IS DISTINCT FROM r.actor_id::text OR decision->>'decision' IS DISTINCT FROM state
   OR decision_ref->>'mode' IS DISTINCT FROM state OR decision->'object_revision' IS DISTINCT FROM '1'::jsonb
   OR decision->'reason' IS DISTINCT FROM body->'reason' OR decision->'evidence_ids' IS DISTINCT FROM quoted_ids
   OR EXISTS(SELECT 1 FROM design.rule_carryovers WHERE new_rule_id::text=x->>'to_rule_id')
   OR NOT EXISTS(SELECT 1 FROM design.audit_entries a WHERE a.command_id=r.command_id AND a.bid_id=r.bid_id AND a.actor_id=r.actor_id
    AND a.event_type='human.decision_recorded' AND a.payload->>'decision_id'=current_decision::text
    AND a.payload->'basis'=jsonb_build_object('package_rule_correction_preview_digest',m->'preview_digest','authority',m->'authority','rule_digest',x->'to_rule_digest','change_index',i,'operation',kind)) THEN
    RAISE EXCEPTION 'package_rule_correction_human_decision' USING ERRCODE='23514'; END IF;
  END IF;
 END LOOP;
 SELECT * INTO command FROM design.commands WHERE id=r.command_id;
 expected=jsonb_build_object('request',body,'preview_digest',m->'preview_digest');
 request_digest=design.package_rule_json_digest(jsonb_build_object('body',jsonb_build_object('scope',jsonb_build_array(r.bid_id,r.package_id,r.revision_id,r.base_inventory_id))||expected,
  'if_match','"requirement-inventory:'||r.revision_id::text||':'||b.digest::text||'"'));
 IF command.id IS NULL OR command.actor_id<>r.actor_id OR command.command_kind<>'package-rule-correction-apply'
 OR command.target_id<>r.base_inventory_id OR command.request_digest<>request_digest
 OR command.response IS DISTINCT FROM jsonb_build_object('body',jsonb_build_object('correction',jsonb_build_object('manifest',m,'digest',r.digest),
 'inventory',jsonb_build_object('manifest',result_inv.manifest,'digest',result_inv.digest),'command',jsonb_build_object('command_id',r.command_id,'actor_id',r.actor_id,'idempotency_key',command.idempotency_key,'request_digest',request_digest,'request',expected,'if_match','"requirement-inventory:'||r.revision_id::text||':'||b.digest::text||'"')),
 'status',201,'headers',jsonb_build_object('ETag','"requirement-inventory:'||r.revision_id::text||':'||result_inv.digest::text||'"')) THEN
  RAISE EXCEPTION 'package_rule_correction_ack' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM design.audit_entries WHERE command_id=r.command_id AND event_type='package.rules_corrected')<>1
 OR NOT EXISTS(SELECT 1 FROM design.audit_entries a WHERE a.command_id=r.command_id AND a.bid_id=r.bid_id AND a.actor_id=r.actor_id AND a.event_type='package.rules_corrected'
  AND a.payload=jsonb_build_object('correction_id',r.id,'digest',r.digest,'inventory_id',r.result_inventory_id)) THEN
  RAISE EXCEPTION 'package_rule_correction_audit' USING ERRCODE='23514'; END IF;
END $$;

CREATE FUNCTION package_rule_inventory_derivation_check(inventory uuid) RETURNS void LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE inv design.bid_package_requirement_inventories; root design.bid_package_requirement_inventories; head design.bid_package_rule_corrections;
 item record; depth integer=0; total bigint=0; actual jsonb; expected jsonb; prior uuid; extra bigint;
BEGIN
 SELECT * INTO inv FROM design.bid_package_requirement_inventories WHERE id=inventory;
 IF inv.manifest->>'version'<>'bid-package-requirements/3' THEN RETURN; END IF;
 IF inv.manifest->>'extraction_binding'<>'frozen_extraction_plus_human_derivation'
 OR NOT design.package_json_keys(inv.manifest->'human_derivation',ARRAY['version','head_id','head_digest','length'])
 OR inv.manifest#>>'{human_derivation,version}' IS DISTINCT FROM 'package-rule-derivation/1' THEN
  RAISE EXCEPTION 'package_rule_correction_inventory_shape' USING ERRCODE='23514'; END IF;
 SELECT * INTO head FROM design.bid_package_rule_corrections WHERE id::text=inv.manifest#>>'{human_derivation,head_id}' AND bid_id=inv.bid_id;
 SELECT * INTO root FROM design.bid_package_requirement_inventories WHERE id::text=inv.manifest#>>'{extraction_basis,inventory_id}' AND bid_id=inv.bid_id;
 IF head.id IS NULL OR root.id IS NULL OR head.result_rule_set_id<>inv.rule_set_id
 OR head.digest::text IS DISTINCT FROM inv.manifest#>>'{human_derivation,head_digest}'
 OR head.sequence_no::text IS DISTINCT FROM inv.manifest#>>'{human_derivation,length}'
 OR head.manifest->'extraction_basis' IS DISTINCT FROM inv.manifest->'extraction_basis'
 OR head.manifest->'authority' IS DISTINCT FROM jsonb_build_object('revision_id',inv.authority_revision_id,'digest',inv.manifest->'authority_digest','identity_digest',inv.manifest->'identity_digest')
 OR root.manifest->>'version'<>'bid-package-requirements/2'
 OR (SELECT manifest->'scope' FROM design.bid_package_revisions WHERE id=root.target_revision_id) IS DISTINCT FROM (SELECT manifest->'scope' FROM design.bid_package_revisions WHERE id=inv.target_revision_id) THEN
  RAISE EXCEPTION 'package_rule_correction_inventory_binding' USING ERRCODE='23514'; END IF;
 SELECT coalesce(jsonb_agg(to_jsonb(r)||jsonb_build_object('max_points',r.max_points::text) ORDER BY r.kind,r.id),'[]') INTO actual FROM design.rule_items r WHERE rule_set_id=inv.rule_set_id;
 SELECT coalesce(jsonb_agg(v->'rule_snapshot' ORDER BY v#>>'{rule_snapshot,kind}',v->>'rule_id'),'[]') INTO expected FROM jsonb_array_elements(inv.manifest->'requirements') x(v);
 IF actual IS DISTINCT FROM expected OR design.package_rule_json_digest(actual) IS DISTINCT FROM head.manifest#>>'{result,rules_digest}' THEN
  RAISE EXCEPTION 'package_rule_correction_inventory_rules' USING ERRCODE='23514'; END IF;
 total=octet_length(convert_to(design.package_canonical_json(jsonb_build_object('root_inventory',jsonb_build_object('manifest',root.manifest,'digest',root.digest),'steps','[]'::jsonb)),'UTF8'));
 prior=head.id;
 WHILE prior IS NOT NULL LOOP
  depth=depth+1;
  IF depth>32 THEN RAISE EXCEPTION 'package_rule_correction_chain_limit' USING ERRCODE='23514'; END IF;
  SELECT * INTO item FROM design.bid_package_rule_corrections WHERE id=prior AND bid_id=inv.bid_id;
  IF item.id IS NULL THEN RAISE EXCEPTION 'package_rule_correction_chain' USING ERRCODE='23514'; END IF;
  SELECT total+octet_length(convert_to(design.package_canonical_json(jsonb_build_object(
   'manifest',item.manifest,'digest',item.digest,'base_inventory',jsonb_build_object('manifest',i.manifest,'digest',i.digest),
   'result_rules','[]'::jsonb,'decisions','[]'::jsonb,'carryovers','[]'::jsonb)),'UTF8'))+(depth>1)::integer
   INTO total FROM design.bid_package_requirement_inventories i WHERE i.id=item.base_inventory_id;
  SELECT coalesce(sum(octet_length(convert_to(design.package_canonical_json(to_jsonb(q)||jsonb_build_object('max_points',q.max_points::text)),'UTF8'))),0)+greatest(count(*)-1,0)
   INTO extra FROM design.rule_items q WHERE q.rule_set_id=item.result_rule_set_id;
  total=total+extra;
  SELECT coalesce(sum(octet_length(convert_to(design.package_canonical_json(to_jsonb(d)),'UTF8'))),0)+greatest(count(*)-1,0)
   INTO extra FROM design.decisions d WHERE d.bid_id=inv.bid_id AND d.id::text IN(SELECT v->>'decision_id' FROM jsonb_array_elements(item.manifest->'decision_bindings') x(v));
  total=total+extra;
  SELECT coalesce(sum(octet_length(convert_to(design.package_canonical_json(to_jsonb(co)),'UTF8'))),0)+greatest(count(*)-1,0)
   INTO extra FROM design.rule_carryovers co JOIN design.rule_items q ON q.id=co.new_rule_id WHERE q.rule_set_id=item.result_rule_set_id;
  total=total+extra;
  IF total>67108864 THEN RAISE EXCEPTION 'package_rule_correction_chain_limit' USING ERRCODE='23514'; END IF;
  PERFORM design.package_rule_correction_check(item.id);
  prior=item.previous_id;
 END LOOP;
 IF depth<>head.sequence_no OR total>67108864 THEN RAISE EXCEPTION 'package_rule_correction_chain_limit' USING ERRCODE='23514'; END IF;
END $$;

CREATE FUNCTION package_rule_correction_deferred() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE row record; current_id uuid;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'package_rule_correction_requires_read_committed' USING ERRCODE='25001'; END IF;
 IF TG_TABLE_NAME='bid_package_requirement_inventories' THEN
  PERFORM design.package_rule_inventory_derivation_check(NEW.id);
 ELSE
  PERFORM id FROM design.bids WHERE id=NEW.bid_id FOR UPDATE;
  PERFORM pg_advisory_xact_lock(90127,1);
  FOR row IN SELECT q.rule_id,q.decision_id FROM design.bid_package_requirements q WHERE q.inventory_id=NEW.base_inventory_id LOOP
   SELECT coalesce(h.decision_id,co.from_decision_id) INTO current_id FROM design.rule_items r
    LEFT JOIN design.decision_heads h ON h.bid_id=r.bid_id AND h.object_kind='rule' AND h.object_id=r.id
    LEFT JOIN design.rule_carryovers co ON co.new_rule_id=r.id WHERE r.id=row.rule_id;
   IF current_id IS DISTINCT FROM row.decision_id THEN RAISE EXCEPTION 'package_rule_correction_decision_changed' USING ERRCODE='23514'; END IF;
  END LOOP;
  PERFORM design.package_rule_correction_check(NEW.id);
  IF EXISTS(SELECT 1 FROM design.bid_package_members m JOIN design.bid_package_requirement_inventories i ON i.authority_revision_id=m.revision_id
    WHERE i.id=NEW.result_inventory_id AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(i.manifest->'source_snapshot') s
      WHERE s->>'document_version_id'=m.document_version_id::text)) THEN
   RAISE EXCEPTION 'package_rule_correction_source_unproven' USING ERRCODE='23514'; END IF;
  PERFORM design.bid_requirement_final_recheck(NEW.result_inventory_id);
 END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER rule_correction_complete AFTER INSERT ON bid_package_rule_corrections
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION package_rule_correction_deferred();
CREATE CONSTRAINT TRIGGER rule_inventory_derivation_complete AFTER INSERT ON bid_package_requirement_inventories
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION package_rule_correction_deferred();

REVOKE ALL ON bid_package_rule_corrections FROM PUBLIC,tender_worker;
GRANT SELECT,INSERT ON bid_package_rule_corrections TO tender_api;
GRANT SELECT ON bid_package_rule_corrections TO tender_worker;
REVOKE ALL ON bid_package_rule_correction_command_receipts FROM PUBLIC;
GRANT SELECT ON bid_package_rule_correction_command_receipts TO tender_api,tender_worker;
REVOKE ALL ON FUNCTION package_rule_json_digest(jsonb),package_rule_text(jsonb,integer),package_rule_semantic(jsonb),package_rule_root_basis(jsonb,text),
 package_rule_quote_guard(uuid,uuid,jsonb),package_rule_expected(uuid,uuid,uuid,jsonb),package_rule_correction_check(uuid),
 package_rule_inventory_derivation_check(uuid),package_rule_correction_deferred() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION package_rule_json_digest(jsonb),package_rule_text(jsonb,integer),package_rule_semantic(jsonb),package_rule_root_basis(jsonb,text),
 package_rule_quote_guard(uuid,uuid,jsonb),package_rule_expected(uuid,uuid,uuid,jsonb),package_rule_correction_check(uuid),
 package_rule_inventory_derivation_check(uuid),package_rule_correction_deferred() TO tender_api;

-- A v3 human derivation may only carry the explicit /2 row-state projection.
-- Existing /1 plans retain their original protocol and admission semantics.
CREATE FUNCTION package_rule_dependency_state_guard(assessment jsonb,inventory jsonb) RETURNS void LANGUAGE plpgsql
 SET search_path=pg_catalog,design AS $$
DECLARE item jsonb; original jsonb; state text; n integer=0; active integer=0; inactive integer=0; revalidate integer=0;
BEGIN
 IF inventory->>'version'<>'bid-package-requirements/3' THEN
  IF assessment ? 'rule_state_counts' OR EXISTS(SELECT 1 FROM jsonb_array_elements(assessment->'requirements') x(v) WHERE v ? 'rule_status') THEN
   RAISE EXCEPTION 'dependency_plan_rule_state_shape' USING ERRCODE='23514'; END IF;
  RETURN;
 END IF;
 IF assessment->>'inventory_status' IS DISTINCT FROM 'human_derivation_range_quality_unmeasured'
 OR NOT design.package_json_keys(assessment->'rule_state_counts',ARRAY['total','active','inactive','needs_revalidation'])
 OR jsonb_array_length(assessment->'requirements')<>(SELECT count(DISTINCT v->>'requirement_id') FROM jsonb_array_elements(assessment->'requirements') x(v)) THEN
  RAISE EXCEPTION 'dependency_plan_rule_state_shape' USING ERRCODE='23514'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(assessment->'requirements') LOOP
  SELECT value INTO original FROM jsonb_array_elements(inventory->'requirements') WHERE value->>'rule_id'=item->>'requirement_id';
  IF original IS NULL OR item->>'requirement_digest' IS DISTINCT FROM original->>'requirement_digest' THEN
   RAISE EXCEPTION 'dependency_plan_rule_state_binding' USING ERRCODE='23514'; END IF;
  state=CASE original#>>'{rule_snapshot,provenance_status}' WHEN 'effective' THEN 'active' WHEN 'superseded' THEN 'inactive' ELSE 'needs_revalidation' END;
  IF item->>'rule_status' IS DISTINCT FROM state THEN RAISE EXCEPTION 'dependency_plan_rule_state_binding' USING ERRCODE='23514'; END IF;
  n=n+1; active=active+(state='active')::integer; inactive=inactive+(state='inactive')::integer; revalidate=revalidate+(state='needs_revalidation')::integer;
 END LOOP;
 IF assessment->'rule_state_counts' IS DISTINCT FROM jsonb_build_object('total',n,'active',active,'inactive',inactive,'needs_revalidation',revalidate) THEN
  RAISE EXCEPTION 'dependency_plan_rule_state_counts' USING ERRCODE='23514'; END IF;
END $$;
REVOKE ALL ON FUNCTION package_rule_dependency_state_guard(jsonb,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION package_rule_dependency_state_guard(jsonb,jsonb) TO tender_api;

CREATE OR REPLACE FUNCTION bid_dependency_plan_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,design AS $$
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
 OR a->>'version' IS DISTINCT FROM (CASE WHEN original.evidence_text::jsonb#>>'{selection,inventory,manifest,version}'='bid-package-requirements/3' THEN 'package-input-dependencies/2' ELSE 'package-input-dependencies/1' END) OR a->>'kind' IS DISTINCT FROM 'input_dependency_assessment'
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
 PERFORM design.package_rule_dependency_state_guard(a,original.evidence_text::jsonb#>'{selection,inventory,manifest}');
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
COMMIT;
