"""Execute evidence read SQL against synthetic SQLite rows; no PG/runtime acceptance claim."""

import json
import re
import sqlite3
from contextlib import contextmanager
from uuid import UUID

import pytest

from apps.api import main, review_routes
from packages.domain.runtime import DomainError
from packages.rag.indexing import original_source_id, parse_source_id


def identity(value):
    return str(UUID(int=value))


class ReadDatabase:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            ATTACH DATABASE ':memory:' AS retrieval;
            CREATE TABLE document_versions(id TEXT PRIMARY KEY);
            CREATE TABLE parse_runs(id TEXT PRIMARY KEY,document_version_id TEXT,
                created_at TEXT,coverage TEXT,gaps TEXT);
            CREATE TABLE pages(parse_id TEXT,physical_page INTEGER,width REAL,height REAL,
                rotation INTEGER,printed_label TEXT);
            CREATE TABLE evidence_blocks(id TEXT PRIMARY KEY,parse_id TEXT,physical_page INTEGER,
                ordinal INTEGER,kind TEXT,text_content TEXT,bbox TEXT);
            CREATE TABLE retrieval.source_nodes(id TEXT PRIMARY KEY,document_version_id TEXT);
            CREATE TABLE retrieval.source_heads(source_id TEXT PRIMARY KEY,status TEXT);
            CREATE TABLE retrieval.lineage_edges(child_id TEXT,parent_id TEXT);
            CREATE VIEW retrieval.source_ancestors AS WITH RECURSIVE walk(source_id,ancestor_id)
            AS (SELECT id,id FROM source_nodes UNION SELECT w.source_id,e.parent_id
                FROM walk w JOIN lineage_edges e ON e.child_id=w.ancestor_id)
            SELECT source_id,ancestor_id FROM walk;
            """
        )
        self.queries = []

    def execute(self, query, params=()):
        self.queries.append(query)
        query = re.sub(r"::(?:text|uuid\[\])", "", query)
        query = query.replace("=ANY(%s)", " IN (%s)")
        values = []
        for value in params:
            if isinstance(value, list):
                query = query.replace("%s", ",".join("?" for _ in value), 1)
                values.extend(str(item) for item in value)
            else:
                query = query.replace("%s", "?", 1)
                values.append(str(value) if isinstance(value, UUID) else value)
        cursor = self.db.execute(query, values)

        def row(value):
            if value is None:
                return None
            result = dict(value)
            for key in ("bbox", "gaps"):
                if key in result:
                    result[key] = json.loads(result[key])
            return result

        class Result:
            def fetchone(self):
                return row(cursor.fetchone())

            def fetchall(self):
                return [row(value) for value in cursor.fetchall()]

        return Result()

    @contextmanager
    def connection(self):
        yield self

    def node(self, node, document, status="published"):
        self.db.execute("INSERT INTO retrieval.source_nodes VALUES(?,?)", (node, document))
        self.db.execute("INSERT INTO retrieval.source_heads VALUES(?,?)", (node, status))

    def parse(self, document, parse, *, count=1, created="2026-10-20", status="published"):
        self.db.execute("INSERT OR IGNORE INTO document_versions VALUES(?)", (document,))
        self.db.execute(
            "INSERT INTO parse_runs VALUES(?,?,?,'complete','[]')", (parse, document, created)
        )
        self.db.execute("INSERT INTO pages VALUES(?,1,600,800,0,'1')", (parse,))
        evidence = [identity(UUID(parse).int * 1000 + n) for n in range(1, count + 1)]
        for n, eid in enumerate(evidence):
            self.db.execute(
                "INSERT INTO evidence_blocks VALUES(?,?,1,?,'text','合成引用','[1,2,3,4]')",
                (eid, parse, n),
            )
        source, root = str(parse_source_id(UUID(parse))), str(original_source_id(UUID(document)))
        if not self.db.execute(
            "SELECT 1 FROM retrieval.source_nodes WHERE id=?", (root,)
        ).fetchone():
            self.node(root, document)
        self.node(source, document, status)
        self.db.execute("INSERT INTO retrieval.lineage_edges VALUES(?,?)", (source, root))
        return evidence


@pytest.fixture
def database(monkeypatch):
    database = ReadDatabase()
    monkeypatch.setattr(main, "auth", lambda *_: None)
    monkeypatch.setattr(main, "connection", database.connection)
    monkeypatch.setattr(review_routes, "auth", lambda *_: None)
    monkeypatch.setattr(review_routes, "connection", database.connection)
    yield database
    database.db.close()


def detail(eid):
    return json.loads(review_routes.get_evidence(UUID(eid), None).body)


def listing(document):
    return main.document_evidence(UUID(document), None)


def test_withdrawn_original_has_same_status_and_quote_in_list_and_detail(database):
    document, parse = identity(1), identity(11)
    evidence = database.parse(document, parse, count=3)
    database.db.execute(
        "UPDATE retrieval.source_heads SET status='withdrawn' WHERE source_id=?",
        (str(original_source_id(UUID(document))),),
    )

    items = listing(document)["items"]

    assert [item["id"] for item in items] == evidence
    assert all(item["source_status"] == "withdrawn" for item in items)
    assert items == [detail(eid) for eid in evidence]


def test_old_parse_withdrawal_does_not_label_a_distinct_current_parse(database):
    document = identity(1)
    old = database.parse(document, identity(11), created="2026-10-19", status="withdrawn")
    current = database.parse(document, identity(12))

    assert listing(document)["items"] == [detail(current[0])]
    assert detail(current[0])["source_status"] == "published"
    assert detail(old[0])["source_status"] == "withdrawn"


def test_word_ancestor_withdrawal_reaches_pdf_list_and_detail(database):
    document, word = identity(1), identity(2)
    evidence = database.parse(document, identity(11))
    word_root = str(original_source_id(UUID(word)))
    database.node(word_root, word, "withdrawn")
    database.db.execute(
        "INSERT INTO retrieval.lineage_edges VALUES(?,?)",
        (str(original_source_id(UUID(document))), word_root),
    )

    assert detail(evidence[0])["source_status"] == "withdrawn"
    assert listing(document)["items"] == [detail(evidence[0])]


@pytest.mark.parametrize("unpublished", ["candidate", "missing_head", "missing_source"])
def test_unknown_or_candidate_sources_do_not_claim_published(database, unpublished):
    document, parse = identity(1), identity(11)
    evidence = database.parse(document, parse)
    source = str(parse_source_id(UUID(parse)))
    if unpublished == "candidate":
        database.db.execute(
            "UPDATE retrieval.source_heads SET status='candidate' WHERE source_id=?", (source,)
        )
    else:
        database.db.execute("DELETE FROM retrieval.source_heads WHERE source_id=?", (source,))
        if unpublished == "missing_source":
            database.db.execute("DELETE FROM retrieval.source_nodes WHERE id=?", (source,))

    assert detail(evidence[0])["source_status"] == "candidate"
    assert listing(document)["items"] == [detail(evidence[0])]


def test_list_read_query_count_is_bounded_independently_of_block_count(database):
    small, large = identity(1), identity(2)
    database.parse(small, identity(11))
    evidence = database.parse(large, identity(12), count=301)
    database.queries.clear()
    listing(small)
    small_queries = len(database.queries)
    database.queries.clear()

    items = listing(large)["items"]

    assert [item["id"] for item in items] == evidence
    assert len(database.queries) <= 4
    assert len(database.queries) == small_queries


def test_unparsed_document_keeps_pending_without_source_reads(database):
    document = identity(1)
    database.db.execute("INSERT INTO document_versions VALUES(?)", (document,))

    assert listing(document) == {
        "document_version_id": document,
        "parse_run_id": None,
        "coverage": "pending",
        "gaps": [],
        "items": [],
    }
    assert not any("retrieval." in query for query in database.queries)


def test_missing_evidence_still_returns_not_found(database):
    with pytest.raises(DomainError) as error:
        detail(identity(999))
    assert error.value.status == 404
