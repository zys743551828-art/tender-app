"""Advisory packet integrity for exact generated-file adoption."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from apps.api.export_openapi import implemented_openapi
from apps.api.main import app
from packages.authoring import technical_handoff as handoff
from packages.domain.bid_packages import PackageKind
from packages.domain.runtime import DomainError, sha

BID, PACKAGE, REVISION, DOC, BUILD, SNAPSHOT, ACTOR, CMD = (str(UUID(int=i)) for i in range(1, 9))


@pytest.fixture
def frozen():
    member = SimpleNamespace(
        member_id="synthetic-word",
        document_version_id=DOC,
        file_digest="a" * 64,
        purposes=["技术"],
        parts=[],
        parse=SimpleNamespace(parse_run_id=None),
    )
    package = SimpleNamespace(
        package_id=PACKAGE,
        revision_id=REVISION,
        scope=SimpleNamespace(bid_id=BID),
        kind=PackageKind.BID,
        manifest_digest="b" * 64,
        members=[member],
    )
    proof = {
        "protocol": handoff.PROTOCOL,
        "bid_id": BID,
        "build_id": BUILD,
        "document_version_id": DOC,
        "sha256": member.file_digest,
        "format": "docx",
        "build_identity": {"snapshot_id": SNAPSHOT, "snapshot_digest": "c" * 64},
    }
    row = {
        "adoption": {
            "document_version_id": DOC,
            "package_id": PACKAGE,
            "package_revision_id": REVISION,
            "package_digest": package.manifest_digest,
            "build_id": BUILD,
            "reason": "Private synthetic note must not be returned",
        },
        "qualification": {"proof": deepcopy(proof), "proof_digest": sha(proof)},
        "command_kind": handoff.KIND,
        "command_status": 201,
        "command_actor": ACTOR,
        "receipt_actor": ACTOR,
        "command_id": CMD,
        "receipt_command": CMD,
        "receipt_bid": BID,
        "command_target": BUILD,
        "command_request_digest": "d" * 64,
        "receipt_request_digest": "d" * 64,
        "command_protocol": "authoring-output-adoption/1",
        "command_output": proof,
        "command_revision": REVISION,
        "command_package_digest": package.manifest_digest,
    }
    return package, row, member


def test_registered_session_read_route_refuses_anonymous():
    template = (
        "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}"
        "/technical-authoring-handoff"
    )
    assert set(implemented_openapi(app)["paths"][template]) == {"get"}
    assert implemented_openapi(app)["paths"][template]["get"]["security"] == [{"SessionCookie": []}]
    path = template.format(bid_id=BID, package_id=PACKAGE, revision_id=REVISION)
    assert TestClient(app).get(path).status_code == 401


def test_safe_adoption_projection_does_not_reveal_private_proof(frozen):
    package, row, member = frozen
    assert handoff._receipt(package, row) == {
        "member_id": member.member_id,
        "document_version_id": DOC,
        "artifact_sha256": member.file_digest,
        "format": "docx",
        "build_id": UUID(BUILD),
        "snapshot_id": UUID(SNAPSHOT),
        "snapshot_digest": "c" * 64,
        "parse_run_id": None,
    }
    member.purposes = ["商务"]
    assert handoff._receipt(package, row) is None


@pytest.mark.parametrize(
    ("key", "change"),
    (
        ("qualification", None),
        ("command_status", 200),
        ("command_kind", "other"),
        ("receipt_actor", UUID(int=90)),
        ("receipt_request_digest", "e" * 64),
        ("command_revision", UUID(int=90)),
        ("command_output", None),
    ),
)
def test_missing_or_foreign_command_cannot_qualify_same_file(frozen, key, change):
    package, row, member = frozen
    row[key] = change
    with pytest.raises(DomainError, match="采用记录"):
        handoff._receipt(package, row)


def test_identical_member_label_and_hash_are_not_enough_when_document_version_differs(frozen):
    package, row, member = frozen
    member.document_version_id = str(UUID(int=99))
    with pytest.raises(DomainError, match="采用记录"):
        handoff._receipt(package, row)
