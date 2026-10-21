-- Optional read-only discovery after package-historical-research.sql.
-- No qualification check, label export, business write, or table SELECT grant.
BEGIN;

CREATE FUNCTION package_historical_research.assert_directory_reader() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
DECLARE who record; forbidden text;
BEGIN
 SELECT * INTO who FROM pg_roles WHERE rolname=session_user;
 IF who.rolsuper OR who.rolbypassrls OR who.rolcreatedb OR who.rolcreaterole OR who.rolreplication
 OR NOT who.rolcanlogin OR NOT pg_has_role(session_user,'tender_api','MEMBER')
 OR EXISTS(SELECT FROM pg_class WHERE relowner=who.oid AND relnamespace IN(to_regnamespace('design'),to_regnamespace('retrieval'),to_regnamespace('package_historical_research')))
 THEN RAISE EXCEPTION 'package_history_directory_role_denied' USING ERRCODE='42501'; END IF;
 FOREACH forbidden IN ARRAY ARRAY['tender_worker','tender_research_worker','tender_research_read','tender_score_read','tender_model_train','tender_model_evaluate','tender_model_score','tender_package_history_verify','tender_package_history_train','tender_package_history_evaluate'] LOOP
  IF pg_has_role(session_user,forbidden,'MEMBER') THEN RAISE EXCEPTION 'package_history_directory_mixed_role_denied' USING ERRCODE='42501'; END IF;
 END LOOP;
 IF current_setting('transaction_isolation')<>'repeatable read' OR current_setting('transaction_read_only')<>'on'
 THEN RAISE EXCEPTION 'package_history_directory_readonly_snapshot_required' USING ERRCODE='55000'; END IF;
END $$;

