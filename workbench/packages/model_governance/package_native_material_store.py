"""Independent native private evidence bytes, never semantic/input authority."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from deploy import fusion_context_derivation as derivation
from deploy import fusion_material_derivation as material_derivation
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_material as current
from packages.model_governance import package_material_archive as archive
from packages.model_governance import package_material_scope_findings as findings
from packages.model_governance import package_scope_review_issuers as issuers
from packages.model_governance import package_technical_assets as assets
from packages.model_governance import package_technical_material as material
from packages.model_governance import read_purpose
from packages.storage.private_cas import is_digest, sha

WRITE_GROUP = "tender_material_store_write"
READ_GROUP = "tender_material_store_read"
PUT_RPC = "technical_material_store.put(uuid,uuid,text,uuid,jsonb,text[],bytea[])"
READ_RPC = "technical_material_store.read(uuid,uuid,text,text)"
SQL_FILE = Path(__file__).parents[2] / "deploy/sql/package-native-material-store.sql"
OBJECT_FIELDS = (
    "context_object",
    "source_observation_object",
    "derivation_object",
    "findings_object",
)
ROOT_FIELDS = frozenset(
    {
        "store_method_digest",
        "context_digest",
        "context_method_digest",
        "source_observation_digest",
        "derivation_observation_digest",
        "review_digest",
        "findings_digest",
    }
)
CAPS = (12 * 1024 * 1024, 2 * 1024 * 1024, 4 * 1024 * 1024, 8 * 1024 * 1024 + 4096)
FLAGS = frozenset(
    {
        "necessary_scope_verified",
        "native_binding_verified",
        "input_authority_granted",
        "execution_authorized",
        "historical_existence_verified",
    }
)
KNOWN_ERRORS = frozenset(
    "MATERIAL_STORE_" + s
    for s in (
        "OWNED_WRITE_TRANSACTION_REQUIRED",
        "OWNED_READ_TRANSACTION_REQUIRED",
        "INDEPENDENT_LOGIN_REQUIRED",
        "PACKET_INVALID",
        "CAPACITY_EXCEEDED",
        "REFERENCE_INVALID",
        "COMMAND_CONFLICT",
        "SCOPE_MISMATCH",
        "OBJECT_SET_INVALID",
        "OBJECT_INVALID",
        "DOCUMENT_INVALID",
        "OBJECT_CONFLICT",
        "NOT_FOUND",
        "OBJECT_NOT_IN_RECORD",
    )
)


class NativeMaterialStoreError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise NativeMaterialStoreError("MATERIAL_STORE_" + code)


@dataclass(frozen=True, repr=False)
class PreparedEvidence:
    live: derivation.LiveDerivedContext
    findings: findings.CheckedScopeFindings
    producer_method_digest: str
    packet: dict
    objects: dict[str, bytes]


@dataclass(frozen=True, repr=False)
class NativeEvidenceRecord:
    metadata: dict


@dataclass(frozen=True, repr=False)
class NativeEvidenceObject:
    record: NativeEvidenceRecord
    object_digest: str
    data: bytes


@dataclass(frozen=True, repr=False)
class StoredMaterialEvidence:
    record: NativeEvidenceRecord
    context_metadata: dict
    source_observation: dict
    derivation_observation: dict
    findings_metadata: dict
    image_blobs: dict[str, bytes]


def method_digest():
    # A renderer's platform-specific method remains a fixed producer claim in
    # the evidence. Store/read identity itself must work across host platforms.
    return digest(
        {
            "version": "package-native-material-store-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "sql_source": sha(SQL_FILE.read_bytes()),
            "archive_method": archive.method_digest(),
            "findings_method": findings.method_digest(),
            "derivation_source": sha(Path(derivation.__file__).read_bytes()),
            "derivation_verifier_source": sha(Path(material_derivation.__file__).read_bytes()),
            "issuer_audit_source": sha(Path(issuers.__file__).read_bytes()),
            "issuer_policy_sql_source": sha(issuers.SQL_FILE.read_bytes()),
            "limits": list(CAPS) + [384, 64 * 1024 * 1024],
            "qualification_granted": False,
        }
    )


def _uuid(value):
    valid = False
    try:
        valid = type(value) is str and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        pass
    if not valid:
        fail("ID_INVALID")


def _packet(value):
    if (
        type(value) is not dict
        or set(value) != ROOT_FIELDS | set(OBJECT_FIELDS) | {"version", "image_objects"}
        or value["version"] != "package-native-material-store-packet/1"
        or any(not is_digest(value[k]) for k in ROOT_FIELDS)
    ):
        fail("PACKET_INVALID")
    if type(value["image_objects"]) is not list or not 1 <= len(value["image_objects"]) <= 384:
        fail("CAPACITY_EXCEEDED")
    references = []
    for key, cap in zip(OBJECT_FIELDS, CAPS, strict=True):
        r = value[key]
        if (
            type(r) is not dict
            or set(r) != {"sha256", "byte_size"}
            or not is_digest(r["sha256"])
            or type(r["byte_size"]) is not int
            or not 1 <= r["byte_size"] <= cap
        ):
            fail("REFERENCE_INVALID")
        references.append(r)
    seen = set()
    total = 0
    for r in value["image_objects"]:
        if (
            type(r) is not dict
            or set(r) != {"asset_id", "sha256", "byte_size"}
            or not is_digest(r["asset_id"])
            or not is_digest(r["sha256"])
            or r["asset_id"] in seen
            or type(r["byte_size"]) is not int
            or not 1 <= r["byte_size"] <= 32 * 1024 * 1024
        ):
            fail("REFERENCE_INVALID")
        seen.add(r["asset_id"])
        total += r["byte_size"]
        references.append(r)
    if total > 64 * 1024 * 1024 or value["image_objects"] != sorted(
        value["image_objects"], key=lambda r: r["asset_id"]
    ):
        fail("CAPACITY_EXCEEDED")
    if len(canonical(value)) > 100000:
        fail("PACKET_INVALID")
    sizes: dict[str, int] = {}
    for r in references:
        if r["sha256"] in sizes and sizes[r["sha256"]] != r["byte_size"]:
            fail("REFERENCE_INVALID")
        sizes[r["sha256"]] = r["byte_size"]
    return sizes


def prepare(
    live,
    report,
    *,
    expected_context_digest,
    expected_findings_digest,
    expected_derivation_digest,
    expected_producer_method_digest,
    expected_method_digest,
):
    if expected_method_digest != method_digest():
        fail("METHOD_MISMATCH")
    if type(live) is not derivation.LiveDerivedContext or not is_digest(
        expected_producer_method_digest
    ):
        fail("LIVE_EVIDENCE_REQUIRED")
    context = material.verify_context(live.context, expected_context_digest)
    checked = findings.verify(report, expected_digest=expected_findings_digest)
    if checked.metadata["context_digest"] != expected_context_digest:
        fail("FINDINGS_CONTEXT_MISMATCH")
    m = deepcopy(live.metadata)
    claim_fields = FLAGS | {
        "visual_readability_verified",
        "atomic_snapshot_verified",
        "send_lease_granted",
        "version",
        "method_digest",
        "context_digest",
        "context_method_digest",
        "frozen_material_digest",
        "fresh_material_digest",
        "original_source_observation_digest",
        "fresh_material_observation",
        "runtime",
        "runtime_description_receipt",
        "documents",
        "document_manifest_links",
        "exact_frozen_context_preserved",
        "trusted_derivation_bound",
        "frozen_detail_crops_preserved",
        "fresh_native_facts_checked_after_all_render_sessions",
        "digest",
    }
    if (
        set(m) != claim_fields
        or any(
            m[k] is not True
            for k in (
                "exact_frozen_context_preserved",
                "trusted_derivation_bound",
                "frozen_detail_crops_preserved",
                "fresh_native_facts_checked_after_all_render_sessions",
            )
        )
        or m.get("context_method_digest") != material.context_method_digest()
        or not is_digest(expected_derivation_digest)
        or m.get("digest") != expected_derivation_digest
        or digest({k: v for k, v in m.items() if k != "digest"}) != expected_derivation_digest
        or m.get("version") != "fusion-exact-context-derivation/1"
        or m.get("method_digest") != expected_producer_method_digest
        or m.get("context_digest") != expected_context_digest
        or m.get("frozen_material_digest") != context.metadata["source_material_digest"]
        or m.get("original_source_observation_digest")
        != context.metadata["source_observation_digest"]
        or any(
            m.get(k) is not False
            for k in FLAGS
            | {"visual_readability_verified", "atomic_snapshot_verified", "send_lease_granted"}
        )
    ):
        fail("DERIVATION_CLAIM_INVALID")
    if type(m["documents"]) is not list or any(
        type(r) is not dict or set(r) != {"document_version_id", "manifest_digest", "receipt"}
        for r in m["documents"]
    ):
        fail("DERIVATION_CLAIM_INVALID")
    links = m.get("document_manifest_links")
    if (
        type(links) is not list
        or {r.get("document_version_id") for r in links if type(r) is dict}
        != set(context.origin.page_bundles)
        or len(links) != len(context.origin.page_bundles)
    ):
        fail("DERIVATION_CLAIM_INVALID")
    fresh_manifests = {}
    for link in links:
        doc = link["document_version_id"]
        fresh = assets.PageAssetBundle(
            deepcopy(link["fresh_manifest"]), dict(context.origin.page_bundles[doc].blobs)
        )
        rebuilt = derivation._link_assets(doc, context.origin.page_bundles[doc], fresh)
        if canonical(rebuilt) != canonical(link):
            fail("DERIVATION_CLAIM_INVALID")
        fresh_manifests[doc] = fresh.manifest
    fresh_material = deepcopy(context.metadata["material"])
    fresh_material["page_asset_manifests"] = fresh_manifests
    observation = m.get("fresh_material_observation")
    if (
        type(observation) is not dict
        or observation.get("material_digest") != digest(fresh_material)
        or m.get("fresh_material_digest") != digest(fresh_material)
        or observation.get("digest")
        != digest({k: v for k, v in observation.items() if k != "digest"})
    ):
        fail("DERIVATION_CLAIM_INVALID")
    for k in ("bid_id", "scope_id", "scope_digest"):
        if observation.get(k) != context.metadata[k]:
            fail("DERIVATION_CLAIM_INVALID")
    fresh_origin = current.CurrentMaterial(
        observation,
        fresh_material,
        context.origin.originals,
        {
            doc: assets.PageAssetBundle(
                fresh_manifests[doc], dict(context.origin.page_bundles[doc].blobs)
            )
            for doc in fresh_manifests
        },
    )
    _, checked_documents = material_derivation._checked_receipts(
        fresh_origin,
        SimpleNamespace(
            receipts=[m["runtime_description_receipt"], *[r["receipt"] for r in m["documents"]]]
        ),
        m["runtime"],
    )
    if canonical(checked_documents) != canonical(m["documents"]):
        fail("DERIVATION_CLAIM_INVALID")
    base = archive.prepare(context, expected_context_digest=expected_context_digest)
    objects = dict(base.objects)
    bodies = [
        canonical(context.metadata),
        canonical(context.origin.metadata),
        canonical(m),
        canonical(checked.metadata),
    ]
    packet = {
        "version": "package-native-material-store-packet/1",
        "store_method_digest": expected_method_digest,
        "context_digest": expected_context_digest,
        "context_method_digest": material.context_method_digest(),
        "source_observation_digest": context.metadata["source_observation_digest"],
        "derivation_observation_digest": expected_derivation_digest,
        "review_digest": checked.metadata["review_digest"],
        "findings_digest": expected_findings_digest,
        "image_objects": deepcopy(base.manifest["images"]),
    }
    for key, raw, cap in zip(OBJECT_FIELDS, bodies, CAPS, strict=True):
        if len(raw) > cap:
            fail("CAPACITY_EXCEEDED")
        checksum = sha(raw)
        objects[checksum] = raw
        packet[key] = {"sha256": checksum, "byte_size": len(raw)}
    expected = _packet(packet)
    if set(objects) != set(expected) or any(
        len(raw) != expected[key] or sha(raw) != key for key, raw in objects.items()
    ):
        fail("OBJECT_SET_INVALID")
    return PreparedEvidence(
        derivation.LiveDerivedContext(context, m),
        checked,
        expected_producer_method_digest,
        packet,
        objects,
    )


def _audit(c, write):
    read_purpose.require_read_purpose(
        c,
        read_purpose.ReadPurpose(
            groups=frozenset({WRITE_GROUP if write else READ_GROUP}),
            definer_calls=(PUT_RPC if write else READ_RPC,),
        ),
    )
    owner = c.execute(
        "SELECT c.relowner,n.nspowner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=to_regclass('technical_material_store.records')"
    ).fetchone()
    if owner is None or owner["relowner"] != owner["nspowner"]:
        fail("NATIVE_METHOD_MISMATCH")
    # Audit the shared private policy through pg_catalog, without granting this
    # purpose USAGE or EXECUTE on any other purpose's schema/entry points.
    policy_parts = issuers.SQL_FILE.read_text(encoding="utf-8").split("$scope_issuer_policy$")
    policies = c.execute(
        "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proowner,l.lanname,p.prorettype::regtype::text AS returns FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname='scope_review_issuer' AND p.proname='role_policy' AND oidvectortypes(p.proargtypes)='name, text, text[]'"
    ).fetchall()
    if len(policy_parts) != 3 or len(policies) != 1:
        fail("NATIVE_METHOD_MISMATCH")
    policy = policies[0]
    if (
        policy["prosrc"] != policy_parts[1]
        or policy["prosecdef"] is not False
        or policy["provolatile"] != "s"
        or policy["lanname"] != "plpgsql"
        or policy["returns"] != "boolean"
        or policy["proowner"] != owner["relowner"]
        or policy["proconfig"] != ["search_path=pg_catalog, scope_review_issuer, design, pg_temp"]
    ):
        fail("NATIVE_METHOD_MISMATCH")
    text = SQL_FILE.read_text(encoding="utf-8")
    for rpc, tag, returns in (
        (PUT_RPC, "material_store_put", "jsonb"),
        (READ_RPC, "material_store_read", "record"),
    ):
        pieces = text.split("$" + tag + "$")
        row = c.execute(
            "SELECT p.prosrc,p.prosecdef,p.provolatile,p.proconfig,p.proowner,l.lanname,p.prorettype::regtype::text AS returns,pg_has_role(session_user,p.proowner,'MEMBER') AS caller_owner FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(%s)",
            (rpc,),
        ).fetchone()
        if (
            len(pieces) != 3
            or row is None
            or row["prosrc"] != pieces[1]
            or row["prosecdef"] is not True
            or row["provolatile"] != "v"
            or row["lanname"] != "plpgsql"
            or row["returns"] != returns
            or row["proowner"] != owner["relowner"]
            or row["caller_owner"]
            or row["proconfig"]
            != ["search_path=pg_catalog, technical_material_store, design, pg_temp", "TimeZone=UTC"]
        ):
            fail("NATIVE_METHOD_MISMATCH")


def _record(value):
    if type(value) is not dict or set(value) != {"document", "digest"}:
        fail("NATIVE_RESULT_INVALID")
    d = value["document"]
    if (
        type(d) is not dict
        or set(d)
        != FLAGS
        | {
            "version",
            "record_id",
            "bid_id",
            "scope_id",
            "scope_digest",
            "command_id",
            "recorded_by",
            "recorded_at",
            "packet",
            "packet_digest",
            "status",
        }
        or d["version"] != "package-native-material-store-record/1"
        or d["status"] != "private_evidence_stored"
        or any(d[k] is not False for k in FLAGS)
        or not is_digest(value["digest"])
        or digest(d) != value["digest"]
    ):
        fail("NATIVE_RESULT_INVALID")
    for k in ("record_id", "bid_id", "scope_id", "command_id"):
        _uuid(d[k])
    if (
        not is_digest(d["scope_digest"])
        or not is_digest(d["packet_digest"])
        or digest(d["packet"]) != d["packet_digest"]
        or type(d["recorded_by"]) is not str
        or not 1 <= len(d["recorded_by"]) <= 63
    ):
        fail("NATIVE_RESULT_INVALID")
    valid = False
    try:
        at = d["recorded_at"]
        valid = (
            type(at) is str
            and len(at) <= 40
            and datetime.fromisoformat(at.replace("Z", "+00:00")).tzinfo is not None
        )
    except (ValueError, TypeError):
        pass
    if not valid:
        fail("NATIVE_RESULT_INVALID")
    _packet(d["packet"])
    return NativeEvidenceRecord(deepcopy(value) | {"native_record_identity_verified": True})


def _execute(connection, query, args, *, write, expected_method_digest, validate):
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    if connection.info.transaction_status != TransactionStatus.IDLE:
        fail("IDLE_CONNECTION_REQUIRED")
    error_code = None
    try:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as c:
                c.execute(
                    "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE"
                    if write
                    else "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                c.execute("SET LOCAL statement_timeout='5s'")
                _audit(c, write)
                checked = validate(c.execute(query, args).fetchone())
                if method_digest() != method:
                    fail("METHOD_CHANGED")
    except read_purpose.ReadPurposeError as error:
        error_code = "MATERIAL_STORE_" + error.code
    except psycopg.Error as error:
        error_code = (
            error.diag.message_primary
            if error.diag.message_primary in KNOWN_ERRORS
            else "MATERIAL_STORE_NATIVE_UNAVAILABLE"
        )
    if error_code:
        raise NativeMaterialStoreError(error_code)
    return checked


def put(connection, prepared, *, command_id, expected_packet_digest, expected_method_digest):
    _uuid(command_id)
    if (
        type(prepared) is not PreparedEvidence
        or not is_digest(expected_packet_digest)
        or digest(prepared.packet) != expected_packet_digest
    ):
        fail("PREPARED_EVIDENCE_INVALID")
    p = prepared.packet
    owned = prepare(
        prepared.live,
        prepared.findings,
        expected_context_digest=p["context_digest"],
        expected_findings_digest=p["findings_digest"],
        expected_derivation_digest=p["derivation_observation_digest"],
        expected_producer_method_digest=prepared.producer_method_digest,
        expected_method_digest=expected_method_digest,
    )
    if canonical(owned.packet) != canonical(p) or owned.objects != prepared.objects:
        fail("PREPARED_EVIDENCE_INVALID")
    context = owned.live.context.metadata

    def validate(row):
        if type(row) is not dict or set(row) != {"value"}:
            fail("NATIVE_RESULT_INVALID")
        record = _record(row["value"])
        d = record.metadata["document"]
        if (
            d["command_id"] != command_id
            or d["packet"] != owned.packet
            or any(d[k] != context[k] for k in ("bid_id", "scope_id", "scope_digest"))
        ):
            fail("NATIVE_RESULT_INVALID")
        return record

    keys = sorted(owned.objects)
    return _execute(
        connection,
        "SELECT technical_material_store.put(%s,%s,%s,%s,%s,%s,%s) AS value",
        (
            context["bid_id"],
            context["scope_id"],
            context["scope_digest"],
            command_id,
            Jsonb(owned.packet),
            keys,
            [owned.objects[k] for k in keys],
        ),
        write=True,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def read(
    connection,
    *,
    bid_id,
    command_id,
    expected_packet_digest,
    expected_method_digest,
    expected_record_digest=None,
    object_digest=None,
):
    _uuid(bid_id)
    _uuid(command_id)
    if not is_digest(expected_packet_digest) or any(
        v is not None and not is_digest(v) for v in (expected_record_digest, object_digest)
    ):
        fail("DIGEST_INVALID")

    def validate(row):
        if type(row) is not dict or set(row) != {"document", "digest", "object_sha", "data"}:
            fail("NATIVE_RESULT_INVALID")
        record = _record({k: row[k] for k in ("document", "digest")})
        d = record.metadata["document"]
        if (
            d["bid_id"] != bid_id
            or d["command_id"] != command_id
            or d["packet_digest"] != expected_packet_digest
            or (
                expected_record_digest is not None
                and record.metadata["digest"] != expected_record_digest
            )
        ):
            fail("NATIVE_RESULT_INVALID")
        if object_digest is None:
            if row["object_sha"] is not None or row["data"] is not None:
                fail("NATIVE_RESULT_INVALID")
            return record
        references = _packet(d["packet"])
        raw = row["data"]
        if (
            object_digest not in references
            or row["object_sha"] != object_digest
            or type(raw) is not bytes
            or len(raw) != references[object_digest]
            or sha(raw) != object_digest
        ):
            fail("NATIVE_OBJECT_INVALID")
        return NativeEvidenceObject(record, object_digest, raw)

    return _execute(
        connection,
        "SELECT * FROM technical_material_store.read(%s,%s,%s,%s)",
        (bid_id, command_id, expected_packet_digest, object_digest),
        write=False,
        expected_method_digest=expected_method_digest,
        validate=validate,
    )


def load(
    connection,
    *,
    bid_id,
    command_id,
    expected_packet_digest,
    expected_record_digest,
    expected_method_digest,
):
    args = {
        "bid_id": bid_id,
        "command_id": command_id,
        "expected_packet_digest": expected_packet_digest,
        "expected_record_digest": expected_record_digest,
        "expected_method_digest": expected_method_digest,
    }
    record = read(connection, **args)
    packet = record.metadata["document"]["packet"]
    objects = {key: read(connection, **args, object_digest=key).data for key in _packet(packet)}
    bodies = [archive._decode(objects[packet[k]["sha256"]]) for k in OBJECT_FIELDS]
    context, observation, derived, report = bodies
    for body, key in zip(
        bodies,
        (
            "context_digest",
            "source_observation_digest",
            "derivation_observation_digest",
            "findings_digest",
        ),
        strict=True,
    ):
        if (
            body.get("digest") != packet[key]
            or digest({k: v for k, v in body.items() if k != "digest"}) != packet[key]
        ):
            fail("STORED_DOCUMENT_INVALID")
    if (
        context.get("context_method_digest") != packet["context_method_digest"]
        or context.get("source_observation_digest") != packet["source_observation_digest"]
        or any(
            context.get(k) != record.metadata["document"][k]
            for k in ("bid_id", "scope_id", "scope_digest")
        )
        or derived.get("context_digest") != packet["context_digest"]
        or report.get("context_digest") != packet["context_digest"]
        or report.get("review_digest") != packet["review_digest"]
        or archive._images(context) != packet["image_objects"]
    ):
        fail("STORED_DOCUMENT_INVALID")
    blobs = {r["asset_id"]: objects[r["sha256"]] for r in packet["image_objects"]}
    return StoredMaterialEvidence(record, context, observation, derived, report, blobs)
