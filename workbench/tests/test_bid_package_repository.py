"""Explicit real PG17 storage checks; no API/model/deployment acceptance implied."""

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.domain.bid_package_repository import (
    load_frozen_identity,
    load_revision,
    read_parse_identity,
    save_revision,
)
from packages.domain.bid_packages import (
    BidScope,
    DocumentPart,
    PackageError,
    PackageKind,
    PackageMember,
    PackageRevision,
    ParseIdentity,
)

DSN = os.environ.get("FUSION_PACKAGE_REPO_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="requires explicit isolated fusion_package_repo DB")


def uid():
    return str(uuid4())


def connect():
    c = psycopg.connect(DSN, row_factory=dict_row)
    c.execute("SET search_path TO design,public")
    assert (
        c.execute("SELECT current_database() AS name").fetchone()["name"] == "fusion_package_repo"
    )
    assert (
        c.execute("SELECT current_setting('server_version_num')::int AS v").fetchone()["v"]
        >= 170000
    )
    return c


def seed(c):
    # Existing identity module is the authority; do not synthesize a competing status column.
    from packages.identity.repository import record_binding, register_bidder

    actor, bid, engineering, lot, round_id = [uid() for _ in range(5)]
    c.execute("INSERT INTO design.members(id,display_name) VALUES(%s,'synthetic actor')", (actor,))
    bidder = register_bidder(c, actor, "synthetic bidder", "explicit test registration", None)["id"]
    c.execute(
        "INSERT INTO design.bids(id,title,settings,created_by) VALUES(%s,'synthetic bid','{}',%s)",
        (bid, actor),
    )
    c.execute(
        "INSERT INTO design.engineering_projects(id,title) VALUES(%s,'synthetic engineering')",
        (engineering,),
    )
    c.execute("INSERT INTO design.engineering_lots VALUES(%s,%s,'lot A')", (lot, engineering))
    c.execute(
        "INSERT INTO design.bid_rounds(id,engineering_project_id,lot,lot_id,round_no) VALUES(%s,%s,'lot A',%s,1)",
        (round_id, engineering, lot),
    )
    c.execute(
        "INSERT INTO design.bid_profiles(bid_id,round_id,bidder_id,phase) VALUES(%s,%s,%s,'preparation')",
        (bid, round_id, bidder),
    )
    record_binding(c, bid, actor, None, reason="explicit synthetic confirmation", confirmed=True)
    scope = BidScope(engineering, lot, round_id, bid, bidder)
    member = add_document(c, scope, actor)
    p = PackageRevision(uid(), uid(), 1, PackageKind.BID, scope, (member,))
    return {"c": c, "actor": actor, "scope": scope, "member": member, "package": p}


def add_document(c, scope, actor, *, source_kind="own", category="technical", raw=None):
    blob, version, parse_id = uid(), uid(), uid()
    file_digest = hashlib.sha256(raw if raw is not None else version.encode()).hexdigest()
    c.execute(
        "INSERT INTO design.blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,%s,'application/pdf') ON CONFLICT(digest) DO NOTHING",
        (blob, file_digest, "synthetic/" + version, len(raw) if raw is not None else 10),
    )
    blob = c.execute("SELECT id FROM design.blobs WHERE digest=%s", (file_digest,)).fetchone()["id"]
    c.execute(
        """INSERT INTO design.document_versions
        (id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by)
        VALUES(%s,%s,%s,'synthetic.pdf',now(),'bid_body',%s)""",
        (version, scope.bid_id, blob, actor),
    )
    c.execute(
        """INSERT INTO design.parse_runs
        (id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps)
        VALUES(%s,%s,%s,%s,%s,2,'complete','[]')""",
        (parse_id, scope.bid_id, version, "b" * 64, "c" * 64),
    )
    for page in (1, 2):
        c.execute(
            """INSERT INTO design.pages
            (bid_id,parse_id,physical_page,width,height,rotation,quality,gaps)
            VALUES(%s,%s,%s,400,500,0,'usable','[]')""",
            (scope.bid_id, parse_id, page),
        )
        text = f"synthetic page {page}"
        c.execute(
            """INSERT INTO design.evidence_blocks
            (id,bid_id,parse_id,physical_page,ordinal,kind,text_content,bbox,structure,digest)
            VALUES(%s,%s,%s,%s,0,'text',%s,%s,%s,%s)""",
            (
                uid(),
                scope.bid_id,
                parse_id,
                page,
                text,
                Jsonb([0.1, 0.2, 0.8, 0.9]),
                Jsonb({"cell_width": 1.25}),
                hashlib.sha256(text.encode()).hexdigest(),
            ),
        )
    identity = read_parse_identity(c, scope.bid_id, version, parse_id)
    return PackageMember(
        "member-" + version,
        version,
        file_digest,
        source_kind,
        "upload-" + version,
        scope,
        (category,),
        2,
        identity,
        (DocumentPart("part-" + version, category, 1, 2),),
    )


@pytest.fixture
def world(monkeypatch):
    # runtime import must not read the local business .env.
    monkeypatch.setenv("WORKBENCH_ENV_FILE", "explicit-test-no-profile-read")
    with connect() as c:
        try:
            yield seed(c)
        finally:
            c.rollback()


def test_real_master_data_roundtrip_manifest_and_independent_authority_package(world):
    c, p = world["c"], world["package"]
    result = save_revision(c, p, expected_digest=None)
    assert not result["replayed"] and result["digest"] == p.manifest_digest
    assert load_revision(c, p.scope.bid_id, p.revision_id) == p
    stored = c.execute(
        """SELECT id::text AS revision_id,package_id::text AS package_id,
        manifest->>'revision_id' AS manifest_revision_id,manifest->>'package_id' AS manifest_package_id
        FROM design.bid_package_revisions WHERE id=%s""",
        (p.revision_id,),
    ).fetchone()
    assert stored["revision_id"] == stored["manifest_revision_id"] == p.revision_id
    assert stored["package_id"] == stored["manifest_package_id"] == p.package_id
    assert (
        c.execute(
            "SELECT count(*) AS n FROM design.bid_package_parts WHERE revision_id=%s",
            (p.revision_id,),
        ).fetchone()["n"]
        == 1
    )
    authority = replace(
        p,
        package_id=uid(),
        revision_id=uid(),
        kind=PackageKind.AUTHORITY,
        members=(replace(p.members[0], source_kind="authority"),),
    )
    save_revision(c, authority, expected_digest=None)
    assert load_revision(c, p.scope.bid_id, authority.revision_id).kind == PackageKind.AUTHORITY


def test_replay_after_later_revision_does_not_rewind_head(world):
    c, p = world["c"], world["package"]
    save_revision(c, p, expected_digest=None)
    newer = p.next_revision(uid(), (replace(p.members[0], purposes=("technical", "annex")),))
    save_revision(c, newer, expected_digest=p.manifest_digest)
    assert save_revision(c, p, expected_digest=None)["replayed"]
    head = c.execute(
        "SELECT revision_id FROM design.bid_package_heads WHERE package_id=%s", (p.package_id,)
    ).fetchone()
    assert str(head["revision_id"]) == newer.revision_id
    with pytest.raises(PackageError, match="REPLAY_CONFLICT"):
        save_revision(
            c,
            replace(p, members=(replace(p.members[0], purposes=("annex",)),)),
            expected_digest=None,
        )


def test_stale_cas_rejects_and_leaves_no_partial_revision(world):
    c, p = world["c"], world["package"]
    save_revision(c, p, expected_digest=None)
    newer = p.next_revision(uid(), p.members)
    with pytest.raises(PackageError, match="CAS_MISMATCH"):
        save_revision(c, newer, expected_digest="f" * 64)
    assert (
        c.execute(
            "SELECT 1 FROM design.bid_package_revisions WHERE id=%s", (newer.revision_id,)
        ).fetchone()
        is None
    )


@pytest.mark.parametrize("field", ["round_id", "lot_id", "engineering_project_id", "bidder_id"])
def test_current_profile_rejects_cross_round_lot_project_and_bidder(world, field):
    c, p = world["c"], world["package"]
    scope = replace(p.scope, **{field: uid()})
    attempted = replace(p, scope=scope, members=(replace(p.members[0], scope=scope),))
    with pytest.raises(PackageError, match="(LOT_BINDING|PROFILE_SCOPE)_MISMATCH"):
        save_revision(c, attempted, expected_digest=None)


def test_no_identity_authority_or_changed_profile_cannot_claim_confirmed(world):
    c, p = world["c"], world["package"]
    c.execute(
        "UPDATE design.bidders SET name='changed bidder name' WHERE id=%s", (p.scope.bidder_id,)
    )
    with pytest.raises(PackageError, match="BINDING_STATUS_MISMATCH"):
        save_revision(c, p, expected_digest=None)
    pending = replace(p.scope, bidder_status="pending")
    candidate = replace(p, scope=pending, members=(replace(p.members[0], scope=pending),))
    save_revision(c, candidate, expected_digest=None)
    assert not load_revision(c, pending.bid_id, candidate.revision_id).formal_eligible


def test_identity_correction_preserves_saved_package_and_replay(world):
    c, p = world["c"], world["package"]
    save_revision(c, p, expected_digest=None)
    original_identity = load_frozen_identity(c, p.scope.bid_id, p.revision_id)
    c.execute(
        "UPDATE design.bidders SET name='changed name after frozen package' WHERE id=%s",
        (p.scope.bidder_id,),
    )
    assert load_revision(c, p.scope.bid_id, p.revision_id) == p
    assert load_frozen_identity(c, p.scope.bid_id, p.revision_id) == original_identity
    assert save_revision(c, p, expected_digest=None)["replayed"]
    with pytest.raises(PackageError, match="BINDING_STATUS_MISMATCH"):
        save_revision(c, p.next_revision(uid(), p.members), expected_digest=p.manifest_digest)


@pytest.mark.parametrize(
    "mutation",
    ["file_digest", "document_version_id", "parser_digest", "evidence_digest", "page_count"],
)
def test_real_parse_and_file_binding_rejects_wrong_supplied_identity(world, mutation):
    c, p = world["c"], world["package"]
    member = p.members[0]
    if mutation in {"parser_digest", "evidence_digest"}:
        altered = replace(member, parse=replace(member.parse, **{mutation: "e" * 64}))
    elif mutation == "document_version_id":
        other = add_document(c, p.scope, world["actor"])
        altered = replace(other, parse=member.parse)
    else:
        altered = replace(member, **{mutation: "e" * 64 if mutation == "file_digest" else 3})
    with pytest.raises(PackageError, match="PACKAGE_(DOCUMENT|PARSE)_"):
        save_revision(c, replace(p, members=(altered,)), expected_digest=None)


def test_unknown_page_member_is_retained_as_unknown_in_real_storage(world):
    c, p = world["c"], world["package"]
    unread = replace(
        p.members[0],
        page_count=None,
        parts=(),
        parse=ParseIdentity("not_frozen", reason="encrypted original"),
    )
    candidate = replace(p, members=(unread,))
    save_revision(c, candidate, expected_digest=None)
    loaded = load_revision(c, p.scope.bid_id, p.revision_id)
    assert loaded.members[0].page_count is None and loaded.members[0].parts == ()
    assert not loaded.formal_eligible


@pytest.mark.parametrize(
    "target",
    ["revision", "member", "part", "binding", "page_insert", "evidence_insert", "head_rewind"],
)
def test_database_guards_reject_mutation_and_late_parse_expansion(world, target):
    c, p = world["c"], world["package"]
    save_revision(c, p, expected_digest=None)
    member = p.members[0]
    statements = {
        "revision": (
            "UPDATE design.bid_package_revisions SET digest=%s WHERE id=%s",
            ("e" * 64, p.revision_id),
        ),
        "member": ("DELETE FROM design.bid_package_members WHERE revision_id=%s", (p.revision_id,)),
        "part": (
            "UPDATE design.bid_package_parts SET last_page=1 WHERE revision_id=%s",
            (p.revision_id,),
        ),
        "binding": (
            "UPDATE design.bid_package_parse_bindings SET evidence_digest=%s WHERE parse_run_id=%s",
            ("e" * 64, member.parse.parse_run_id),
        ),
        "page_insert": (
            "INSERT INTO design.pages SELECT bid_id,parse_id,3,null,width,height,rotation,quality,gaps FROM design.pages WHERE parse_id=%s AND physical_page=1",
            (member.parse.parse_run_id,),
        ),
        "evidence_insert": (
            "INSERT INTO design.evidence_blocks SELECT %s,bid_id,parse_id,physical_page,2,kind,text_content,bbox,structure,digest FROM design.evidence_blocks WHERE parse_id=%s AND physical_page=1",
            (uid(), member.parse.parse_run_id),
        ),
        "head_rewind": (
            "DELETE FROM design.bid_package_heads WHERE package_id=%s",
            (p.package_id,),
        ),
    }
    with pytest.raises(psycopg.Error), c.transaction():
        c.execute(*statements[target])
    assert load_revision(c, p.scope.bid_id, p.revision_id).manifest_digest == p.manifest_digest


def test_actual_concurrent_cas_allows_one_writer(monkeypatch):
    monkeypatch.setenv("WORKBENCH_ENV_FILE", "explicit-test-no-profile-read")
    with connect() as seed_connection:
        w = seed(seed_connection)
        p = w["package"]
        save_revision(seed_connection, p, expected_digest=None)
    # Explicit committed synthetic records live only in the dedicated disposable DB.
    barrier = Barrier(2)
    candidates = [
        p.next_revision(uid(), (replace(p.members[0], purposes=("technical", purpose)),))
        for purpose in ("annex-a", "annex-b")
    ]

    def attempt(candidate):
        with connect() as c:
            barrier.wait(timeout=10)
            try:
                save_revision(c, candidate, expected_digest=p.manifest_digest)
            except PackageError as error:
                return error.code
            return "saved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, candidates))
    assert sorted(results) == ["PACKAGE_CAS_MISMATCH", "saved"]


def test_repeatable_read_writer_is_rejected_before_reading_stale_identity(world):
    p = world["package"]
    # SET LOCAL permitted before the first statement only; use a clean explicit transaction.
    with connect() as other:
        other.rollback()
        other.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with pytest.raises(PackageError, match="ISOLATION_REQUIRES_READ_COMMITTED"):
            save_revision(other, p, expected_digest=None)


def test_pending_identity_snapshot_keeps_actual_then_name_separately_from_old_authority(world):
    c, p = world["c"], world["package"]
    c.execute(
        "UPDATE design.bidders SET name='pending name at freeze' WHERE id=%s", (p.scope.bidder_id,)
    )
    pending = replace(p.scope, bidder_status="pending")
    candidate = replace(p, scope=pending, members=(replace(p.members[0], scope=pending),))
    save_revision(c, candidate, expected_digest=None)
    original = load_frozen_identity(c, p.scope.bid_id, p.revision_id)
    c.execute("UPDATE design.bidders SET name='later name' WHERE id=%s", (p.scope.bidder_id,))
    assert original["bidder_name"] == "pending name at freeze"
    assert original["binding_status"] == "pending"
    assert load_frozen_identity(c, p.scope.bid_id, p.revision_id) == original


@pytest.mark.parametrize("coverage,pages", [("failed", 0), ("partial", 1), ("complete", 1)])
def test_incomplete_or_failed_parser_cannot_be_adopted_as_formal_frozen_input(
    world, coverage, pages
):
    c, p = world["c"], world["package"]
    member = p.members[0]
    new_run = uid()
    c.execute(
        """INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps)
        VALUES(%s,%s,%s,%s,%s,2,%s,'[]')""",
        (new_run, p.scope.bid_id, member.document_version_id, "b" * 64, "c" * 64, coverage),
    )
    if pages:
        c.execute(
            """INSERT INTO design.pages SELECT bid_id,%s,physical_page,printed_label,width,height,rotation,quality,gaps
            FROM design.pages WHERE parse_id=%s AND physical_page=1""",
            (new_run, member.parse.parse_run_id),
        )
    with pytest.raises(PackageError, match="PARSE_INCOMPLETE"):
        read_parse_identity(c, p.scope.bid_id, member.document_version_id, new_run)
    unknown = replace(
        member, parse=ParseIdentity("not_frozen", reason="parser failed or missing pages")
    )
    save_revision(c, replace(p, members=(unknown,)), expected_digest=None)
    assert not load_revision(c, p.scope.bid_id, p.revision_id).formal_eligible


@pytest.mark.parametrize(
    "malformation",
    ["empty", "missing_members", "parse_missing_digest", "integer_digest", "bad_part_range"],
)
def test_direct_sql_cannot_commit_malformed_manifest(world, malformation):
    from packages.domain.review_identity import digest

    c, p = world["c"], world["package"]
    save_revision(c, p, expected_digest=None)
    candidate = p.next_revision(uid(), p.members)
    value = candidate.manifest()
    if malformation == "empty":
        value = {}
    elif malformation == "missing_members":
        del value["members"]
    elif malformation == "parse_missing_digest":
        del value["members"][0]["parse"]["evidence_digest"]
    elif malformation == "integer_digest":
        value["members"][0]["file_digest"] = int("1" * 64)
    else:
        value["members"][0]["parts"][0]["last_page"] = 99
    supplied_digest = "f" * 64 if malformation == "integer_digest" else digest(value)
    with pytest.raises(psycopg.Error), c.transaction():
        c.execute(
            """INSERT INTO design.bid_package_revisions
            (id,package_id,revision,predecessor_digest,digest,manifest,identity_authority_id,identity_digest,bidder_status,identity_snapshot)
            SELECT %s,package_id,2,digest,%s,%s,identity_authority_id,identity_digest,bidder_status,identity_snapshot
            FROM design.bid_package_revisions WHERE id=%s""",
            (candidate.revision_id, supplied_digest, Jsonb(value), p.revision_id),
        )
        c.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_deferred_constraint_rejects_missing_member_rows(world):
    c, p = world["c"], world["package"]
    save_revision(c, p, expected_digest=None)
    candidate = p.next_revision(uid(), p.members)
    with pytest.raises(psycopg.Error, match="package_revision_incomplete"), c.transaction():
        c.execute(
            """INSERT INTO design.bid_package_revisions
            (id,package_id,revision,predecessor_digest,digest,manifest,identity_authority_id,identity_digest,bidder_status,identity_snapshot)
            SELECT %s,package_id,2,digest,%s,%s,identity_authority_id,identity_digest,bidder_status,identity_snapshot
            FROM design.bid_package_revisions WHERE id=%s""",
            (
                candidate.revision_id,
                candidate.manifest_digest,
                Jsonb(candidate.manifest()),
                p.revision_id,
            ),
        )
        c.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.parametrize("field", ["package_id", "revision_id"])
@pytest.mark.parametrize("malformation", ["missing", "null", "empty", "number", "mismatch"])
def test_direct_sql_manifest_ids_cannot_bypass_row_identity_with_null_or_wrong_type(
    world, field, malformation
):
    from packages.domain.review_identity import digest

    c, p = world["c"], world["package"]
    save_revision(c, p, expected_digest=None)
    candidate = p.next_revision(uid(), p.members)
    value = candidate.manifest()
    if malformation == "missing":
        del value[field]
    else:
        value[field] = {"null": None, "empty": "", "number": 123, "mismatch": uid()}[malformation]
    with pytest.raises(psycopg.Error), c.transaction():
        c.execute(
            """INSERT INTO design.bid_package_revisions
            (id,package_id,revision,predecessor_digest,digest,manifest,identity_authority_id,identity_digest,bidder_status,identity_snapshot)
            SELECT %s,package_id,2,digest,%s,%s,identity_authority_id,identity_digest,bidder_status,identity_snapshot
            FROM design.bid_package_revisions WHERE id=%s""",
            (candidate.revision_id, digest(value), Jsonb(value), p.revision_id),
        )
        c.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert (
        c.execute(
            "SELECT id FROM design.bid_package_revisions WHERE id=%s", (candidate.revision_id,)
        ).fetchone()
        is None
    )


def test_corrupt_loaded_record_returns_stable_domain_error(world, monkeypatch):
    from packages.domain import bid_package_repository as repository

    monkeypatch.setattr(repository, "_one", lambda *args: {"manifest": {}, "digest": "f" * 64})
    p = world["package"]
    with pytest.raises(PackageError, match="PACKAGE_STORED_MANIFEST_CORRUPT"):
        repository.load_revision(world["c"], p.scope.bid_id, p.revision_id)


@pytest.mark.parametrize(
    "field", ["file_digest", "parser_digest", "config_digest", "evidence_digest", "page_count"]
)
def test_direct_sql_cannot_freeze_forged_parse_binding(world, field):
    c, p = world["c"], world["package"]
    member = p.members[0]
    values = {
        "parse_run_id": member.parse.parse_run_id,
        "bid_id": p.scope.bid_id,
        "document_version_id": member.document_version_id,
        "file_digest": member.file_digest,
        "parser_digest": member.parse.parser_digest,
        "config_digest": member.parse.config_digest,
        "evidence_digest": member.parse.evidence_digest,
        "page_count": member.page_count,
    }
    values[field] = 3 if field == "page_count" else "e" * 64
    with pytest.raises(psycopg.Error, match="package_parse_binding_invalid"), c.transaction():
        c.execute(
            """INSERT INTO design.bid_package_parse_bindings
            (parse_run_id,bid_id,document_version_id,file_digest,parser_digest,config_digest,evidence_digest,page_count)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
            tuple(values.values()),
        )


def test_same_bytes_new_parse_can_append_without_changing_old_frozen_package(world):
    c, p = world["c"], world["package"]
    save_revision(c, p, expected_digest=None)
    old_member, new_run = p.members[0], uid()
    c.execute(
        """INSERT INTO design.parse_runs
        (id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps)
        SELECT %s,bid_id,document_version_id,%s,config_digest,page_count,coverage,gaps
        FROM design.parse_runs WHERE id=%s""",
        (new_run, "e" * 64, old_member.parse.parse_run_id),
    )
    c.execute(
        """INSERT INTO design.pages
        SELECT bid_id,%s,physical_page,printed_label,width,height,rotation,quality,gaps
        FROM design.pages WHERE parse_id=%s""",
        (new_run, old_member.parse.parse_run_id),
    )
    for row in c.execute(
        "SELECT id FROM design.evidence_blocks WHERE parse_id=%s", (old_member.parse.parse_run_id,)
    ).fetchall():
        c.execute(
            """INSERT INTO design.evidence_blocks
            SELECT %s,bid_id,%s,physical_page,ordinal,kind,text_content,bbox,structure,digest
            FROM design.evidence_blocks WHERE id=%s""",
            (uid(), new_run, row["id"]),
        )
    identity = read_parse_identity(c, p.scope.bid_id, old_member.document_version_id, new_run)
    revised = p.next_revision(uid(), (replace(old_member, parse=identity),))
    save_revision(c, revised, expected_digest=p.manifest_digest)
    assert load_revision(c, p.scope.bid_id, p.revision_id) == p
    assert load_revision(c, p.scope.bid_id, revised.revision_id) == revised
    assert revised.members[0].file_digest == old_member.file_digest
    assert revised.members[0].parse.evidence_digest != old_member.parse.evidence_digest


def test_sql_canonical_json_matches_shared_protocol_for_unicode_and_safe_integers(world):
    from packages.domain.review_identity import canonical

    value = {"z": [True, None, 9007199254740991], "a": '汉字\n\t"\\😀'}
    observed = (
        world["c"]
        .execute("SELECT design.package_canonical_json(%s) AS value", (Jsonb(value),))
        .fetchone()["value"]
    )
    assert observed.encode("utf-8") == canonical(value)


def test_two_connection_revocation_is_not_hidden_by_repeatable_read_snapshot(monkeypatch):
    monkeypatch.setenv("WORKBENCH_ENV_FILE", "explicit-test-no-profile-read")
    from packages.identity.repository import record_binding

    with connect() as creator:
        w = seed(creator)
        p = w["package"]
    with connect() as stale:
        stale.rollback()
        stale.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        before = stale.execute(
            "SELECT count(*) AS n FROM design.audit_entries WHERE bid_id=%s", (p.scope.bid_id,)
        ).fetchone()["n"]
        with connect() as revoker:
            record_binding(
                revoker,
                p.scope.bid_id,
                w["actor"],
                None,
                reason="explicit revocation after old snapshot",
                confirmed=False,
            )
        assert (
            stale.execute(
                "SELECT count(*) AS n FROM design.audit_entries WHERE bid_id=%s", (p.scope.bid_id,)
            ).fetchone()["n"]
            == before
        )
        with pytest.raises(PackageError, match="ISOLATION_REQUIRES_READ_COMMITTED"):
            save_revision(stale, p, expected_digest=None)


def test_stable_lot_round_identity_is_unique_independent_of_display_name(world):
    c, scope = world["c"], world["scope"]
    with pytest.raises(psycopg.errors.UniqueViolation), c.transaction():
        c.execute(
            """INSERT INTO design.bid_rounds(id,engineering_project_id,lot,lot_id,round_no)
            VALUES(%s,%s,'another alias for same lot',%s,1)""",
            (uid(), scope.engineering_project_id, scope.lot_id),
        )
    c.execute(
        """INSERT INTO design.bid_rounds(id,engineering_project_id,lot,lot_id,round_no)
        VALUES(%s,%s,'same stable lot second round',%s,2)""",
        (uid(), scope.engineering_project_id, scope.lot_id),
    )


def test_two_distinct_stable_lots_may_have_same_display_name_and_round_number(world):
    c, scope = world["c"], world["scope"]
    other_lot = uid()
    c.execute(
        "INSERT INTO design.engineering_lots VALUES(%s,%s,'lot A')",
        (other_lot, scope.engineering_project_id),
    )
    c.execute(
        """INSERT INTO design.bid_rounds(id,engineering_project_id,lot,lot_id,round_no)
        VALUES(%s,%s,'lot A',%s,1)""",
        (uid(), scope.engineering_project_id, other_lot),
    )


def test_direct_sql_unfrozen_member_cannot_claim_wrong_file_digest(world):
    from packages.domain.review_identity import digest

    c, p = world["c"], world["package"]
    unknown = replace(
        p.members[0],
        file_digest="e" * 64,
        parse=ParseIdentity("not_frozen", reason="awaiting parse"),
    )
    candidate = replace(p, members=(unknown,))
    # First save a valid package, then try a new immutable revision entirely through SQL.
    save_revision(c, p, expected_digest=None)
    candidate = p.next_revision(uid(), candidate.members)
    frozen_identity = load_frozen_identity(c, p.scope.bid_id, p.revision_id)
    with pytest.raises(psycopg.Error, match="package_document_file_mismatch"), c.transaction():
        c.execute(
            """INSERT INTO design.bid_package_revisions
            (id,package_id,revision,predecessor_digest,digest,manifest,identity_authority_id,identity_digest,bidder_status,identity_snapshot)
            VALUES(%s,%s,2,%s,%s,%s,%s,%s,'confirmed',%s)""",
            (
                candidate.revision_id,
                p.package_id,
                p.manifest_digest,
                digest(candidate.manifest()),
                Jsonb(candidate.manifest()),
                frozen_identity["authority_id"],
                frozen_identity["digest"],
                Jsonb(frozen_identity),
            ),
        )
        c.execute(
            """INSERT INTO design.bid_package_members
            (revision_id,member_id,ordinal,bid_id,document_version_id,file_digest,parse_run_id,payload)
            VALUES(%s,%s,0,%s,%s,%s,null,%s)""",
            (
                candidate.revision_id,
                unknown.member_id,
                p.scope.bid_id,
                unknown.document_version_id,
                unknown.file_digest,
                Jsonb(candidate.manifest()["members"][0]),
            ),
        )