CREATE FUNCTION package_historical_research.directory_page(
 target_kind text,filters jsonb,page_limit integer,after_id uuid,expected_observation design.sha256
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,design,pg_temp SET timezone='UTC' AS $$
DECLARE rows jsonb; page jsonb; fingerprint text; after_ordinal bigint:=0; next_id uuid;
 bid uuid; scope uuid; protocol uuid; cohort uuid; total integer;
BEGIN
 PERFORM package_historical_research.assert_directory_reader();
 IF target_kind IS NULL OR target_kind NOT IN('admissions','protocols','cohorts','jobs') OR page_limit IS NULL OR page_limit NOT BETWEEN 1 AND 50
 OR NOT design.package_json_keys(filters,ARRAY['bid_id','scope_id','protocol_id','cohort_id'])
 OR (after_id IS NULL)<>(expected_observation IS NULL)
 THEN RAISE EXCEPTION 'package_history_directory_request_invalid' USING ERRCODE='23514'; END IF;
 bid:=(filters->>'bid_id')::uuid; scope:=(filters->>'scope_id')::uuid;
 protocol:=(filters->>'protocol_id')::uuid; cohort:=(filters->>'cohort_id')::uuid;
 IF target_kind='admissions' THEN
  IF protocol IS NOT NULL OR cohort IS NOT NULL OR scope IS NOT NULL AND bid IS NULL
  THEN RAISE EXCEPTION 'package_history_directory_filters_invalid' USING ERRCODE='23514'; END IF;
  IF bid IS NOT NULL AND NOT EXISTS(SELECT FROM design.bids WHERE id=bid)
  OR scope IS NOT NULL AND NOT EXISTS(SELECT FROM design.bid_package_technical_scopes s WHERE s.id=scope AND s.bid_id=bid)
  THEN RAISE EXCEPTION 'package_history_directory_scope_missing' USING ERRCODE='P0002'; END IF;
  SELECT coalesce(jsonb_agg(x.item ORDER BY x.created_at DESC,x.id DESC),'[]') INTO rows FROM (
   SELECT a.id,a.created_at,jsonb_build_object('kind','admission','id',a.id,'created_at',a.created_at,
    'bid_id',a.bid_id,'scope_id',a.scope_id,'submission_id',a.submission_id,'outcome_id',a.outcome_id,
    'digest',a.digest,'origin',a.origin,'state',a.document->'state',
    'historical_as_of',a.document->'historical_as_of','label_known_at',a.document->'label_known_at',
    'current_status','not_rechecked') AS item
   FROM package_historical_research.admissions a WHERE (bid IS NULL OR a.bid_id=bid) AND (scope IS NULL OR a.scope_id=scope)
   ORDER BY a.created_at DESC,a.id DESC LIMIT 2001
  )x;
 ELSIF target_kind='protocols' THEN
  IF bid IS NOT NULL OR scope IS NOT NULL OR protocol IS NOT NULL OR cohort IS NOT NULL
  THEN RAISE EXCEPTION 'package_history_directory_filters_invalid' USING ERRCODE='23514'; END IF;
  SELECT coalesce(jsonb_agg(x.item ORDER BY x.created_at DESC,x.id DESC),'[]') INTO rows FROM (
   SELECT p.id,p.created_at,jsonb_build_object('kind','protocol','id',p.id,'created_at',p.created_at,
    'digest',p.digest,'document',p.document,'current_status','not_rechecked') AS item
   FROM package_historical_research.protocols p ORDER BY p.created_at DESC,p.id DESC LIMIT 2001
  )x;
 ELSIF target_kind='cohorts' THEN
  IF bid IS NOT NULL OR scope IS NOT NULL OR cohort IS NOT NULL
  THEN RAISE EXCEPTION 'package_history_directory_filters_invalid' USING ERRCODE='23514'; END IF;
  IF protocol IS NOT NULL AND NOT EXISTS(SELECT FROM package_historical_research.protocols p WHERE p.id=protocol)
  THEN RAISE EXCEPTION 'package_history_directory_protocol_missing' USING ERRCODE='P0002'; END IF;
  SELECT coalesce(jsonb_agg(x.item ORDER BY x.created_at DESC,x.id DESC),'[]') INTO rows FROM (
   SELECT c.id,c.training_frozen_at AS created_at,jsonb_build_object('kind','cohort','id',c.id,'created_at',c.training_frozen_at,
    'protocol_id',c.protocol_id,'digest',c.digest,'membership_digest',c.membership_digest,'origin',c.origin,
    'submission_split_at',c.submission_split_at,'label_available_as_of',c.label_available_as_of,
    'member_count',(SELECT count(*) FROM package_historical_research.members m WHERE m.cohort_id=c.id),
    'current_status','not_rechecked') AS item
   FROM package_historical_research.cohorts c WHERE protocol IS NULL OR c.protocol_id=protocol
   ORDER BY c.training_frozen_at DESC,c.id DESC LIMIT 2001
  )x;
 ELSE
  IF bid IS NOT NULL OR scope IS NOT NULL OR protocol IS NOT NULL OR cohort IS NULL
  THEN RAISE EXCEPTION 'package_history_directory_filters_invalid' USING ERRCODE='23514'; END IF;
  IF NOT EXISTS(SELECT FROM package_historical_research.cohorts c WHERE c.id=cohort)
  THEN RAISE EXCEPTION 'package_history_directory_cohort_missing' USING ERRCODE='P0002'; END IF;
  SELECT coalesce(jsonb_agg(x.item ORDER BY x.created_at DESC,x.id DESC),'[]') INTO rows FROM (
   SELECT j.id,j.created_at,jsonb_build_object('kind','job','id',j.id,'created_at',j.created_at,'cohort_id',j.cohort_id,
    'job_kind',j.kind,'state',j.state,'generation',j.generation,'result_available',r.job_id IS NOT NULL,
    'result_digest',r.digest,'current_status','not_rechecked') AS item
   FROM package_historical_research.jobs j LEFT JOIN package_historical_research.results r ON r.job_id=j.id
   WHERE j.cohort_id=cohort ORDER BY j.created_at DESC,j.id DESC LIMIT 2001
  )x;
 END IF;
 total:=jsonb_array_length(rows);
 IF total>2000 THEN RAISE EXCEPTION 'package_history_directory_budget_exceeded' USING ERRCODE='54000'; END IF;
 fingerprint:=design.package_technical_digest(jsonb_build_object('version','package-history-directory-observation/1','kind',target_kind,'filters',filters,'items',rows));
 IF expected_observation IS NOT NULL AND expected_observation::text<>fingerprint
 THEN RAISE EXCEPTION 'package_history_directory_observation_changed' USING ERRCODE='55000'; END IF;
 IF after_id IS NOT NULL THEN
  SELECT ordinal INTO after_ordinal FROM jsonb_array_elements(rows) WITH ORDINALITY x(item,ordinal) WHERE item->>'id'=after_id::text;
  IF after_ordinal IS NULL THEN RAISE EXCEPTION 'package_history_directory_cursor_invalid' USING ERRCODE='23514'; END IF;
 END IF;
 SELECT coalesce(jsonb_agg(item ORDER BY ordinal),'[]') INTO page FROM jsonb_array_elements(rows) WITH ORDINALITY x(item,ordinal)
 WHERE ordinal>after_ordinal AND ordinal<=after_ordinal+page_limit;
 IF after_ordinal+jsonb_array_length(page)<total THEN next_id:=(page->(jsonb_array_length(page)-1)->>'id')::uuid; END IF;
 RETURN jsonb_build_object('kind',target_kind,'filters',filters,'items',page,'total',total,
  'observation_digest',fingerprint,'observed_at',transaction_timestamp(),'after_id',next_id,
  'has_more',next_id IS NOT NULL);
END $$;

CREATE FUNCTION package_historical_research.list_admissions(bid uuid,scope uuid,page_limit integer,after_id uuid,expected_observation design.sha256) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
 SELECT package_historical_research.directory_page('admissions',jsonb_build_object('bid_id',bid,'scope_id',scope,'protocol_id',NULL,'cohort_id',NULL),page_limit,after_id,expected_observation)
$$;
CREATE FUNCTION package_historical_research.list_protocols(page_limit integer,after_id uuid,expected_observation design.sha256) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
 SELECT package_historical_research.directory_page('protocols',jsonb_build_object('bid_id',NULL,'scope_id',NULL,'protocol_id',NULL,'cohort_id',NULL),page_limit,after_id,expected_observation)
$$;
CREATE FUNCTION package_historical_research.list_cohorts(protocol uuid,page_limit integer,after_id uuid,expected_observation design.sha256) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
 SELECT package_historical_research.directory_page('cohorts',jsonb_build_object('bid_id',NULL,'scope_id',NULL,'protocol_id',protocol,'cohort_id',NULL),page_limit,after_id,expected_observation)
$$;
CREATE FUNCTION package_historical_research.list_jobs(cohort uuid,page_limit integer,after_id uuid,expected_observation design.sha256) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,package_historical_research,pg_temp AS $$
 SELECT package_historical_research.directory_page('jobs',jsonb_build_object('bid_id',NULL,'scope_id',NULL,'protocol_id',NULL,'cohort_id',cohort),page_limit,after_id,expected_observation)
$$;

REVOKE ALL ON FUNCTION package_historical_research.assert_directory_reader(),package_historical_research.directory_page(text,jsonb,integer,uuid,design.sha256),
 package_historical_research.list_admissions(uuid,uuid,integer,uuid,design.sha256),package_historical_research.list_protocols(integer,uuid,design.sha256),
 package_historical_research.list_cohorts(uuid,integer,uuid,design.sha256),package_historical_research.list_jobs(uuid,integer,uuid,design.sha256)
 FROM PUBLIC,tender_api,tender_worker,tender_research_worker,tender_research_read,tender_score_read,tender_model_train,tender_model_evaluate,tender_model_score,tender_package_history_verify,tender_package_history_train,tender_package_history_evaluate,tender_package_history_test_api;
GRANT EXECUTE ON FUNCTION package_historical_research.list_admissions(uuid,uuid,integer,uuid,design.sha256),package_historical_research.list_protocols(integer,uuid,design.sha256),
 package_historical_research.list_cohorts(uuid,integer,uuid,design.sha256),package_historical_research.list_jobs(uuid,integer,uuid,design.sha256) TO tender_api;
COMMIT;
