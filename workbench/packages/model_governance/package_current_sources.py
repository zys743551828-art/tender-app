"""Read native current sources through an independent, read-only purpose LOGIN.

This observation proves neither original object bytes nor necessary scope. It is
not a verification binding and cannot authorize a judgment job.
"""

from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from uuid import UUID, uuid5

from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from packages.domain import bid_package_repository as parses
from packages.domain.bid_packages import PackageError
from packages.domain.review_identity import digest
from packages.model_governance import read_purpose
from packages.model_governance.technical_png import digest_bytes

GROUP = "tender_current_source_verify"
NAMESPACE = UUID("8d6cdd5c-1a28-45c6-ac26-e293b1d16f42")
MAX_DOCUMENTS = 32
MAX_PAGES = 256
MAX_BLOCKS = 20000
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_NODES = 20000
MAX_EDGES = 20000
MAX_DEPTH = 64
TABLES = (
    "design.document_versions",
    "design.blobs",
    "design.parse_runs",
    "design.pages",
    "design.evidence_blocks",
    "retrieval.source_nodes",
    "retrieval.source_heads",
    "retrieval.lineage_edges",
)
METADATA_COLUMNS = {
    "design.blobs": {"id", "digest", "byte_size", "media_type"},
    "design.document_versions": {"id", "bid_id", "blob_id", "artifact_kind"},
}
DOCUMENT_FIELDS = {
    "document_version_id",
    "source_digest",
    "source_byte_size",
    "parse_run_id",
    "parse_digest",
    "page_count",
}


class CurrentSourceError(ValueError):
    pass


def fail(code):
    raise CurrentSourceError("CURRENT_SOURCE_" + code)


@dataclass(frozen=True, repr=False)
class CurrentSourceObservation:
    metadata: dict


def method_digest():
    root = Path(__file__).parents[1]
    names = (
        "model_governance/package_current_sources.py",
        "model_governance/read_purpose.py",
        "domain/bid_package_repository.py",
        "domain/bid_packages.py",
        "domain/review_identity.py",
    )
    return digest(
        {
            "version": "package-current-source-method/1",
            "files": {name: digest_bytes((root / name).read_bytes()) for name in names},
            "source_id_namespace": str(NAMESPACE),
            "tables": list(TABLES),
            "metadata_columns": {key: sorted(value) for key, value in METADATA_COLUMNS.items()},
            "limits": [
                MAX_DOCUMENTS,
                MAX_PAGES,
                MAX_BLOCKS,
                MAX_TEXT_BYTES,
                MAX_METADATA_BYTES,
                MAX_NODES,
                MAX_EDGES,
                MAX_DEPTH,
            ],
            "authority_grants": False,
        }
    )


def source_id(kind, identity):
    return str(uuid5(NAMESPACE, f"document-{kind}:{UUID(identity)}"))


def _uuid(value):
    try:
        if str(UUID(value)) != value:
            fail("INVALID_ID")
    except (ValueError, AttributeError, TypeError):
        fail("INVALID_ID")


def _expected(documents):
    if not isinstance(documents, list) or not 1 <= len(documents) <= MAX_DOCUMENTS:
        fail("DOCUMENT_LIMIT")
    seen = set()
    for row in documents:
        if not isinstance(row, dict) or set(row) != DOCUMENT_FIELDS:
            fail("DOCUMENT_FIELDS")
        for key in ("document_version_id", "parse_run_id"):
            _uuid(row[key])
        for key in ("source_digest", "parse_digest"):
            value = row[key]
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                fail("DOCUMENT_DIGEST")
        if (
            type(row["source_byte_size"]) is not int
            or not 1 <= row["source_byte_size"] <= 32 * 1024 * 1024
        ):
            fail("ORIGINAL_LIMIT")
        if type(row["page_count"]) is not int or not 1 <= row["page_count"] <= 128:
            fail("PAGE_LIMIT")
        if row["document_version_id"] in seen:
            fail("DOCUMENT_REUSED")
        seen.add(row["document_version_id"])
    if sum(row["page_count"] for row in documents) > MAX_PAGES:
        fail("PAGE_LIMIT")


