"""Explicit additive package adoption, with exact replay before current-use gates."""

from packages.authoring import package_outputs
from packages.authoring.package_adoption_contracts import validate
from packages.domain import bid_package_service as packages
from packages.domain.bid_packages import PackageKind
from packages.domain.runtime import DomainError, audit, connection, sha
from packages.domain.work_access import begin

KIND = "adopt-authoring-output"


def _selected_package(c, bid, body, condition):
    if body["package_id"] is None:
        if condition is not None:
            raise DomainError("INVALID_PRECONDITION", "创建新投标包不能携带旧包版本条件", 422)
        return None
    if not condition:
        raise DomainError("PRECONDITION_REQUIRED", "请先读取所选投标包当前修订", 428)
    previous = packages.head(c, bid, body["package_id"])
    if previous.kind != PackageKind.BID:
        raise DomainError("AUTHORING_ADOPTION_PACKAGE_KIND", "生成投标正文只能采用到投标包", 422)
    if condition != packages.head_tag(previous):
        raise DomainError("REVISION_CONFLICT", "投标包已有新修订，请保留选择并核对当前包", 412)
    return previous


def _snapshot(packet, body):
    identity = packet["proof"]["build_identity"]
    if (
        identity["snapshot_id"] != body["snapshot_id"]
        or identity["snapshot_digest"] != body["snapshot_digest"]
    ):
        raise DomainError(
            "AUTHORING_ADOPTION_SNAPSHOT_MISMATCH", "所选文件不属于确认的草稿快照", 409
        )


def adopt(bid, build_id, actor, key, body, condition, *, final_auth):
    validate("AdoptAuthoringOutput", body)
    request = {"bid_id": str(bid), **body}
    with connection() as c:
        command = begin(c, actor, KIND, build_id, key, request, condition, bid=bid)
        if command.replay:
            return command.replay, True
        _selected_package(c, bid, body, condition)
        package_outputs.sources.lock_graph(c)
        packet = package_outputs.capture(c, bid, build_id, body["member"]["document_version_id"])
        _snapshot(packet, body)
        package_outputs.assert_current(c, packet)
        # Discard a new provisional command; no incomplete ACK is committed over I/O.
        c.rollback()
    package_outputs.verify_bytes(packet)
    if final_auth() != actor:
        raise DomainError("AUTHORING_ADOPTION_ACTOR_CHANGED", "采用发起身份已变化", 403)
    with connection() as c:
        command = begin(c, actor, KIND, build_id, key, request, condition, bid=bid)
        if command.replay:
            return command.replay, True
        previous = _selected_package(c, bid, body, condition)
        package_outputs.qualify(c, packet, actor, command.id)
        members = []
        for item in previous.manifest()["members"] if previous else []:
            member = {
                name: item[name]
                for name in ("member_id", "document_version_id", "purposes", "parts")
            }
            if item["parse"]["status"] == "frozen":
                member["parse_run_id"] = item["parse"]["parse_run_id"]
            members.append(member)
        members.append(body["member"])
        if len(members) > 500:
            raise DomainError(
                "AUTHORING_ADOPTION_PACKAGE_FULL", "投标包已达到500个文件，未隐式删除原成员", 422
            )
        package = packages.create_revision(c, bid, {"kind": "bid", "members": members}, previous)
        value = {
            "protocol": "authoring-output-adoption/1",
            "bid_id": str(bid),
            "build_id": str(build_id),
            "actor_id": str(actor),
            "command_id": str(command.id),
            "request_digest": sha({"body": request, "if_match": condition}),
            "output": packet["proof"],
            "package": packages.view(c, package),
            "package_etag": packages.head_tag(package),
            "automatically_started_review": False,
            "current_body_changed": False,
        }
        validate("AuthoringOutputAdopted", value)
        audit(
            c,
            actor,
            bid,
            "authoring.output_adopted",
            {
                "build_id": str(build_id),
                "document_version_id": body["member"]["document_version_id"],
                "package_id": package.package_id,
                "package_revision_id": package.revision_id,
                "package_digest": package.manifest_digest,
                "reason": body["reason"],
            },
            command.id,
        )
        return command.finish(value, 201, {"ETag": value["package_etag"]}), False
