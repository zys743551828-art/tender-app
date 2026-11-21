"""Historical exact-candidate citations, never a current authority or coverage check."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from packages.assistant.generation import nodes
from packages.authoring import exact_sources, package_generation, package_publication
from packages.domain.runtime import DomainError, clean, fetch, sha
from packages.rag.indexing import parse_source_id

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HistoricalCandidateMembership(StrictModel):
    role: Literal["authority", "target"]
    package_id: UUID
    revision_id: UUID
    manifest_digest: Digest


class HistoricalCandidateCitation(StrictModel):
    evidence_id: UUID
    document_version_id: UUID
    parse_run_id: UUID
    physical_page: int = Field(ge=1)
    evidence_digest: Digest
    source_id: UUID
    source_revision: int = Field(ge=1)
    memberships: tuple[HistoricalCandidateMembership, ...] = Field(min_length=1, max_length=2)


class HistoricalCandidateNode(StrictModel):
    node_id: str = Field(min_length=1, max_length=128)
    node_type: Literal["heading", "paragraph"]
    before_digest: Digest
    after_digest: Digest


class HistoricalCandidateTrace(StrictModel):
    protocol: Literal["authoring-historical-candidate-trace/1"]
    bid_id: UUID
    action_id: UUID
    action_digest: Digest
    candidate_digest: Digest
    snapshot_id: UUID
    snapshot_digest: Digest
    section_revision_id: UUID
    qualification_digest: Digest
    node: HistoricalCandidateNode
    citations: tuple[HistoricalCandidateCitation, ...] = Field(max_length=500)
    historic_only: Literal[True]
    original_bytes_reverified: Literal[False]
    current_effectivity_verified: Literal[False]
    content_correctness_certified: Literal[False]
    publication_authorized: Literal[False]
    trace_digest: Digest


def invalid():
    return DomainError(
        "AUTHORING_HISTORICAL_CANDIDATE_TRACE_UNVERIFIED",
        "无法核对原候选、采纳修订或固定原页身份；没有用当前稿或当前解析替代。",
        409,
    )


def _one_node(content, stable_id):
    selected = [entry for entry in nodes(content) if entry["node_id"] == stable_id]
    if len(selected) != 1:
        raise invalid()
    return selected[0]


def _citations(plan, candidate, after):
    wanted = candidate["evidence_ids"]
    if len(wanted) != len(set(wanted)) or len(wanted) > 500:
        raise invalid()
    context = plan["context"]
    choices = context["request"]["package_context"]
    selected = set(wanted)
    refs = package_generation.source_refs(plan)
    after_refs = {sha(entry) for entry in after["attrs"]["source_refs"]}
    found: dict[str, dict] = {}
    for document in context["documents"]:
        role = document["package_role"]
        if role not in {"authority", "target"}:
            raise invalid()
        parse = document["parse_id"]
        source = str(parse_source_id(UUID(parse)))
        package = choices[role]
        membership = {"role": role, **package}
        for block in document["blocks"]:
            evidence = block["id"]
            if evidence not in selected:
                continue
            expected = refs.get(evidence)
            if (
                expected is None
                or expected["source_id"] != source
                or expected["document_version_id"] != document["document_version_id"]
                or sha(expected) not in after_refs
                or not 0 < block["physical_page"] <= document["page_count"]
            ):
                raise invalid()
            entry = expected | {
                "parse_run_id": parse,
                "physical_page": block["physical_page"],
                "evidence_digest": block["digest"],
            }
            known = found.get(evidence)
            if known is None:
                found[evidence] = {"entry": entry, "memberships": {role: membership}}
            elif known["entry"] != entry:
                raise invalid()
            else:
                known["memberships"][role] = membership
    if set(found) != selected:
        raise invalid()
    return [
        found[item]["entry"]
        | {"memberships": list(value for _, value in sorted(found[item]["memberships"].items()))}
        for item in wanted
    ]


def read(c, bid, revision, snapshot_id, snapshot_digest, qualification_digest, action_id):
    # This call proves the original B3 adoption, not live source availability.
    qualified = exact_sources.load(c, bid, revision)
    manifest = qualified["manifest"]
    if (
        qualified["digest"] != qualification_digest
        or manifest["protocol"] != "authoring-exact-revision/1"
        or manifest["origin"]["action_id"] != str(action_id)
    ):
        raise invalid()
    stored = fetch(
        c,
        """SELECT manifest,digest FROM design.draft_snapshots
           WHERE bid_id=%s AND draft_id=%s AND id=%s AND revision=%s""",
        (bid, manifest["draft_id"], snapshot_id, manifest["draft_revision"]),
    )
    if stored["digest"] != snapshot_digest or sha(stored["manifest"]) != snapshot_digest:
        raise invalid()
    bindings = stored["manifest"].get("authoring_exact_sections")
    if (
        not bindings
        or exact_sources.section_binding({"manifest": manifest, "digest": qualification_digest})
        not in bindings["sections"]
    ):
        raise invalid()

    action, job = package_publication.inspect(c, action_id)
    origin = manifest["origin"]
    if (
        str(action["bid_id"]) != str(bid)
        or str(job["id"]) != origin["job_id"]
        or action["request_digest"] != origin["action_digest"]
        or action["candidate_digest"] != origin["candidate_digest"]
        or job["input_digest"] != origin["job_input_digest"]
    ):
        raise invalid()
    plan = job["input_manifest"]["plan"]
    candidate = action["payload"]["candidate"]
    node_id = candidate["node_id"]
    change = package_generation.materialize(plan, candidate)
    before, after = _one_node(change["before"], node_id), _one_node(change["after"], node_id)
    if (
        sha(change["after"]) != manifest["section_digest"]
        or before["before_digest"] != candidate["before_digest"]
        or before["node"]["type"] != after["node"]["type"]
    ):
        raise invalid()
    trace = clean(
        {
            "protocol": "authoring-historical-candidate-trace/1",
            "bid_id": bid,
            "action_id": action_id,
            "action_digest": origin["action_digest"],
            "candidate_digest": origin["candidate_digest"],
            "snapshot_id": snapshot_id,
            "snapshot_digest": snapshot_digest,
            "section_revision_id": revision,
            "qualification_digest": qualification_digest,
            "node": {
                "node_id": node_id,
                "node_type": before["node"]["type"],
                "before_digest": before["before_digest"],
                "after_digest": after["before_digest"],
            },
            "citations": _citations(plan, candidate, change["after"]),
            "historic_only": True,
            "original_bytes_reverified": False,
            "current_effectivity_verified": False,
            "content_correctness_certified": False,
            "publication_authorized": False,
        }
    )
    return HistoricalCandidateTrace.model_validate(trace | {"trace_digest": sha(trace)})