def _role(c):
    policy = read_purpose.ReadPurpose(
        groups=frozenset({GROUP}),
        tables=frozenset(TABLES),
        columns=tuple((name, frozenset(columns)) for name, columns in METADATA_COLUMNS.items()),
    )
    try:
        read_purpose.require_read_purpose(c, policy)
    except read_purpose.ReadPurposeError as error:
        fail(error.code)


def _documents(c, bid_id, expected):
    actual, totals = [], {"pages": 0, "blocks": 0, "text_bytes": 0, "metadata_bytes": 0}
    for row in sorted(expected, key=lambda item: item["document_version_id"]):
        native = c.execute(
            "SELECT b.digest,b.byte_size,b.media_type,v.artifact_kind FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=%s AND v.id=%s",
            (bid_id, row["document_version_id"]),
        ).fetchone()
        if (
            native is None
            or native["digest"] != row["source_digest"]
            or native["byte_size"] != row["source_byte_size"]
            or native["media_type"] != "application/pdf"
            or native["artifact_kind"] not in {"source_original", "bid_body"}
        ):
            fail("ORIGINAL_BINDING")
        counts = c.execute(
            "SELECT count(*) AS blocks,coalesce(sum(octet_length(text_content)),0) AS text_bytes,coalesce(sum(octet_length(text_content)+coalesce(octet_length(bbox::text),0)+coalesce(octet_length(structure::text),0)+200),0) AS metadata_bytes FROM design.evidence_blocks WHERE bid_id=%s AND parse_id=%s",
            (bid_id, row["parse_run_id"]),
        ).fetchone()
        page_counts = c.execute(
            "SELECT count(*) AS pages,coalesce(sum(octet_length(coalesce(printed_label,''))+octet_length(gaps::text)+200),0) AS metadata_bytes FROM design.pages WHERE bid_id=%s AND parse_id=%s",
            (bid_id, row["parse_run_id"]),
        ).fetchone()
        totals["pages"] += page_counts["pages"]
        for key in ("blocks", "text_bytes", "metadata_bytes"):
            totals[key] += counts[key]
        totals["metadata_bytes"] += page_counts["metadata_bytes"]
        if any(
            totals[k] > maximum
            for k, maximum in (
                ("pages", MAX_PAGES),
                ("blocks", MAX_BLOCKS),
                ("text_bytes", MAX_TEXT_BYTES),
                ("metadata_bytes", MAX_METADATA_BYTES),
            )
        ):
            fail("PARSE_LIMIT")
        parse_size = c.execute(
            "SELECT coalesce(octet_length(gaps::text),0) AS bytes FROM design.parse_runs WHERE bid_id=%s AND document_version_id=%s AND id=%s",
            (bid_id, row["document_version_id"], row["parse_run_id"]),
        ).fetchone()
        if parse_size is None or parse_size["bytes"] > MAX_METADATA_BYTES:
            fail("PARSE_BINDING")
        totals["metadata_bytes"] += parse_size["bytes"]
        if totals["metadata_bytes"] > MAX_METADATA_BYTES:
            fail("PARSE_LIMIT")
        try:
            identity = parses.read_parse_identity(
                c.connection, bid_id, row["document_version_id"], row["parse_run_id"], lock=False
            )
        except PackageError:
            fail("PARSE_BINDING")
        if (
            identity.evidence_digest != row["parse_digest"]
            or page_counts["pages"] != row["page_count"]
        ):
            fail("PARSE_BINDING")
        actual.append(dict(row))
    return actual, totals


