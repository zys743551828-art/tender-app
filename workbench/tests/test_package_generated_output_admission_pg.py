"""Real nonowner generated-output new-use checks over an exact saved package.

The Word is actually built by the existing Worker. Its small parse is explicitly
synthetic DB fixture data: these cases test qualification/transaction binding,
not real Word parsing, image rendering, or model quality. Run PG serially.
"""
# ruff: noqa: F401,F811

import os
from uuid import UUID, uuid4

import pytest
from test_authoring_package_adoptions_pg import adopt, build, database, env

from packages.authoring import package_outputs
from packages.domain import bid_package_review_documents as documents
from packages.domain import bid_package_service as packages
from packages.domain.runtime import DomainError, connection, sha
from packages.rag.indexing import ensure_parse_sources, original_source_id

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires serial isolated PG17 generated-output qualification fixture",
)


@pytest.fixture
def parsed_package(env):
    build_id, request, computed = build(env)
    key = uuid4().hex
    ack, _ = adopt(env, build_id, request, key=key)
    document = UUID(request["member"]["document_version_id"])
    parse, evidence = uuid4(), uuid4()
    owner = env["database"]["owner"]
    with owner.transaction():
        owner.execute("SET LOCAL search_path TO design,public")
        owner.execute(
            """INSERT INTO parse_runs
            (id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps)
            VALUES(%s,%s,%s,%s,%s,1,'complete','[]')""",
            (parse, env["bid"], document, sha("explicit-synthetic-parser"), sha("fixture-only")),
        )
        owner.execute(
            """INSERT INTO pages
            (bid_id,parse_id,physical_page,width,height,rotation,quality,gaps)
            VALUES(%s,%s,1,100,100,0,'usable','[]')""",
            (env["bid"], parse),
        )
        owner.execute(
            """INSERT INTO evidence_blocks
            (id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest)
            VALUES(%s,%s,%s,1,0,'text','explicit synthetic parsed body',%s)""",
            (evidence, env["bid"], parse, sha(b"explicit synthetic parsed body")),
        )
    # Runtime registration must use the actual nonowner Worker transaction;
    # the fresh-schema fixture keeps its owner connection in autocommit mode.
    with connection(True) as c:
        ensure_parse_sources(c, env["bid"], parse, publish_readable=True)
    member = request["member"] | {
        "parse_run_id": str(parse),
        "parts": [
            {
                "part_id": "body-pages",
                "category": "technical",
                "first_page": 1,
                "last_page": 1,
                "shared_attachment": False,
                "heading_path": [],
            }
        ],
    }
    with connection() as c:
        packages.lock_bid(c, env["bid"])
        old = packages.head(c, env["bid"], ack["body"]["package"]["manifest"]["package_id"])
        revision = packages.create_revision(c, env["bid"], {"members": [member]}, old)
        saved = packages.view(c, revision)
    return env | {
        "build_id": build_id,
        "request": request,
        "adoption_key": key,
        "adoption_ack": ack,
        "package": saved,
        "member": saved["manifest"]["members"][0],
        "computed": computed,
    }


def source_heads(case):
    with connection() as c:
        return c.execute(
            """SELECT h.* FROM retrieval.source_heads h
            WHERE h.source_id IN
              (SELECT ancestor_id FROM retrieval.source_ancestors WHERE source_id=%s)
            ORDER BY h.source_id""",
            (original_source_id(UUID(case["member"]["document_version_id"])),),
        ).fetchall()


@pytest.mark.parametrize("worker", [False, True])
def test_current_authoring_basis_change_blocks_saved_package_new_use_without_parse_or_graph_change(
    parsed_package, worker, monkeypatch
):
    case = parsed_package
    bid, member = str(case["bid"]), case["member"]
    selection = {
        "bid_id": bid,
        "target": {"manifest": {"members": [member]}},
        "authority": {"manifest": {"members": []}},
    }
    graph = source_heads(case)
    with connection(worker) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        assert c.execute("SELECT current_user AS role").fetchone()["role"] != "nobody"
        admitted = documents.generated_observations(c, selection)
        assert admitted[0]["admission"]["state"] == "matched"
        before = documents.read_member(c, bid, member)
        assert before["parse_id"] == UUID(member["parse"]["parse_run_id"])
    # This change does not withdraw any source node or change parse bytes. The
    # generated output's original authoring qualification nevertheless becomes
    # invalid, because its cited body is no longer a current authoring basis.
    with connection() as c:
        packages.lock_bid(c, bid)
        c.execute("UPDATE design.bid_profiles SET current_body_id=NULL WHERE bid_id=%s", (bid,))
    assert source_heads(case) == graph
    with connection(worker) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        assert documents.evidence_matches(c, selection)
        current = documents.generated_observations(c, selection)
        assert current[0]["admission"]["state"] == "blocked"
        assert current[0]["admission"]["reason_code"] == "AUTHORING_SOURCE_STALE"
        with pytest.raises(DomainError) as error:
            documents.read_member(c, bid, member)
        assert error.value.code == "PACKAGE_REVIEW_GENERATED_OUTPUT_UNPROVEN"
    # Historical package contents and the exact old command ACK remain readable.
    with connection() as c:
        historic = packages.historical(
            c,
            bid,
            case["package"]["manifest"]["package_id"],
            case["package"]["manifest"]["revision_id"],
        )
        assert packages.view(c, historic) == case["package"]
    monkeypatch.setattr(
        package_outputs,
        "verify_bytes",
        lambda *_args: pytest.fail("exact historical adoption replay must not reread objects"),
    )
    replayed, replay = adopt(case, case["build_id"], case["request"], key=case["adoption_key"])
    assert replay and replayed == case["adoption_ack"]
