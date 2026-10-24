"""Owned complete original collection from native scope; no input authority.

Connections and a pure private URL signer are supplied by a controlled process.
This module discovers no credentials, grants no permissions and publishes no jobs.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from psycopg.pq import TransactionStatus

from packages.domain.providers import original_bytes as byte_port
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_original as original
from packages.model_governance import package_current_scope as scope
from packages.model_governance.technical_png import digest_bytes

MAX_DOCUMENTS = 32
MAX_TOTAL_BYTES = 64 * 1024 * 1024


class CurrentOriginalSetError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise CurrentOriginalSetError("CURRENT_ORIGINAL_SET_" + code)


@dataclass(frozen=True, repr=False)
class CurrentOriginalSet:
    metadata: dict
    scope_facts: dict
    originals: dict[str, bytes]


def method_digest():
    return digest(
        {
            "version": "package-current-original-set-method/1",
            "source_digest": digest_bytes(Path(__file__).read_bytes()),
            "scope_method_digest": scope.method_digest(),
            "original_method_digest": original.method_digest(),
            "byte_method_digest": byte_port.method_digest(),
            "maximum_documents": MAX_DOCUMENTS,
            "maximum_total_bytes": MAX_TOTAL_BYTES,
            "authority_grants": False,
        }
    )


def _files(facts):
    files = facts["scope"]["manifest"]["original_verification"]["files"]
    if not 1 <= len(files) <= MAX_DOCUMENTS:
        fail("DOCUMENT_LIMIT")
    if (
        len({row["document_version_id"] for row in files}) != len(files)
        or any(
            type(row["byte_size"]) is not int or not 1 <= row["byte_size"] <= byte_port.MAX_BYTES
            for row in files
        )
        or sum(row["byte_size"] for row in files) > MAX_TOTAL_BYTES
    ):
        fail("ORIGINAL_LIMIT")
    return sorted(files, key=lambda row: row["document_version_id"])


def _stable_locator(observation):
    return canonical(
        {k: v for k, v in observation.metadata.items() if k not in {"observed_at", "digest"}}
    )


async def collect(
    scope_connection,
    original_connection,
    *,
    bid_id,
    scope_id,
    expected_scope_digest,
    expected_method_digest,
    profile,
    url_for_locator,
    byte_client=None,
):
    """Collect every native frozen file, then independently reobserve all sources.

    No DB transaction spans network I/O. The final observations are fresh
    snapshots, not a durable binding, atomic validity promise or send lease.
    """
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    scope_method = scope.method_digest()
    original_method = original.method_digest()
    byte_method = byte_port.method_digest()
    args = {"bid_id": bid_id, "scope_id": scope_id, "expected_scope_digest": expected_scope_digest}
    initial = scope.observe(scope_connection, **args, expected_method_digest=scope_method)
    files = _files(initial.metadata)
    client = byte_port.OriginalByteClient() if byte_client is None else byte_client
    content, receipts, locators = {}, [], {}
    for row in files:
        doc = row["document_version_id"]
        located = original.observe(
            original_connection,
            **args,
            document_version_id=doc,
            expected_original_digest=row["digest"],
            expected_method_digest=original_method,
        )
        if located.metadata["source_byte_size"] != row["byte_size"]:
            fail("FILE_BINDING_CHANGED")
        failure = False
        try:
            url = url_for_locator(located.locator)
        except Exception:
            failure = True
        if failure:
            fail("URL_PREPARATION_FAILED")
        if any(
            c.info.transaction_status != TransactionStatus.IDLE
            for c in (scope_connection, original_connection)
        ):
            fail("IDLE_CONNECTIONS_REQUIRED")
        request = byte_port.prepare_get(
            url=url,
            profile=profile,
            bid_id=bid_id,
            scope_id=scope_id,
            scope_digest=expected_scope_digest,
            document_version_id=doc,
            source_digest=row["digest"],
            source_byte_size=row["byte_size"],
        )
        result = await client.read(
            request,
            expected_request_digest=request.metadata["digest"],
            expected_method_digest=byte_method,
        )
        content[doc] = result.data
        locators[doc] = located
        receipts.append(
            {
                "document_version_id": doc,
                "initial_locator_observation": located.metadata,
                "byte_receipt": result.metadata,
            }
        )
    final = scope.observe(scope_connection, **args, expected_method_digest=scope_method)
    if _files(final.metadata) != files:
        fail("FILE_SET_CHANGED")
    for row, receipt in zip(files, receipts, strict=True):
        located = original.observe(
            original_connection,
            **args,
            document_version_id=row["document_version_id"],
            expected_original_digest=row["digest"],
            expected_method_digest=original_method,
        )
        if _stable_locator(located) != _stable_locator(locators[row["document_version_id"]]):
            fail("LOCATOR_CHANGED")
        receipt["final_locator_observation"] = located.metadata
    if method_digest() != method:
        fail("METHOD_CHANGED")
    metadata = {
        "version": "package-current-original-set/1",
        "bid_id": bid_id,
        "scope_id": scope_id,
        "scope_digest": expected_scope_digest,
        "method_digest": method,
        "initial_scope_observation_digest": initial.metadata["digest"],
        "final_scope_observation_digest": final.metadata["digest"],
        "file_count": len(files),
        "total_bytes": sum(len(raw) for raw in content.values()),
        "files": receipts,
        "native_scope_and_complete_original_set_observed": True,
        "native_parse_content_reverified": False,
        "necessary_scope_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "historical_existence_verified": False,
    }
    return CurrentOriginalSet(metadata | {"digest": digest(metadata)}, final.metadata, content)
