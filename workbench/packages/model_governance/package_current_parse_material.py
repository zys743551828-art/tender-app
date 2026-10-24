"""Complete native parse material through the existing independent source role.

No configuration, connection creation, privilege repair or latest-parse lookup.
The source audit and limits run before native text/geometry leaves PostgreSQL.
"""

from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import NoReturn

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_sources as sources
from packages.model_governance.technical_png import digest_bytes

EXTRA_FIELDS = {"parser_digest", "config_digest"}


class CurrentParseMaterialError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise CurrentParseMaterialError("CURRENT_PARSE_MATERIAL_" + code)


@dataclass(frozen=True, repr=False)
class CurrentParseMaterial:
    metadata: dict
    documents: list[dict]


def method_digest():
    return digest(
        {
            "version": "package-current-parse-material-method/1",
            "source_digest": digest_bytes(Path(__file__).read_bytes()),
            "source_method_digest": sources.method_digest(),
            "extra_identity_fields": sorted(EXTRA_FIELDS),
            "authority_grants": False,
        }
    )


def observe(connection, *, bid_id, expected_documents, expected_method_digest):
    sources._uuid(bid_id)
    if (
        not isinstance(expected_documents, list)
        or not 1 <= len(expected_documents) <= sources.MAX_DOCUMENTS
    ):
        fail("DOCUMENT_LIMIT")
    expected = []
    for row in expected_documents:
        if not isinstance(row, dict) or set(row) != sources.DOCUMENT_FIELDS | EXTRA_FIELDS:
            fail("DOCUMENT_FIELDS")
        for key in EXTRA_FIELDS:
            if (
                not isinstance(row[key], str)
                or len(row[key]) != 64
                or any(c not in "0123456789abcdef" for c in row[key])
            ):
                fail("IDENTITY_INVALID")
        expected.append({k: row[k] for k in sources.DOCUMENT_FIELDS})
    sources._expected(expected)
    frozen = {row["document_version_id"]: dict(row) for row in expected_documents}
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    if connection.info.transaction_status != TransactionStatus.IDLE:
        fail("IDLE_CONNECTION_REQUIRED")
    failure = None
    try:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as c:
                c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                c.execute("SET LOCAL statement_timeout='5s'")
                sources._role(c)
                at = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
                identities, counts = sources._documents(c, bid_id, expected)
                graph = sources._graph(c, bid_id, expected, at)
                documents = []
                for row in identities:
                    selected = frozen[row["document_version_id"]]
                    native = c.execute(
                        "SELECT parser_digest,config_digest FROM design.parse_runs WHERE bid_id=%s AND document_version_id=%s AND id=%s",
                        (bid_id, row["document_version_id"], row["parse_run_id"]),
                    ).fetchone()
                    if native is None or any(native[k] != selected[k] for k in EXTRA_FIELDS):
                        fail("PARSER_CONFIG_CHANGED")
                    pages = c.execute(
                        "SELECT physical_page,printed_label,width::text,height::text,rotation,quality,gaps::text FROM design.pages WHERE bid_id=%s AND parse_id=%s ORDER BY physical_page",
                        (bid_id, row["parse_run_id"]),
                    ).fetchall()
                    blocks = c.execute(
                        "SELECT id::text,physical_page,ordinal,kind,text_content,bbox::text,structure::text,digest::text FROM design.evidence_blocks WHERE bid_id=%s AND parse_id=%s ORDER BY physical_page,ordinal,id",
                        (bid_id, row["parse_run_id"]),
                    ).fetchall()
                    # Match the exact same records returned, not only a prior query.
                    if (
                        digest(
                            {
                                "identity_version": "package-parse-evidence/1",
                                "parse_run_id": row["parse_run_id"],
                                "pages": pages,
                                "blocks": blocks,
                            }
                        )
                        != row["parse_digest"]
                    ):
                        fail("PARSE_CONTENT_CHANGED")
                    documents.append({**selected, "pages": pages, "blocks": blocks})
                if len(canonical(documents)) > sources.MAX_METADATA_BYTES:
                    fail("MATERIAL_LIMIT")
                if method_digest() != method:
                    fail("METHOD_CHANGED")
    except sources.CurrentSourceError as error:
        # The source port only emits controlled codes, never native SQL text.
        failure = str(error)
    except psycopg.Error:
        failure = "CURRENT_PARSE_MATERIAL_NATIVE_UNAVAILABLE"
    if failure:
        raise CurrentParseMaterialError(failure)
    public = {
        "version": "package-current-parse-material/1",
        "bid_id": bid_id,
        "observed_at": at.astimezone(timezone.utc).isoformat(),
        "method_digest": method,
        "documents_digest": digest(documents),
        "counts": counts,
        "graph": graph,
        "native_parse_content_reverified": True,
        "original_bytes_reverified": False,
        "necessary_scope_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "historical_existence_verified": False,
    }
    return CurrentParseMaterial(public | {"digest": digest(public)}, documents)
