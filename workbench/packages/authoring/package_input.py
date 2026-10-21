"""Save exact authoring context; no jobs, model calls, publication or draft mutation."""

from psycopg.types.json import Jsonb

from packages.authoring import package_admission as admission
from packages.authoring import package_input_repository as repository
from packages.domain.bid_package_service import lock_bid
from packages.domain.review_identity import utc
from packages.domain.runtime import Command, DomainError, audit, connection, fetch, sha, uid


def key_required(key):
    if not key or len(key) > 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供有效的操作幂等键", 428)


def _declarations(identity, observed, actor, command_id, recorded_at):
    context = observed.context()
    facts = {row["item"]["fact"]["id"]: row for row in context["facts"]["items"]}
    result = []
    for use in observed.request()["facts"]["uses"]:
        manifest = {
            "protocol": "authoring-package-fact-scope/1",
            "id": str(uid()),
            "bid_id": observed.bid_id,
            "input_id": identity,
            "fact_id": use["fact_id"],
            "purpose": "authoring",
            "revision": 1,
            "action": "bind",
            "previous_digest": None,
            "actor_id": str(actor),
            "command_id": str(command_id),
            "recorded_at": recorded_at,
            "basis_digest": observed.digest,
            "fact_item_digest": use["fact_item_digest"],
            "proof_digest": facts[use["fact_id"]]["proof_digest"],
            "subject": use["subject"],
            "reason": use["reason"].strip(),
        }
        result.append({"manifest": manifest, "digest": sha(manifest)})
    return result


def _insert_declaration(c, value):
    m = value["manifest"]
    c.execute(
        """INSERT INTO design.authoring_package_fact_scopes
        (id,bid_id,input_id,fact_id,revision,actor_id,command_id,manifest,digest)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            m["id"],
            m["bid_id"],
            m["input_id"],
            m["fact_id"],
            m["revision"],
            m["actor_id"],
            m["command_id"],
            Jsonb(m),
            value["digest"],
        ),
    )


def save(actor, bid, key, body, *, final_auth):
    key_required(key)
    bid, actor = str(bid), str(actor)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        repository.require_schema(c)
        old = repository.replay(c, actor, bid, key, body)
    if old:
        return old, True
    verified = admission.verify(admission.observe(bid, body))
    with connection() as c:
        lock_bid(c, bid)
        cmd = Command(c, actor, repository.KIND, bid, key, body)
        if cmd.replay:
            return cmd.replay, True
        observed = admission.recheck(c, verified)
        final_auth()
        identity = str(uid())
        recorded_at = utc(fetch(c, "SELECT clock_timestamp() AS at")["at"].isoformat())
        context = observed.context()
        declarations = _declarations(identity, observed, actor, cmd.id, recorded_at)
        counts = {
            "logical_members": len(context["documents"]),
            "physical_pages": sum(d["page_count"] for d in context["documents"]),
            "evidence_blocks": sum(len(d["blocks"]) for d in context["documents"]),
            "facts": len(context["facts"]["items"]),
            "requirements": len(context["inventory"]["record"]["manifest"]["requirements"]),
            "context_bytes": len(observed._context_text.encode()),
        }
        manifest = {
            "protocol": "package-authoring-input/1",
            "id": identity,
            "bid_id": bid,
            "actor_id": actor,
            "command_id": str(cmd.id),
            "saved_at": recorded_at,
            "originals_verified_at": observed.checked_at,
            "selection": observed.request(),
            "scope": context["packages"]["target"]["manifest"]["scope"],
            "identity_digest": context["identity"]["digest"],
            "context_digest": observed.digest,
            "method_digest": context["method_digest"],
            "counts": counts,
            "fact_declarations": declarations,
            "generation_available": False,
            "publication_authorized": False,
            "apply_available": False,
            "build_available": False,
            "formal_decisions_allowed": False,
        }
        value = {"manifest": manifest, "digest": sha(manifest)}
        c.execute(
            """INSERT INTO design.authoring_package_inputs
            (id,bid_id,actor_id,command_id,manifest,digest,context_text,context_digest)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                identity,
                bid,
                actor,
                cmd.id,
                Jsonb(manifest),
                value["digest"],
                observed._context_text,
                observed.digest,
            ),
        )
        for declaration in declarations:
            _insert_declaration(c, declaration)
        audit(
            c,
            actor,
            bid,
            "authoring.package_input_saved",
            {
                "input_id": identity,
                "input_digest": value["digest"],
                "context_digest": observed.digest,
            },
            cmd.id,
        )
        stored = cmd.finish(value, 201)
    return stored, False


def status(bid, identity, digest):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        row = repository.load(c, bid, identity)
        if row["digest"] != digest:
            raise DomainError("AUTHORING_PACKAGE_INPUT_DIGEST_MISMATCH", "所选输入摘要不符", 409)
        reasons = []
        try:
            repository.declarations_match(c, row)
            current = admission.capture(c, str(bid), row["manifest"]["selection"])
            if current._context_text != row["context_text"]:
                reasons.append("AUTHORING_PACKAGE_INPUT_CHANGED")
        except DomainError as error:
            reasons.append(error.code)
        checked = utc(fetch(c, "SELECT clock_timestamp() AS at")["at"].isoformat())
        return {
            "protocol": "package-authoring-input-status/1",
            "input_id": str(identity),
            "input_digest": digest,
            "current_input_matches": not reasons,
            "original_bytes_reverified": False,
            "checked_at": checked,
            "generation_available": False,
            "publication_available": False,
            "apply_available": False,
            "build_available": False,
            "blocking_reasons": [*reasons, "AUTHORING_PACKAGE_EXECUTOR_NOT_READY"],
        }


def withdraw(actor, bid, identity, key, body):
    key_required(key)
    bid, actor, identity = str(bid), str(actor), str(identity)
    with connection() as c:
        lock_bid(c, bid)
        cmd = Command(c, actor, repository.WITHDRAW, identity, key, body)
        if cmd.replay:
            return cmd.replay, True
        row = repository.load(c, bid, identity)
        if row["digest"] != body["input_digest"]:
            raise DomainError("AUTHORING_PACKAGE_INPUT_DIGEST_MISMATCH", "所选输入摘要不符", 409)
        previous = fetch(
            c,
            "SELECT manifest,digest FROM design.authoring_package_fact_scopes WHERE bid_id=%s AND input_id=%s AND fact_id=%s ORDER BY revision DESC LIMIT 1",
            (bid, identity, body["fact_id"]),
        )
        if (
            previous["digest"] != body["declaration_digest"]
            or previous["manifest"]["action"] != "bind"
        ):
            raise DomainError(
                "AUTHORING_PACKAGE_FACT_DECLARATION_CHANGED", "所选事实声明已改变", 409
            )
        m = previous["manifest"] | {
            "id": str(uid()),
            "revision": previous["manifest"]["revision"] + 1,
            "action": "withdraw",
            "previous_digest": previous["digest"],
            "actor_id": actor,
            "command_id": str(cmd.id),
            "recorded_at": utc(fetch(c, "SELECT clock_timestamp() AS at")["at"].isoformat()),
            "reason": body["reason"],
        }
        value = {"manifest": m, "digest": sha(m)}
        _insert_declaration(c, value)
        audit(
            c,
            actor,
            bid,
            "authoring.package_fact_withdrawn",
            {
                "input_id": identity,
                "fact_id": body["fact_id"],
                "declaration_digest": value["digest"],
            },
            cmd.id,
        )
        return cmd.finish(value, 201), False
