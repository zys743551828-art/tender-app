-- Retrospective research WORK IN PROGRESS, NOT SUBMITTED OR EXECUTED. Static review -> NEW fresh DB only.
-- Requires score_basis B plus the exact reviewed 17-SQL baseline.
-- This namespace cannot confer real data, future accuracy or model business qualification.
BEGIN;
CREATE SCHEMA retrospective_research;
REVOKE ALL ON SCHEMA retrospective_research FROM PUBLIC;
GRANT USAGE ON SCHEMA retrospective_research TO tender_api,tender_model_train,tender_model_evaluate;
CREATE TABLE retrospective_research.label_versions(
 id uuid PRIMARY KEY,basis_id uuid NOT NULL REFERENCES score_basis.bindings(id),outcome_id uuid NOT NULL REFERENCES design.outcomes(id),
 scale_description text NOT NULL CHECK(scale_description='未加权原始分'),
 aggregation_description text NOT NULL CHECK(length(btrim(aggregation_description)) BETWEEN 1 AND 4000),
 published_at timestamptz NOT NULL,reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 4000),
 origin text NOT NULL CHECK(origin IN ('synthetic','uncertain')),created_by uuid NOT NULL REFERENCES design.members(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE retrospective_research.label_evidence(
 id uuid PRIMARY KEY,label_id uuid NOT NULL REFERENCES retrospective_research.label_versions(id),bid_id uuid NOT NULL,
 document_version_id uuid NOT NULL,parse_id uuid NOT NULL,evidence_id uuid NOT NULL,physical_page integer NOT NULL CHECK(physical_page>0),
 blob_digest design.sha256 NOT NULL,evidence_digest design.sha256 NOT NULL,quote text NOT NULL CHECK(length(quote) BETWEEN 1 AND 16000),
 source_id uuid NOT NULL REFERENCES retrieval.source_nodes(id),original_source_id uuid NOT NULL REFERENCES retrieval.source_nodes(id),
 FOREIGN KEY(bid_id,document_version_id) REFERENCES design.document_versions(bid_id,id),
 FOREIGN KEY(bid_id,parse_id,document_version_id) REFERENCES design.parse_runs(bid_id,id,document_version_id),
 FOREIGN KEY(bid_id,evidence_id) REFERENCES design.evidence_blocks(bid_id,id),UNIQUE(label_id,evidence_id)
);
CREATE TABLE retrospective_research.label_sources(
 evidence_id uuid NOT NULL REFERENCES retrospective_research.label_evidence(id),ancestor_id uuid NOT NULL REFERENCES retrieval.source_nodes(id),
 revision bigint NOT NULL,digest design.sha256 NOT NULL,known_at timestamptz NOT NULL,valid_from timestamptz NOT NULL,valid_until timestamptz,
 PRIMARY KEY(evidence_id,ancestor_id)
);
CREATE TABLE retrospective_research.label_decisions(
 id uuid PRIMARY KEY,label_id uuid NOT NULL REFERENCES retrospective_research.label_versions(id),
 state text NOT NULL CHECK(state IN ('pending','confirmed','rejected','withdrawn')),actor_id uuid NOT NULL REFERENCES design.members(id),
 command_id uuid NOT NULL UNIQUE REFERENCES design.commands(id),reason text NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE retrospective_research.label_heads(
 outcome_id uuid PRIMARY KEY REFERENCES design.outcomes(id),label_id uuid NOT NULL REFERENCES retrospective_research.label_versions(id),
 decision_id uuid NOT NULL REFERENCES retrospective_research.label_decisions(id),revision bigint NOT NULL CHECK(revision>0)
);
-- Optional, explicit evidence-backed template/near-duplicate links. Project and
-- body identity links are always computed from HistoricalSubject / exact originals.
CREATE TABLE retrospective_research.group_links(
 id uuid PRIMARY KEY,left_input_id uuid NOT NULL REFERENCES historical_backtest.inputs(id),right_input_id uuid NOT NULL REFERENCES historical_backtest.inputs(id),
 kind text NOT NULL CHECK(kind IN ('template','near_duplicate')),evidence_ids uuid[] NOT NULL CHECK(cardinality(evidence_ids)>0),
 reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 4000),created_by uuid NOT NULL REFERENCES design.members(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(left_input_id<right_input_id),UNIQUE(left_input_id,right_input_id,kind)
);
CREATE TABLE retrospective_research.group_decisions(
 id uuid PRIMARY KEY,link_id uuid NOT NULL REFERENCES retrospective_research.group_links(id),active boolean NOT NULL,
 actor_id uuid NOT NULL REFERENCES design.members(id),reason text NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE retrospective_research.group_heads(
 link_id uuid PRIMARY KEY REFERENCES retrospective_research.group_links(id),decision_id uuid NOT NULL REFERENCES retrospective_research.group_decisions(id),revision bigint NOT NULL CHECK(revision>0)
);
CREATE TABLE retrospective_research.cohorts(
 id uuid PRIMARY KEY,protocol_id uuid NOT NULL REFERENCES model_governance.protocols(id),
 mode text NOT NULL DEFAULT 'retrospective_submission_time_holdout' CHECK(mode='retrospective_submission_time_holdout'),
 submission_split_at timestamptz NOT NULL,label_available_as_of timestamptz NOT NULL,training_frozen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 timing_digest design.sha256 NOT NULL,request_digest design.sha256 NOT NULL,origin text NOT NULL CHECK(origin IN ('synthetic','uncertain')),
 created_by uuid NOT NULL REFERENCES design.members(id),CHECK(label_available_as_of<=training_frozen_at AND submission_split_at<=training_frozen_at)
);
CREATE TABLE retrospective_research.members(
 cohort_id uuid NOT NULL REFERENCES retrospective_research.cohorts(id),label_id uuid NOT NULL REFERENCES retrospective_research.label_versions(id),
 label_decision_id uuid NOT NULL REFERENCES retrospective_research.label_decisions(id),basis_id uuid NOT NULL REFERENCES score_basis.bindings(id),
 coverage_id uuid NOT NULL REFERENCES score_basis.results(id),historical_input_id uuid NOT NULL REFERENCES historical_backtest.inputs(id),
 subject_id uuid NOT NULL REFERENCES historical_backtest.subjects(id),group_id uuid NOT NULL,closure_ids uuid[] NOT NULL,
 purpose text NOT NULL CHECK(purpose IN ('fit','development','calibration','final','excluded')),exclusion_reason text,
 submitted_at timestamptz NOT NULL,label_known_at timestamptz NOT NULL,
 PRIMARY KEY(cohort_id,historical_input_id),UNIQUE(cohort_id,label_id),CHECK((purpose='excluded')=(exclusion_reason IS NOT NULL))
);
CREATE TABLE retrospective_research.cohort_seals(
 cohort_id uuid PRIMARY KEY REFERENCES retrospective_research.cohorts(id),split_digest design.sha256 NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE retrospective_research.exports(
 cohort_id uuid NOT NULL REFERENCES retrospective_research.cohorts(id),purpose text NOT NULL CHECK(purpose IN ('training','final_features','final_labels')),
 document jsonb NOT NULL,digest design.sha256 NOT NULL,PRIMARY KEY(cohort_id,purpose),
 CHECK(jsonb_typeof(document)='object' AND octet_length(document::text)<=8388608)
);
CREATE TABLE retrospective_research.jobs(
 id uuid PRIMARY KEY,cohort_id uuid NOT NULL REFERENCES retrospective_research.cohorts(id),kind text NOT NULL CHECK(kind IN ('train','evaluate')),
 state text NOT NULL CHECK(state IN ('queued','running','succeeded','failed','cancelled')),generation bigint NOT NULL DEFAULT 1 CHECK(generation>0),
 fence bigint NOT NULL DEFAULT 0,owner_token uuid,lease_until timestamptz,created_by uuid NOT NULL REFERENCES design.members(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK((owner_token IS NULL)=(lease_until IS NULL)),UNIQUE(cohort_id,kind)
);
CREATE TABLE retrospective_research.results(
 job_id uuid PRIMARY KEY REFERENCES retrospective_research.jobs(id),document jsonb NOT NULL,digest design.sha256 NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(jsonb_typeof(document)='object' AND octet_length(document::text)<=8388608)
);
CREATE TABLE retrospective_research.evaluations(
 job_id uuid PRIMARY KEY REFERENCES retrospective_research.jobs(id),training_job_id uuid NOT NULL REFERENCES retrospective_research.results(job_id),
 model_digest design.sha256 NOT NULL,predictions jsonb NOT NULL,predictions_digest design.sha256 NOT NULL,
 CHECK(jsonb_typeof(predictions)='object' AND octet_length(predictions::text)<=8388608)
);
CREATE TABLE retrospective_research.exposures(
 id uuid PRIMARY KEY,job_id uuid NOT NULL UNIQUE REFERENCES retrospective_research.jobs(id),created_xact xid8 NOT NULL DEFAULT pg_current_xact_id(),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE retrospective_research.exposure_members(
 exposure_id uuid NOT NULL REFERENCES retrospective_research.exposures(id),kind text NOT NULL CHECK(kind IN ('input','project','body','group')),
 identity text NOT NULL,PRIMARY KEY(exposure_id,kind,identity)
);
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['label_versions','label_evidence','label_sources','label_decisions','group_links','group_decisions','cohorts','members','cohort_seals','exports','results','evaluations','exposures','exposure_members'] LOOP
 EXECUTE format('CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON retrospective_research.%I FOR EACH ROW EXECUTE FUNCTION design.append_only()',tab);
 END LOOP;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA retrospective_research FROM PUBLIC,tender_api,tender_worker,tender_research_worker,tender_research_read,tender_score_read,tender_model_train,tender_model_evaluate,tender_model_score;
GRANT SELECT ON ALL TABLES IN SCHEMA retrospective_research TO tender_api;
-- API populates typed capsules, never worker-supplied allowlists. Authority functions
-- derive raw score/identity/time from immutable rows and current controlled heads.
GRANT INSERT ON retrospective_research.label_evidence,retrospective_research.label_sources TO tender_api;

CREATE FUNCTION retrospective_research.related_inputs(target uuid) RETURNS uuid[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,historical_backtest,pg_temp AS $$
 WITH RECURSIVE edges(a,b) AS (
  SELECT l.id,r.id FROM historical_backtest.inputs l JOIN historical_backtest.subjects ls ON ls.id=l.subject_id
   JOIN historical_backtest.inputs r ON l.id<>r.id JOIN historical_backtest.subjects rs ON rs.id=r.subject_id
   WHERE ls.engineering_project_id=rs.engineering_project_id OR l.body_digest=r.body_digest
  UNION SELECT l.left_input_id,l.right_input_id FROM retrospective_research.group_links l JOIN retrospective_research.group_heads h ON h.link_id=l.id JOIN retrospective_research.group_decisions d ON d.id=h.decision_id WHERE d.active
  UNION SELECT l.right_input_id,l.left_input_id FROM retrospective_research.group_links l JOIN retrospective_research.group_heads h ON h.link_id=l.id JOIN retrospective_research.group_decisions d ON d.id=h.decision_id WHERE d.active
 ), connected(id) AS (SELECT target UNION SELECT e.b FROM connected c JOIN edges e ON e.a=c.id)
 SELECT array_agg(id ORDER BY id) FROM connected;
$$;

CREATE FUNCTION retrospective_research.lock_label(target uuid) RETURNS retrospective_research.label_versions
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,score_basis,design,pg_temp AS $$
DECLARE v retrospective_research.label_versions; bid uuid;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'retrospective_read_committed_required' USING ERRCODE='55000'; END IF;
 SELECT * INTO v FROM retrospective_research.label_versions WHERE id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'retrospective_label_missing' USING ERRCODE='P0002'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 SELECT (scope->>'bid_id')::uuid INTO bid FROM score_basis.bindings WHERE id=v.basis_id;
 -- Strict StageA basis may span other bids: acquire its complete scope first.
 IF NOT score_basis.current_binding(v.basis_id) THEN RAISE EXCEPTION 'retrospective_basis_stale' USING ERRCODE='55000'; END IF;
 PERFORM design.lock_worker_bid(bid); PERFORM pg_advisory_xact_lock(90127,1);
 RETURN v;
END $$;

CREATE FUNCTION retrospective_research.qualify_label(target uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,score_basis,historical_backtest,design,retrieval,pg_temp AS $$
DECLARE v retrospective_research.label_versions; basis score_basis.bindings; actual design.outcomes; ref retrospective_research.label_evidence; block record; source record; root record; expected uuid[]; frozen uuid[]; count_refs integer:=0;
BEGIN
 v:=retrospective_research.lock_label(target); SELECT * INTO basis FROM score_basis.bindings WHERE id=v.basis_id;
 SELECT * INTO actual FROM design.outcomes WHERE id=v.outcome_id;
 IF actual.id IS NULL OR actual.maximum<=0 OR actual.maximum IN ('NaN','Infinity','-Infinity') OR actual.value<0 OR actual.value IN ('NaN','Infinity','-Infinity') OR actual.value>actual.maximum OR actual.bid_id IS DISTINCT FROM (basis.scope->>'bid_id')::uuid OR actual.submission_id IS DISTINCT FROM (basis.scope->>'submission_id')::uuid
  OR actual.score_kind<>'technical_total' OR actual.value IS NULL OR actual.maximum IS DISTINCT FROM basis.recorded_maximum OR v.scale_description IS DISTINCT FROM basis.scale_description
  OR NOT EXISTS(SELECT FROM design.outcome_heads h WHERE h.submission_id=actual.submission_id AND h.outcome_id=actual.id)
  OR actual.known_at>clock_timestamp() OR v.published_at>actual.known_at
  OR NOT EXISTS(SELECT FROM design.submission_records s WHERE s.id=actual.submission_id AND s.submitted_at<=v.published_at AND s.submitted_at<=actual.known_at) THEN RETURN false; END IF;
 FOR ref IN SELECT * FROM retrospective_research.label_evidence WHERE label_id=target LOOP
  count_refs:=count_refs+1;
  SELECT e.*,p.document_version_id,p.coverage,p.gaps,p.page_count,b.digest AS blob_digest INTO block FROM design.evidence_blocks e JOIN design.parse_runs p ON p.id=e.parse_id AND p.bid_id=e.bid_id
   JOIN design.document_versions d ON d.id=p.document_version_id AND d.bid_id=e.bid_id JOIN design.blobs b ON b.id=d.blob_id
   WHERE e.id=ref.evidence_id AND e.bid_id=actual.bid_id;
  IF NOT FOUND OR ref.bid_id IS DISTINCT FROM actual.bid_id OR ref.document_version_id IS DISTINCT FROM actual.source_version_id OR block.document_version_id IS DISTINCT FROM actual.source_version_id
   OR ref.parse_id IS DISTINCT FROM block.parse_id OR ref.physical_page IS DISTINCT FROM block.physical_page OR ref.evidence_digest IS DISTINCT FROM block.digest OR ref.blob_digest IS DISTINCT FROM block.blob_digest
   OR ref.quote IS DISTINCT FROM block.text_content OR encode(sha256(convert_to(block.text_content,'UTF8')),'hex')<>block.digest::text
   OR block.coverage<>'complete' OR block.gaps<>'[]'::jsonb OR block.page_count<=0
   OR ref.parse_id IS DISTINCT FROM (SELECT p.id FROM design.parse_runs p WHERE p.document_version_id=actual.source_version_id ORDER BY p.created_at DESC,p.id DESC LIMIT 1)
   OR (SELECT count(*) FROM design.pages p WHERE p.parse_id=ref.parse_id)<>block.page_count
   OR EXISTS(SELECT FROM design.pages p WHERE p.parse_id=ref.parse_id AND (p.physical_page NOT BETWEEN 1 AND block.page_count OR p.quality<>'usable' OR p.gaps<>'[]'::jsonb)) THEN RETURN false; END IF;
  SELECT * INTO source FROM retrieval.source_nodes WHERE id=ref.source_id;
  SELECT * INTO root FROM retrieval.source_nodes WHERE id=ref.original_source_id;
  IF source.document_version_id IS DISTINCT FROM actual.source_version_id OR root.document_version_id IS DISTINCT FROM actual.source_version_id
   OR source.digest IS DISTINCT FROM block.blob_digest OR root.digest IS DISTINCT FROM block.blob_digest
   OR source.policy_class IS DISTINCT FROM 'official_label' OR root.policy_class IS DISTINCT FROM 'official_label'
   OR NOT EXISTS(SELECT FROM retrieval.lineage_edges e WHERE e.child_id=source.id AND e.parent_id=root.id) THEN RETURN false; END IF;
  SELECT array_agg(ancestor_id ORDER BY ancestor_id) INTO expected FROM retrieval.source_ancestors WHERE source_id=ref.source_id;
  SELECT array_agg(ancestor_id ORDER BY ancestor_id) INTO frozen FROM retrospective_research.label_sources WHERE evidence_id=ref.id;
  IF expected IS NULL OR expected IS DISTINCT FROM frozen THEN RETURN false; END IF;
  IF EXISTS(SELECT FROM retrospective_research.label_sources f JOIN retrieval.source_nodes n ON n.id=f.ancestor_id LEFT JOIN retrieval.source_heads h ON h.source_id=n.id
   WHERE f.evidence_id=ref.id AND (n.kind<>'document' OR n.policy_class<>'official_label' OR n.known_at>clock_timestamp() OR n.known_at IS DISTINCT FROM f.known_at OR n.digest IS DISTINCT FROM f.digest
    OR h.status IS DISTINCT FROM 'published' OR h.revision IS DISTINCT FROM f.revision OR h.valid_from IS DISTINCT FROM f.valid_from OR h.valid_until IS DISTINCT FROM f.valid_until
    OR h.valid_from>clock_timestamp() OR h.valid_until<=clock_timestamp()
    OR NOT EXISTS(SELECT FROM design.document_versions d JOIN design.blobs b ON b.id=d.blob_id WHERE d.id=n.document_version_id AND d.bid_id=actual.bid_id AND b.digest=n.digest))) THEN RETURN false; END IF;
 END LOOP;
 RETURN count_refs BETWEEN 1 AND 50;
END $$;

CREATE FUNCTION retrospective_research.current_label(target uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,pg_temp AS $$
BEGIN
 RETURN retrospective_research.qualify_label(target) AND EXISTS(SELECT FROM retrospective_research.label_heads h JOIN retrospective_research.label_decisions d ON d.id=h.decision_id WHERE h.label_id=target AND d.label_id=target AND d.state='confirmed');
END $$;

CREATE FUNCTION retrospective_research.create_label(basis uuid,outcome uuid,published timestamptz,aggregation text,explanation text,actor uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,score_basis,historical_backtest,design,pg_temp AS $$
DECLARE b score_basis.bindings; o design.outcomes; identity uuid:=gen_random_uuid(); origin text:='uncertain';
BEGIN
 IF actor IS NULL OR published IS NULL OR explanation IS NULL OR length(btrim(explanation)) NOT BETWEEN 1 AND 4000 OR aggregation IS NULL OR length(btrim(aggregation)) NOT BETWEEN 1 AND 4000 THEN RAISE EXCEPTION 'label_context_required' USING ERRCODE='22023'; END IF;
 IF NOT score_basis.current_binding(basis) THEN RAISE EXCEPTION 'label_basis_stale' USING ERRCODE='55000'; END IF;
 SELECT * INTO b FROM score_basis.bindings WHERE id=basis; SELECT * INTO o FROM design.outcomes WHERE id=outcome;
 IF o.id IS NULL OR o.bid_id IS DISTINCT FROM (b.scope->>'bid_id')::uuid OR o.submission_id IS DISTINCT FROM (b.scope->>'submission_id')::uuid OR o.score_kind<>'technical_total'
  OR o.value IS NULL OR o.maximum IS DISTINCT FROM b.recorded_maximum OR o.known_at>clock_timestamp() OR published>o.known_at
  OR NOT EXISTS(SELECT FROM design.submission_records s WHERE s.id=o.submission_id AND s.submitted_at<=published) THEN RAISE EXCEPTION 'label_observation_mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT FROM historical_backtest.inputs h WHERE h.id=b.historical_input_id AND h.origin='synthetic')
  OR EXISTS(SELECT FROM model_governance.cohorts c WHERE c.id=b.cohort_id AND c.origin='synthetic') THEN origin:='synthetic'; END IF;
 INSERT INTO retrospective_research.label_versions VALUES(identity,basis,outcome,b.scale_description,aggregation,published,explanation,origin,actor,clock_timestamp());
 RETURN identity;
END $$;

CREATE FUNCTION retrospective_research.decide_label(target uuid,state text,expected_revision bigint,actor uuid,command uuid,explanation text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,pg_temp AS $$
DECLARE v retrospective_research.label_versions; old retrospective_research.label_heads; identity uuid:=gen_random_uuid();
BEGIN
 IF state IS NULL OR state NOT IN ('pending','confirmed','rejected','withdrawn') OR expected_revision IS NULL OR actor IS NULL OR command IS NULL OR explanation IS NULL OR length(btrim(explanation)) NOT BETWEEN 1 AND 4000 THEN RAISE EXCEPTION 'label_decision_required' USING ERRCODE='22023'; END IF;
 v:=retrospective_research.lock_label(target);
 SELECT * INTO old FROM retrospective_research.label_heads WHERE outcome_id=v.outcome_id FOR UPDATE;
 IF coalesce(old.revision,0)<>expected_revision THEN RAISE EXCEPTION 'label_head_changed' USING ERRCODE='40001'; END IF;
 IF state='confirmed' AND NOT retrospective_research.qualify_label(target) THEN RAISE EXCEPTION 'label_source_unavailable' USING ERRCODE='55000'; END IF;
 INSERT INTO retrospective_research.label_decisions VALUES(identity,target,state,actor,command,explanation,clock_timestamp());
 INSERT INTO retrospective_research.label_heads VALUES(v.outcome_id,target,identity,expected_revision+1)
  ON CONFLICT(outcome_id) DO UPDATE SET label_id=excluded.label_id,decision_id=excluded.decision_id,revision=excluded.revision;
 RETURN identity;
END $$;

CREATE FUNCTION retrospective_research.prevent_decided_label_append() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,pg_temp AS $$
DECLARE target uuid;
BEGIN
 IF TG_TABLE_NAME='label_evidence' THEN target:=NEW.label_id; ELSE SELECT label_id INTO target FROM retrospective_research.label_evidence WHERE id=NEW.evidence_id; END IF;
 PERFORM retrospective_research.lock_label(target);
 IF EXISTS(SELECT FROM retrospective_research.label_decisions WHERE label_id=target) THEN RAISE EXCEPTION 'label_already_decided' USING ERRCODE='55000'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER decided_guard BEFORE INSERT ON retrospective_research.label_evidence FOR EACH ROW EXECUTE FUNCTION retrospective_research.prevent_decided_label_append();
CREATE TRIGGER decided_guard BEFORE INSERT ON retrospective_research.label_sources FOR EACH ROW EXECUTE FUNCTION retrospective_research.prevent_decided_label_append();

CREATE FUNCTION retrospective_research.lock_cohort(target uuid) RETURNS retrospective_research.cohorts
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,historical_backtest,design,pg_temp AS $$
DECLARE c retrospective_research.cohorts; member record;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'retrospective_read_committed_required' USING ERRCODE='55000'; END IF;
 SELECT * INTO c FROM retrospective_research.cohorts WHERE id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'retrospective_cohort_missing' USING ERRCODE='P0002'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 FOR member IN SELECT DISTINCT h.bid_id FROM retrospective_research.members m CROSS JOIN LATERAL unnest(retrospective_research.related_inputs(m.historical_input_id)) related(id)
  JOIN historical_backtest.inputs h ON h.id=related.id WHERE m.cohort_id=target ORDER BY h.bid_id LOOP
  PERFORM design.lock_worker_bid(member.bid_id);
 END LOOP;
 PERFORM pg_advisory_xact_lock(90127,1);
 RETURN c;
END $$;

CREATE FUNCTION retrospective_research.current_cohort(target uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,score_basis,historical_backtest,historical_input,score_execution,design,pg_temp AS $$
DECLARE c retrospective_research.cohorts; m retrospective_research.members; h historical_backtest.inputs; l retrospective_research.label_versions; o design.outcomes; b score_basis.bindings; coverage score_basis.results; closure uuid[]; span boolean;
BEGIN
 c:=retrospective_research.lock_cohort(target);
 IF NOT EXISTS(SELECT FROM retrospective_research.members WHERE cohort_id=target) OR NOT EXISTS(SELECT FROM retrospective_research.cohort_seals seal WHERE seal.cohort_id=target AND seal.split_digest=(SELECT encode(sha256(convert_to(jsonb_agg(to_jsonb(m) ORDER BY m.historical_input_id)::text,'UTF8')),'hex') FROM retrospective_research.members m WHERE m.cohort_id=target)) THEN RETURN false; END IF;
 IF c.label_available_as_of>c.training_frozen_at OR c.submission_split_at>c.training_frozen_at THEN RETURN false; END IF;
 FOR m IN SELECT * FROM retrospective_research.members WHERE cohort_id=target ORDER BY historical_input_id LOOP
  SELECT * INTO h FROM historical_backtest.inputs WHERE id=m.historical_input_id;
  SELECT * INTO l FROM retrospective_research.label_versions WHERE id=m.label_id;
  SELECT * INTO o FROM design.outcomes WHERE id=l.outcome_id;
  SELECT * INTO b FROM score_basis.bindings WHERE id=m.basis_id;
  SELECT * INTO coverage FROM score_basis.results WHERE id=m.coverage_id;
  closure:=retrospective_research.related_inputs(m.historical_input_id);
  IF m.closure_ids IS DISTINCT FROM closure OR m.group_id IS DISTINCT FROM closure[1]
   OR m.subject_id IS DISTINCT FROM h.subject_id OR m.submitted_at IS DISTINCT FROM h.historical_as_of OR m.label_known_at IS DISTINCT FROM o.known_at
   OR m.basis_id IS DISTINCT FROM l.basis_id OR coverage.binding_id IS DISTINCT FROM m.basis_id
   OR b.historical_input_id IS DISTINCT FROM h.id OR NOT historical_input.current_input(h.id) OR NOT score_basis.current_binding(b.id)
   OR NOT retrospective_research.current_label(l.id)
   OR NOT EXISTS(SELECT FROM retrospective_research.label_heads head WHERE head.label_id=l.id AND head.decision_id=m.label_decision_id)
   OR coverage.document->'features'->>'status' IS DISTINCT FROM 'complete'
   OR coverage.document->>'technical_maximum' IS DISTINCT FROM b.recorded_maximum::text
   OR (c.origin='synthetic' AND (h.origin<>'synthetic' OR l.origin<>'synthetic')) THEN RETURN false; END IF;
  -- Group boundaries are computed over the COMPLETE related input closure, including
  -- registered relatives not selected as a dataset member. No caller subset can hide
  -- a project/duplicate that straddles the real submission split.
  SELECT count(DISTINCT (relative.historical_as_of<c.submission_split_at))>1 INTO span FROM historical_backtest.inputs relative WHERE relative.id=ANY(closure);
  IF span THEN
   IF m.purpose<>'excluded' OR m.exclusion_reason IS DISTINCT FROM 'group_spans_submission_split' THEN RETURN false; END IF;
  ELSIF o.known_at>c.label_available_as_of THEN
   IF m.purpose<>'excluded' OR m.exclusion_reason IS DISTINCT FROM 'label_after_available_cutoff' THEN RETURN false; END IF;
  ELSIF m.purpose='excluded' THEN RETURN false;
  ELSIF (m.purpose='final') IS DISTINCT FROM (m.submitted_at>=c.submission_split_at) THEN RETURN false;
  END IF;
 END LOOP;
 IF EXISTS(SELECT group_id FROM retrospective_research.members WHERE cohort_id=target AND purpose<>'excluded' GROUP BY group_id HAVING count(DISTINCT purpose)>1) THEN RETURN false; END IF;
 RETURN (SELECT count(DISTINCT purpose) FROM retrospective_research.members WHERE cohort_id=target AND purpose IN ('fit','development','final'))=3;
END $$;

CREATE FUNCTION retrospective_research.assert_lease(target uuid,generation bigint,fence bigint,owner uuid) RETURNS retrospective_research.jobs
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,pg_temp AS $$
DECLARE job retrospective_research.jobs; intended text;
BEGIN
 SELECT * INTO job FROM retrospective_research.jobs WHERE id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'retrospective_job_missing' USING ERRCODE='P0002'; END IF;
 intended:=CASE job.kind WHEN 'train' THEN 'tender_model_train' ELSE 'tender_model_evaluate' END;
 IF NOT pg_has_role(session_user,intended,'member') THEN RAISE EXCEPTION 'retrospective_purpose_denied' USING ERRCODE='42501'; END IF;
 IF NOT retrospective_research.current_cohort(job.cohort_id) THEN RAISE EXCEPTION 'retrospective_cohort_stale' USING ERRCODE='55000'; END IF;
 SELECT * INTO job FROM retrospective_research.jobs WHERE id=target FOR UPDATE;
 intended:=CASE job.kind WHEN 'train' THEN 'tender_model_train' ELSE 'tender_model_evaluate' END;
 IF job.state<>'running' OR job.generation IS DISTINCT FROM generation OR job.fence IS DISTINCT FROM fence OR job.owner_token IS DISTINCT FROM owner
  OR owner IS NULL OR job.lease_until<=clock_timestamp() OR NOT pg_has_role(session_user,intended,'member') THEN RAISE EXCEPTION 'retrospective_lease_invalid' USING ERRCODE='55000'; END IF;
 RETURN job;
END $$;

CREATE FUNCTION retrospective_research.claim_job(target uuid,expected_generation bigint,owner uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,pg_temp AS $$
DECLARE job retrospective_research.jobs; intended text;
BEGIN
 IF owner IS NULL OR expected_generation IS NULL THEN RAISE EXCEPTION 'retrospective_lease_invalid' USING ERRCODE='55000'; END IF;
 SELECT * INTO job FROM retrospective_research.jobs WHERE id=target;
 IF NOT FOUND THEN RAISE EXCEPTION 'retrospective_job_missing' USING ERRCODE='P0002'; END IF;
 intended:=CASE job.kind WHEN 'train' THEN 'tender_model_train' ELSE 'tender_model_evaluate' END;
 IF NOT pg_has_role(session_user,intended,'member') THEN RAISE EXCEPTION 'retrospective_purpose_denied' USING ERRCODE='42501'; END IF;
 IF NOT retrospective_research.current_cohort(job.cohort_id) OR NOT EXISTS(SELECT FROM retrospective_research.cohorts c WHERE c.id=job.cohort_id AND c.origin='synthetic') THEN RAISE EXCEPTION 'retrospective_real_execution_not_qualified' USING ERRCODE='55000'; END IF;
 SELECT * INTO job FROM retrospective_research.jobs WHERE id=target FOR UPDATE;
 intended:=CASE job.kind WHEN 'train' THEN 'tender_model_train' ELSE 'tender_model_evaluate' END;
 IF job.generation IS DISTINCT FROM expected_generation OR job.state NOT IN ('queued','running') OR (job.state='running' AND job.lease_until>clock_timestamp()) OR NOT pg_has_role(session_user,intended,'member') THEN RAISE EXCEPTION 'retrospective_not_claimable' USING ERRCODE='55000'; END IF;
 UPDATE retrospective_research.jobs SET state='running',owner_token=owner,lease_until=clock_timestamp()+interval '120 seconds',fence=jobs.fence+1 WHERE id=target RETURNING * INTO job;
 RETURN jsonb_build_object('job_id',job.id,'generation',job.generation,'fence',job.fence,'owner',owner);
END $$;

CREATE FUNCTION retrospective_research.read_training(target uuid,generation bigint,fence bigint,owner uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,model_governance,pg_temp AS $$
DECLARE job retrospective_research.jobs;
BEGIN
 job:=retrospective_research.assert_lease(target,generation,fence,owner);
 IF job.kind<>'train' THEN RAISE EXCEPTION 'retrospective_purpose_denied' USING ERRCODE='42501'; END IF;
 RETURN (SELECT jsonb_build_object('mode',c.mode,'timing_digest',c.timing_digest,'protocol',p.document,'training',e.document,'training_digest',e.digest)
  FROM retrospective_research.cohorts c JOIN model_governance.protocols p ON p.id=c.protocol_id JOIN retrospective_research.exports e ON e.cohort_id=c.id AND e.purpose='training' WHERE c.id=job.cohort_id);
END $$;

CREATE FUNCTION retrospective_research.open_final(target uuid,generation bigint,fence bigint,owner uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,historical_backtest,model_governance,pg_temp AS $$
DECLARE job retrospective_research.jobs; old uuid; identity uuid:=gen_random_uuid();
BEGIN
 job:=retrospective_research.assert_lease(target,generation,fence,owner);
 IF job.kind<>'evaluate' OR NOT EXISTS(SELECT FROM retrospective_research.evaluations WHERE job_id=target) THEN RAISE EXCEPTION 'retrospective_predictions_not_frozen' USING ERRCODE='55000'; END IF;
 PERFORM pg_advisory_xact_lock(91144,1);
 SELECT id INTO old FROM retrospective_research.exposures WHERE job_id=target;
 IF FOUND THEN RETURN old; END IF;
 -- Real closure identities, not just selected final members. Existing StageA final
 -- exposure participates too; new namespaces cannot wash already-seen projects.
 IF EXISTS(SELECT FROM retrospective_research.members m CROSS JOIN LATERAL unnest(m.closure_ids) related(id)
  JOIN historical_backtest.inputs h ON h.id=related.id JOIN historical_backtest.subjects s ON s.id=h.subject_id
  CROSS JOIN LATERAL (VALUES('input',h.id::text),('project',s.engineering_project_id::text),('body',h.body_digest::text),('group',m.group_id::text)) key(kind,identity)
  WHERE m.cohort_id=job.cohort_id AND m.purpose='final' AND (
   EXISTS(SELECT FROM retrospective_research.exposure_members seen WHERE seen.kind=key.kind AND seen.identity=key.identity)
   OR EXISTS(SELECT FROM model_governance.exposure_members seen WHERE seen.kind=key.kind AND seen.identity=key.identity))) THEN RAISE EXCEPTION 'retrospective_final_already_exposed' USING ERRCODE='55000'; END IF;
 INSERT INTO retrospective_research.exposures(id,job_id) VALUES(identity,target);
 INSERT INTO retrospective_research.exposure_members
 SELECT DISTINCT identity,key.kind,key.value FROM retrospective_research.members m CROSS JOIN LATERAL unnest(m.closure_ids) related(id)
  JOIN historical_backtest.inputs h ON h.id=related.id JOIN historical_backtest.subjects s ON s.id=h.subject_id
  CROSS JOIN LATERAL (VALUES('input',h.id::text),('project',s.engineering_project_id::text),('body',h.body_digest::text),('group',m.group_id::text)) key(kind,value)
  WHERE m.cohort_id=job.cohort_id AND m.purpose='final';
 IF NOT FOUND THEN RAISE EXCEPTION 'retrospective_final_empty' USING ERRCODE='55000'; END IF;
 RETURN identity;
END $$;

CREATE FUNCTION retrospective_research.read_final(target uuid,generation bigint,fence bigint,owner uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,model_governance,pg_temp AS $$
DECLARE job retrospective_research.jobs;
BEGIN
 job:=retrospective_research.assert_lease(target,generation,fence,owner);
 IF job.kind<>'evaluate' OR NOT EXISTS(SELECT FROM retrospective_research.exposures x WHERE x.job_id=target AND x.created_xact<>pg_current_xact_id()) THEN RAISE EXCEPTION 'retrospective_committed_exposure_required' USING ERRCODE='55000'; END IF;
 RETURN (SELECT jsonb_build_object('mode',c.mode,'timing_digest',c.timing_digest,'protocol',p.document,'labels',e.document,'labels_digest',e.digest,'predictions',v.predictions,'predictions_digest',v.predictions_digest,'model_digest',v.model_digest)
  FROM retrospective_research.cohorts c JOIN model_governance.protocols p ON p.id=c.protocol_id JOIN retrospective_research.exports e ON e.cohort_id=c.id AND e.purpose='final_labels' JOIN retrospective_research.evaluations v ON v.job_id=target WHERE c.id=job.cohort_id);
END $$;

CREATE FUNCTION retrospective_research.renew_job(target uuid,generation bigint,fence bigint,owner uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,pg_temp AS $$
BEGIN
 PERFORM retrospective_research.assert_lease(target,generation,fence,owner);
 UPDATE retrospective_research.jobs SET lease_until=clock_timestamp()+interval '120 seconds' WHERE id=target;
END $$;

CREATE FUNCTION retrospective_research.finish_job(target uuid,generation bigint,fence bigint,owner uuid,payload jsonb,payload_digest design.sha256) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,pg_temp AS $$
DECLARE job retrospective_research.jobs;
BEGIN
 job:=retrospective_research.assert_lease(target,generation,fence,owner);
 IF payload IS NULL OR payload_digest IS NULL OR payload->>'mode' IS DISTINCT FROM 'retrospective_submission_time_holdout'
  OR payload->>'formal_eligibility' IS DISTINCT FROM 'unavailable' OR payload->'research_only' IS DISTINCT FROM 'true'::jsonb
  OR payload->>'schema' IS DISTINCT FROM (CASE job.kind WHEN 'train' THEN 'retrospective-training-result/1' ELSE 'retrospective-final-evaluation/1' END)
  OR payload->>'timing_digest' IS DISTINCT FROM (SELECT timing_digest::text FROM retrospective_research.cohorts WHERE id=job.cohort_id)
  OR (job.kind='evaluate' AND NOT EXISTS(SELECT FROM retrospective_research.exposures x WHERE x.job_id=target AND x.created_xact<>pg_current_xact_id()))
 THEN RAISE EXCEPTION 'retrospective_result_purpose_invalid' USING ERRCODE='23514'; END IF;
 INSERT INTO retrospective_research.results VALUES(target,payload,payload_digest,clock_timestamp());
 UPDATE retrospective_research.jobs SET state='succeeded',owner_token=NULL,lease_until=NULL WHERE id=target;
 RETURN true;
END $$;

CREATE FUNCTION retrospective_research.freeze_cohort(protocol uuid,boundary timestamptz,label_cutoff timestamptz,selections jsonb,actor uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,retrospective_research,score_basis,historical_backtest,model_governance,design,pg_temp AS $$
DECLARE identity uuid:=gen_random_uuid(); frozen timestamptz; timing jsonb; selection jsonb; l retrospective_research.label_versions;
 b score_basis.bindings; h historical_backtest.inputs; o design.outcomes; head retrospective_research.label_heads; coverage score_basis.results;
 closure uuid[]; scope record; purpose text; exclusion text; span boolean; origin text:='synthetic'; members jsonb; rows jsonb; payload jsonb; name text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR actor IS NULL OR protocol IS NULL OR boundary IS NULL OR label_cutoff IS NULL
  OR selections IS NULL OR jsonb_typeof(selections)<>'array' OR jsonb_array_length(selections) NOT BETWEEN 3 AND 1000 THEN RAISE EXCEPTION 'retrospective_freeze_invalid' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(91143,1);
 -- Derive the full scope BEFORE any single bid or graph lock. A strict basis is
 -- deliberately not an input adapter for this retrospective-only cohort surface.
 IF EXISTS(SELECT FROM jsonb_array_elements(selections) selected LEFT JOIN retrospective_research.label_versions l ON l.id=(selected->>'label_id')::uuid LEFT JOIN score_basis.bindings b ON b.id=l.basis_id WHERE b.historical_input_id IS NULL) THEN RAISE EXCEPTION 'retrospective_historical_authority_required' USING ERRCODE='55000'; END IF;
 FOR scope IN SELECT DISTINCT h.bid_id FROM jsonb_array_elements(selections) selected JOIN retrospective_research.label_versions l ON l.id=(selected->>'label_id')::uuid JOIN score_basis.bindings b ON b.id=l.basis_id CROSS JOIN LATERAL unnest(retrospective_research.related_inputs(b.historical_input_id)) r(id) JOIN historical_backtest.inputs h ON h.id=r.id ORDER BY h.bid_id LOOP
  PERFORM design.lock_worker_bid(scope.bid_id);
 END LOOP;
 PERFORM pg_advisory_xact_lock(90127,1);
 frozen:=clock_timestamp();
 IF label_cutoff>frozen OR boundary>frozen OR NOT EXISTS(SELECT FROM model_governance.protocols WHERE id=protocol AND origin='synthetic') THEN RAISE EXCEPTION 'retrospective_timing_or_protocol_unavailable' USING ERRCODE='55000'; END IF;
 timing:=jsonb_build_object('mode','retrospective_submission_time_holdout','submission_split_at',boundary,'label_available_as_of',label_cutoff,'training_frozen_at',frozen,'group_spanning_policy','exclude');
 INSERT INTO retrospective_research.cohorts VALUES(identity,protocol,'retrospective_submission_time_holdout',boundary,label_cutoff,frozen,encode(sha256(convert_to(timing::text,'UTF8')),'hex'),encode(sha256(convert_to(selections::text,'UTF8')),'hex'),origin,actor);
 FOR selection IN SELECT value FROM jsonb_array_elements(selections) LOOP
  IF NOT score_execution.exact_keys(selection,ARRAY['label_id','coverage_id','training_purpose']) OR selection->>'training_purpose' NOT IN ('fit','development','calibration') THEN RAISE EXCEPTION 'retrospective_selection_invalid' USING ERRCODE='22023'; END IF;
  SELECT * INTO l FROM retrospective_research.label_versions WHERE id=(selection->>'label_id')::uuid;
  SELECT * INTO b FROM score_basis.bindings WHERE id=l.basis_id;
  SELECT * INTO h FROM historical_backtest.inputs WHERE id=b.historical_input_id;
  SELECT * INTO o FROM design.outcomes WHERE id=l.outcome_id;
  SELECT * INTO head FROM retrospective_research.label_heads WHERE label_id=l.id;
  SELECT * INTO coverage FROM score_basis.results WHERE id=(selection->>'coverage_id')::uuid;
  IF h.id IS NULL OR head.label_id IS NULL OR coverage.binding_id IS DISTINCT FROM b.id OR coverage.document->'features'->>'status' IS DISTINCT FROM 'complete'
   OR NOT retrospective_research.current_label(l.id) THEN RAISE EXCEPTION 'retrospective_sample_incomplete' USING ERRCODE='55000'; END IF;
  IF h.origin<>'synthetic' OR l.origin<>'synthetic' THEN RAISE EXCEPTION 'retrospective_real_execution_not_qualified' USING ERRCODE='55000'; END IF;
  closure:=retrospective_research.related_inputs(h.id);
  SELECT count(DISTINCT (relative.historical_as_of<boundary))>1 INTO span FROM historical_backtest.inputs relative WHERE relative.id=ANY(closure);
  exclusion:=CASE WHEN span THEN 'group_spans_submission_split' WHEN o.known_at>label_cutoff THEN 'label_after_available_cutoff' ELSE NULL END;
  purpose:=CASE WHEN exclusion IS NOT NULL THEN 'excluded' WHEN h.historical_as_of>=boundary THEN 'final' ELSE selection->>'training_purpose' END;
  INSERT INTO retrospective_research.members VALUES(identity,l.id,head.decision_id,b.id,coverage.id,h.id,h.subject_id,closure[1],closure,purpose,exclusion,h.historical_as_of,o.known_at);
 END LOOP;
 INSERT INTO retrospective_research.cohort_seals(cohort_id,split_digest) SELECT identity,encode(sha256(convert_to(jsonb_agg(to_jsonb(m) ORDER BY m.historical_input_id)::text,'UTF8')),'hex') FROM retrospective_research.members m WHERE m.cohort_id=identity;
 IF NOT retrospective_research.current_cohort(identity) THEN RAISE EXCEPTION 'retrospective_split_invalid' USING ERRCODE='55000'; END IF;
 -- Exports are built HERE from authoritative observed values and derived features,
 -- never from client-supplied y/features. The training payload has no final y rows.
 SELECT jsonb_agg(jsonb_build_object('id',m.historical_input_id,'purpose',m.purpose,'project_id',s.engineering_project_id,'group_id',m.group_id,'body_digest',h.body_digest,'historical_subject_id',h.subject_id,'historical_as_of',h.historical_as_of,'submitted_at',m.submitted_at,'label_known_at',m.label_known_at) ORDER BY m.historical_input_id)
 INTO members FROM retrospective_research.members m JOIN historical_backtest.inputs h ON h.id=m.historical_input_id JOIN historical_backtest.subjects s ON s.id=h.subject_id WHERE m.cohort_id=identity;
 SELECT jsonb_agg(jsonb_build_object('id',m.historical_input_id,'purpose',m.purpose,'project_id',s.engineering_project_id,'group_id',m.group_id,'method',h.method_digest,'engineering_type',s.identity_snapshot->'engineering_type','maximum',b.recorded_maximum,'target',o.value*100/b.recorded_maximum,'features',coverage.document->'features'->'values') ORDER BY m.historical_input_id)
 INTO rows FROM retrospective_research.members m JOIN historical_backtest.inputs h ON h.id=m.historical_input_id JOIN historical_backtest.subjects s ON s.id=h.subject_id JOIN retrospective_research.label_versions l ON l.id=m.label_id JOIN design.outcomes o ON o.id=l.outcome_id JOIN score_basis.bindings b ON b.id=m.basis_id JOIN score_basis.results coverage ON coverage.id=m.coverage_id WHERE m.cohort_id=identity AND m.purpose<>'excluded';
 FOREACH name IN ARRAY ARRAY['training','final_features','final_labels'] LOOP
  payload:=jsonb_build_object('schema',CASE name WHEN 'training' THEN 'retrospective-training-export/1' WHEN 'final_features' THEN 'retrospective-final-features/1' ELSE 'retrospective-sealed-final-labels/1' END,'origin',origin,'mode','retrospective_submission_time_holdout','timing',timing,'timing_digest',encode(sha256(convert_to(timing::text,'UTF8')),'hex'),'members',members,'rows',coalesce((SELECT jsonb_agg(CASE name WHEN 'final_features' THEN entry-'target' WHEN 'final_labels' THEN entry-'features' ELSE entry END) FROM jsonb_array_elements(rows) entry WHERE CASE WHEN name='training' THEN entry->>'purpose' IN ('fit','development','calibration') ELSE entry->>'purpose'='final' END),'[]'::jsonb));
  INSERT INTO retrospective_research.exports VALUES(identity,name,payload,encode(sha256(convert_to(payload::text,'UTF8')),'hex'));
 END LOOP;
 RETURN identity;
END $$;

-- Work in progress: no callable ports granted until full protocol/DDL is submitted.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA retrospective_research FROM PUBLIC;
COMMIT;
