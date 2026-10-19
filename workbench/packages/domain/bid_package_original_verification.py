"""Snapshot / external IO / revalidation orchestration; never freezes or launches."""

from dataclasses import dataclass
from typing import Any

from packages.domain import bid_package_review_repository as repository
from packages.domain import original_verification
from packages.domain.bid_package_review_documents import read_member
from packages.domain.bid_package_review_policy import evaluate
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, connection


@dataclass
class VerificationInput:
    manifest: dict[str, Any]
    observations: dict[str, Any]
    documents: list[dict[str, Any]]
    blockers: list[str]

    @property
    def digest(self) -> str:
        return digest(self.manifest)

    def stable_observations(self) -> dict[str, Any]:
        # Time itself advances; effectivity at the new time is compared through blockers.
        return {key: value for key, value in self.observations.items() if key != "at"}


def read_input(bid: str, package: str, revision: str, inventory: str, body: dict[str, Any]):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        manifest = repository.selected(c, bid, package, revision, inventory, body)
        if digest(manifest) != body["input_digest"]:
            raise DomainError("PACKAGE_REVIEW_INPUT_DIGEST_MISMATCH", "所选预检输入摘要不一致", 422)
        observations = repository.observations(c, manifest)
        documents = [
            read_member(c, bid, member) | {"package_role": role}
            for role in ("target", "authority")
            for member in manifest[role]["manifest"]["members"]
        ]
        result = evaluate(manifest, observations, evidence_matches=True)
    return VerificationInput(manifest, observations, documents, result["blockers"])


def verify(bid: str, package: str, revision: str, inventory: str, body: dict[str, Any]):
    before = read_input(bid, package, revision, inventory, body)
    # No connection or business lock remains open across provider IO.
    for document in before.documents:
        original_verification.verify(document)
    after = read_input(bid, package, revision, inventory, body)
    if (
        before.manifest != after.manifest
        or before.documents != after.documents
        or before.stable_observations() != after.stable_observations()
        or before.blockers != after.blockers
    ):
        raise DomainError(
            "PACKAGE_REVIEW_INPUT_CHANGED", "核验期间输入或来源状态已变化，请重新检查", 409
        )
    return {
        "kind": "observation",
        "input_digest": after.digest,
        "checked_at": after.observations["at"].isoformat(),
        "originals_verified": True,
        "review_ready": False,
        "launch_available": False,
        "blockers": after.blockers,
        "originals": [
            {
                "role": doc["package_role"],
                "member_id": doc["member_id"],
                "document_version_id": str(doc["document_version_id"]),
                "parse_run_id": str(doc["parse_id"]),
                "file_digest": doc["digest"],
                "byte_size": doc["byte_size"],
            }
            for doc in after.documents
        ],
    }
