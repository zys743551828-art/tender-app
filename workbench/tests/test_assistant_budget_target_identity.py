"""Real target RPC against minimal identity facts; not live evidence qualification."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from packages.assistant.intent_identity import IDENTITY_FACTS, association_key


@pytest.fixture(scope="module")
def target_database():
    dsn = os.environ.get("FUSION_BUDGET_TARGET_TEST_DSN")
    if not dsn:
        pytest.skip("Explicit disposable fusion_budget_target database required")
    with psycopg.connect(dsn) as c:
        assert c.info.dbname == "fusion_budget_target"
        assert 170000 <= c.info.server_version < 180000
        c.execute("CREATE SCHEMA design")
        c.execute("SET LOCAL search_path=design,public")
        definitions = {
            "bid_profiles": "bid_id uuid,round_id uuid,bidder_id uuid",
            "bid_rounds": "id uuid,engineering_project_id uuid,lot_id uuid,lot text,round_no integer",
            "bidders": "id uuid,name text",
            "engineering_projects": "id uuid,title text,region text,engineering_type text",
            "audit_entries": "id uuid,bid_id uuid,event_type text,payload jsonb,created_at timestamptz DEFAULT clock_timestamp()",
            "fact_heads": "bid_id uuid,fact_set_id uuid",
            "fact_items": "id uuid,bid_id uuid,fact_set_id uuid,name text,value jsonb,evidence_ids uuid[]",
            "decision_heads": "bid_id uuid,object_kind text,object_id uuid,decision_id uuid",
            "decisions": "id uuid,decision text,evidence_ids uuid[]",
            "findings": "id uuid,bid_id uuid,carried_from_id uuid",
            "rule_items": "id uuid,bid_id uuid,manual_origin_rule_id uuid,kind text,statement text",
            "sections": "id uuid,bid_id uuid,head_revision bigint",
        }
        for name, definition in definitions.items():
            c.execute(f"CREATE TABLE design.{name}({definition})")
        root = Path(__file__).parents[1]
        for path, names in [
            (root / "packages/contracts/sql/bid-packages.sql", ["package_canonical_json"]),
            (
                root / "packages/identity/sql/stable-lot-identity.sql",
                ["design.identity_association_v2", "design.identity_snapshot_v2"],
            ),
        ]:
            helper_source = path.read_text(encoding="utf-8")
            for name in names:
                start = helper_source.index(f"CREATE FUNCTION {name}(")
                c.execute(
                    helper_source[
                        start : helper_source.index("$$;", helper_source.index("AS $$", start)) + 3
                    ]
                )
        source = (Path(__file__).parents[1] / "packages/assistant/sql/intent-budget.sql").read_text(
            encoding="utf-8"
        )
        for name in ("assistant_normalize_question", "assistant_check_target"):
            start = source.index(f"CREATE FUNCTION design.{name}(")
            c.execute(source[start : source.index("$$;", source.index("AS $$", start)) + 3])
        try:
            yield c
        finally:
            c.rollback()


@pytest.fixture
def world(target_database):
    with target_database.transaction(force_rollback=True):
        c = target_database
        bid, round_id, bidder, project, lot, authority, fact_set, actor = [
            uuid4() for _ in range(8)
        ]
        c.execute("INSERT INTO design.bid_profiles VALUES(%s,%s,%s)", (bid, round_id, bidder))
        c.execute(
            "INSERT INTO design.bid_rounds VALUES(%s,%s,%s,'same display name',1)",
            (round_id, project, lot),
        )
        c.execute("INSERT INTO design.bidders VALUES(%s,'synthetic bidder')", (bidder,))
        c.execute(
            "INSERT INTO design.engineering_projects VALUES(%s,'synthetic project','synthetic region','synthetic type')",
            (project,),
        )
        c.execute(
            "INSERT INTO design.audit_entries(id,bid_id,event_type,payload) VALUES(%s,NULL,'identity.bidder_registered',%s)",
            (uuid4(), Jsonb({"bidder_id": str(bidder)})),
        )
        payload = {
            "identity_version": "bid-identity/2",
            "identity_epoch": 1,
            "confirmed": True,
            "after": c.execute("SELECT design.identity_association_v2(%s)", (bid,)).fetchone()[0],
        }
        c.execute(
            "INSERT INTO design.audit_entries(id,bid_id,event_type,payload) VALUES(%s,%s,'identity.bound',%s)",
            (authority, bid, Jsonb(payload)),
        )
        c.execute("INSERT INTO design.fact_heads VALUES(%s,%s)", (bid, fact_set))
        values = {name: "synthetic-" + name for name in IDENTITY_FACTS}
        canonical = association_key(values)
        proofs = []
        for name, value in values.items():
            fact, decision, evidence = uuid4(), uuid4(), uuid4()
            c.execute(
                "INSERT INTO design.fact_items VALUES(%s,%s,%s,%s,%s,%s)",
                (fact, bid, fact_set, name, Jsonb(value), [evidence]),
            )
            c.execute(
                "INSERT INTO design.decisions VALUES(%s,'confirmed',%s)", (decision, [evidence])
            )
            c.execute(
                "INSERT INTO design.decision_heads VALUES(%s,'fact',%s,%s)", (bid, fact, decision)
            )
            proofs.append(
                {
                    "id": str(fact),
                    "name": name,
                    "value": value,
                    "decision_id": str(decision),
                    "evidence_ids": [str(evidence)],
                }
            )
        target = {
            "kind": "project",
            "id": str(bid),
            "bid_id": str(bid),
            "purpose": "project_reference",
            "target_key": canonical + ":project:project",
            "canonical_project_key": canonical,
            "proof": {
                "identity_authority_id": str(authority),
                "fact_set_id": str(fact_set),
                "identity_facts": proofs,
                "canonical_project_key": canonical,
            },
        }
        yield c, target, actor


def check(c, target, actor):
    c.execute("SELECT design.assistant_check_target(%s,%s)", (Jsonb(target), actor))


def test_current_v2_stable_lot_and_same_five_facts_pass_identity_guard(world):
    c, target, actor = world
    check(c, target, actor)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE design.audit_entries SET payload=payload-'identity_version'",
        "UPDATE design.audit_entries SET payload=jsonb_set(payload,'{identity_version}','\"bid-identity/1\"')",
        "UPDATE design.audit_entries SET payload=jsonb_set(payload,'{after,lot_id}','null')",
        "UPDATE design.audit_entries SET payload=jsonb_set(payload,'{after,lot_id}','\"00000000-0000-0000-0000-000000000001\"')",
        "UPDATE design.bid_rounds SET lot_id=NULL",
        "UPDATE design.bid_rounds SET lot_id='00000000-0000-0000-0000-000000000002'",
        "UPDATE design.bidders SET name='changed same-ID bidder name'",
        "UPDATE design.engineering_projects SET title='changed project title'",
        "UPDATE design.engineering_projects SET region='changed region'",
        "UPDATE design.engineering_projects SET engineering_type='changed type'",
        "UPDATE design.bid_rounds SET lot='changed display lot'",
        "UPDATE design.bid_rounds SET round_no=2",
    ],
)
def test_old_binding_or_changed_same_named_stable_lot_is_rejected(world, mutation):
    c, target, actor = world
    check(c, target, actor)
    c.execute(mutation)
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="ASSISTANT_TARGET_IDENTITY_UNPROVEN"),
        c.transaction(),
    ):
        check(c, target, actor)


def test_general_private_target_does_not_require_project_identity(world):
    c, _, actor = world
    check(
        c,
        {
            "kind": "general",
            "id": None,
            "proof": None,
            "purpose": "general_reference",
            "target_key": "general:" + str(actor),
        },
        actor,
    )
