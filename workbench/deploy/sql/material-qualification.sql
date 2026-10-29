-- Fresh-install optional review registry; this does NOT enable execution.
-- Apply only through the project's reviewed fresh database bootstrap.
BEGIN;
CREATE SCHEMA material_qualification;
REVOKE ALL ON SCHEMA material_qualification FROM PUBLIC;
CREATE TABLE material_qualification.records(
 id uuid PRIMARY KEY,
 bid_id uuid NOT NULL,
 scope_id uuid NOT NULL,
 document jsonb NOT NULL,
 digest design.sha256 NOT NULL,
 created_by uuid NOT NULL REFERENCES design.members(id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(bid_id,scope_id) REFERENCES design.bid_package_technical_scopes(bid_id,id),
 CHECK(jsonb_typeof(document)='object' AND octet_length(design.package_canonical_json(document))<=262144),
 CHECK(digest::text=encode(sha256(convert_to(design.package_canonical_json(document),'UTF8')),'hex'))
);
CREATE TABLE material_qualification.decisions(
 id uuid PRIMARY KEY,
 record_id uuid NOT NULL REFERENCES material_qualification.records(id),
 revision bigint NOT NULL CHECK(revision>=1),
 decision text NOT NULL CHECK(decision IN('approved','revoked')),
 actor_id uuid NOT NULL REFERENCES design.members(id),
 reason text NOT NULL CHECK(length(reason) BETWEEN 1 AND 4000),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(record_id,revision), UNIQUE(record_id,id,revision)
);
CREATE TABLE material_qualification.heads(
 record_id uuid PRIMARY KEY REFERENCES material_qualification.records(id),
 decision_id uuid,
 revision bigint NOT NULL DEFAULT 0 CHECK(revision>=0),
 CHECK((decision_id IS NULL AND revision=0) OR (decision_id IS NOT NULL AND revision>0)),
 FOREIGN KEY(record_id,decision_id,revision) REFERENCES material_qualification.decisions(record_id,id,revision)
);
CREATE TRIGGER immutable_qualification_record BEFORE UPDATE OR DELETE ON material_qualification.records FOR EACH ROW EXECUTE FUNCTION design.append_only();
CREATE TRIGGER immutable_qualification_decision BEFORE UPDATE OR DELETE ON material_qualification.decisions FOR EACH ROW EXECUTE FUNCTION design.append_only();
GRANT USAGE ON SCHEMA material_qualification TO tender_api;
GRANT SELECT,INSERT ON material_qualification.records,material_qualification.decisions TO tender_api;
GRANT SELECT,INSERT,UPDATE ON material_qualification.heads TO tender_api;
COMMIT;
