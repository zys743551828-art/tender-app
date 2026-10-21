"""Build and output authority for real, immutable B3 revision qualifications.

Only the protected snapshot RPC can supply this packet. Its public proof contains
identities and digests; original object descriptors remain private and are read
outside transactions. Legacy source selection never replaces a frozen parse.
"""

from copy import deepcopy

from packages.authoring import exact_sources
from packages.domain import original_verification
from packages.domain.runtime import DomainError, sha


def available(c):
    functions = (
        "design.authoring_exact_snapshot_proof(uuid)",
        "design.authoring_exact_build_packet(uuid)",
        "design.authoring_exact_assert_build(uuid)",
    )
    return all(
        c.execute(
            "SELECT to_regprocedure(%s) IS NOT NULL AND "
            "coalesce(has_function_privilege(current_user,to_regprocedure(%s),'EXECUTE'),false) AS ready",
            (name, name),
        ).fetchone()["ready"]
        for name in functions
    )


def rejected(message="固定整包修订的构建身份或当前依据发生变化，未发布或采用文件"):
    raise DomainError("AUTHORING_EXACT_BUILD_CHANGED", message, 409)


def require_available(c):
    if not available(c):
        raise DomainError(
            "AUTHORING_EXACT_BUILD_NOT_CONFIGURED",
            "固定整包修订的构建资格尚未配置，正文与已采用修订已保留",
            409,
        )


def capture(c, bid, snapshot, *, current=False):
    extension = snapshot.get("authoring_exact_sections")
    if extension is None:
        return None
    require_available(c)
    query = (
        "SELECT design.authoring_exact_assert_build(%s) AS value"
        if current
        else "SELECT design.authoring_exact_build_packet(%s) AS value"
    )
    with exact_sources.errors():
        packet = c.execute(query, (snapshot["snapshot_id"],)).fetchone()["value"]
    if not isinstance(packet, dict) or set(packet) != {"proof", "originals"}:
        rejected()
    proof = packet["proof"]
    if (
        proof.get("protocol") != "authoring-exact-build/1"
        or proof.get("bid_id") != str(bid)
        or proof.get("snapshot_id") != snapshot["snapshot_id"]
        or proof.get("snapshot_digest") != snapshot["snapshot_digest"]
        or proof.get("exact_sections_digest") != extension["digest"]
        or proof.get("section_digests") != [sha(content) for content in snapshot["sections"]]
        or proof.get("originals_digest") != sha(packet["originals"])
        or proof.get("digest") != sha({k: v for k, v in proof.items() if k != "digest"})
    ):
        rejected()
    return packet


def _immutable_proof(proof):
    """A historical proof retains its original current-use observation digest."""
    if not isinstance(proof, dict) or proof.get("digest") != sha(
        {k: v for k, v in proof.items() if k != "digest"}
    ):
        rejected()
    identities = proof.get("input_identities")
    if not isinstance(identities, list):
        rejected()
    for identity in identities:
        if (
            not isinstance(identity, dict)
            or set(identity) != {"id", "digest", "context_digest", "dependency_digest"}
            or not isinstance(identity["dependency_digest"], str)
            or len(identity["dependency_digest"]) != 64
            or set(identity["dependency_digest"]) - set("0123456789abcdef")
        ):
            rejected()
    return {
        **{k: v for k, v in proof.items() if k not in {"digest", "input_identities"}},
        "input_identities": [
            {k: v for k, v in identity.items() if k != "dependency_digest"}
            for identity in identities
        ],
    }


def checked(c, bid, snapshot, manifest, *, current=False, historical=False):
    if current and historical:
        raise ValueError("Current-use authorization cannot be a historical read")
    packet = capture(c, bid, snapshot, current=current)
    if historical and packet is not None:
        frozen = manifest.get("authoring_exact")
        if _immutable_proof(frozen) != _immutable_proof(packet["proof"]):
            rejected()
        # This is only a read projection. All new uses call checked without
        # historical=True again, under their existing final authority gates.
        return {"proof": deepcopy(frozen), "originals": packet["originals"]}
    if manifest.get("authoring_exact") != (packet["proof"] if packet else None):
        rejected()
    return packet


def ordinary_sections(snapshot, packet):
    """Only actual qualified revisions use exact authority; legacy sections stay strict."""
    if packet is None:
        return snapshot["sections"]
    selected = packet["proof"]["section_revisions"]
    if len(selected) != len(snapshot["sections"]):
        rejected()
    bound = {
        item["section_revision_id"]: item
        for item in snapshot["authoring_exact_sections"]["sections"]
    }
    ordinary, seen = [], set()
    for content, row in zip(snapshot["sections"], selected, strict=True):
        if row["digest"] != sha(content):
            rejected()
        qualification = bound.get(row["section_revision_id"])
        if qualification is None:
            ordinary.append(content)
        elif (
            qualification["section_id"] != row["section_id"]
            or qualification["section_digest"] != row["digest"]
        ):
            rejected()
        else:
            seen.add(row["section_revision_id"])
    if seen != set(bound):
        rejected()
    return ordinary


def verify_originals(packet):
    if packet is not None:
        for document in packet["originals"]:
            original_verification.verify(document)


def prepared_proof(prepared):
    packet = prepared.get("authoring_exact")
    expected = prepared["info"]["manifest"].get("authoring_exact")
    if expected != (packet["proof"] if packet else None):
        rejected()
    verify_originals(packet)
    return deepcopy(expected) if expected else None


def verified_result(result, proof):
    if proof is not None:
        result["authoring_exact_verified"] = proof["digest"]
    return result


def assert_result(computed, packet):
    if computed.get("authoring_exact_verified") != (packet["proof"]["digest"] if packet else None):
        rejected("固定整包构建尚未完成原件核验，未发布结果")