def _graph(c, bid_id, documents, now):
    roots, direct = {}, set()
    for row in documents:
        identity = (row["document_version_id"], row["source_digest"])
        original = source_id("original", row["document_version_id"])
        parsed = source_id("parse", row["parse_run_id"])
        roots[original] = roots[parsed] = identity
        direct.add((parsed, original))
    pending = set(roots)
    seen: set[str] = set()
    edges: set[tuple[str, str]] = set()
    nodes = {}
    for _ in range(MAX_DEPTH):
        if not pending:
            break
        if len(seen | pending) > MAX_NODES:
            fail("GRAPH_LIMIT")
        rows = c.execute(
            "SELECT n.id::text,n.document_version_id::text,n.digest,n.kind,n.policy_class,n.known_at,h.revision,h.status,h.valid_from,h.valid_until,v.bid_id::text AS bid_id,b.digest AS original_digest FROM retrieval.source_nodes n LEFT JOIN retrieval.source_heads h ON h.source_id=n.id LEFT JOIN design.document_versions v ON v.id=n.document_version_id LEFT JOIN design.blobs b ON b.id=v.blob_id WHERE n.id=ANY(%s::uuid[]) ORDER BY n.id",
            (sorted(pending),),
        ).fetchall()
        if {row["id"] for row in rows} != pending:
            fail("GRAPH_NODE_MISSING")
        for row in rows:
            if (
                row["bid_id"] != bid_id
                or row["kind"] != "document"
                or row["policy_class"] != "prebid_content"
                or row["digest"] != row["original_digest"]
                or row["known_at"] > now
                or row["status"] != "published"
                or row["revision"] is None
                or row["valid_from"] is None
                or row["valid_from"] > now
                or (row["valid_until"] is not None and row["valid_until"] <= now)
            ):
                fail("GRAPH_SOURCE_UNAVAILABLE")
            if (
                row["id"] in roots
                and (row["document_version_id"], row["digest"]) != roots[row["id"]]
            ):
                fail("GRAPH_ROOT_BINDING")
            nodes[row["id"]] = {
                key: (
                    value.astimezone(timezone.utc).isoformat()
                    if hasattr(value, "astimezone")
                    else value
                )
                for key, value in row.items()
            }
        outgoing = c.execute(
            "SELECT child_id::text,parent_id::text FROM retrieval.lineage_edges WHERE child_id=ANY(%s::uuid[]) ORDER BY child_id,parent_id LIMIT %s",
            (sorted(pending), MAX_EDGES - len(edges) + 1),
        ).fetchall()
        edges.update((r["child_id"], r["parent_id"]) for r in outgoing)
        if len(edges) > MAX_EDGES:
            fail("GRAPH_LIMIT")
        seen.update(pending)
        pending = {r["parent_id"] for r in outgoing} - seen
    if pending:
        fail("GRAPH_DEPTH_LIMIT")
    if not direct <= edges:
        fail("PARSE_ORIGINAL_EDGE_MISSING")
    # Recheck cycles even though the normal writer has an acyclicity trigger.
    remaining = set(seen)
    parents: dict[str, set[str]] = {key: set() for key in seen}
    for child, parent in edges:
        parents[child].add(parent)
    ready = {key for key in remaining if not parents[key]}
    while ready:
        remaining.difference_update(ready)
        previous = ready
        ready = set()
        for key in remaining:
            parents[key].difference_update(previous)
            if not parents[key]:
                ready.add(key)
    if remaining:
        fail("GRAPH_CYCLE")
    return {
        "roots": sorted(roots),
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": [list(edge) for edge in sorted(edges)],
    }


def observe(connection, *, bid_id, expected_documents, expected_method_digest):
    """Own the repeatable-read transaction; never borrow a caller's stale snapshot."""
    _uuid(bid_id)
    _expected(expected_documents)
    expected = [dict(row) for row in expected_documents]
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    if connection.info.transaction_status != TransactionStatus.IDLE:
        fail("IDLE_CONNECTION_REQUIRED")
    with connection.transaction():
        with connection.cursor(row_factory=dict_row) as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            c.execute("SET LOCAL statement_timeout='5s'")
            _role(c)
            at = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
            documents, counts = _documents(c, bid_id, expected)
            graph = _graph(c, bid_id, documents, at)
            if method_digest() != method:
                fail("METHOD_CHANGED")
            value = {
                "version": "package-current-source-observation/1",
                "bid_id": bid_id,
                "observed_at": at.astimezone(timezone.utc).isoformat(),
                "method_digest": method,
                "documents": documents,
                "counts": counts,
                "graph": graph,
                "native_parse_and_current_sources_reverified": True,
                "original_bytes_reverified": False,
                "necessary_scope_verified": False,
                "input_authority_granted": False,
                "execution_authorized": False,
                "historical_existence_verified": False,
            }
            return CurrentSourceObservation(value | {"digest": digest(value)})
