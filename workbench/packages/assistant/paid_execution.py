"""Assistant project port: original native call ledger plus aggregate dispatch authority."""

import json

from psycopg.types.json import Jsonb

from packages.assistant import budget
from packages.assistant.authority import assert_source_guards
from packages.domain import model_calls, storage
from packages.domain.providers.deepseek import DeepSeekClient, ProviderError
from packages.domain.runtime import DomainError, clean, connection, fetch, sha, uid


def generate_project(row, message, lease, *, messages, schema, max_tokens):
    client = DeepSeekClient.from_env()
    purpose = "assistant" if row["kind"] == "answer" else "authoring"
    request = {
        "messages": messages,
        "json_schema": schema,
        "max_tokens": max_tokens,
        "temperature": 0,
        "thinking": "disabled",
    }
    profile = {
        "provider": "deepseek",
        "model": client.model,
        "port": "generation/1",
        "purpose": purpose,
        "formal_scoring_eligible": False,
    }
    with connection(True) as c:
        model_calls.lock_execution(c, message, lease)
        assert_source_guards(c, row["input_manifest"])
        budget.before_native_reserve(c, row, profile, max_tokens)
    call, created = model_calls.reserve(
        message,
        lease,
        logical_key="assistant.answer/1" if purpose == "assistant" else "authoring.generate/1",
        request_digest=sha(request),
        profile_digest=sha(profile),
        max_tokens=max_tokens,
    )
    if not created:
        if call["state"] == "succeeded" and call["response_ref"]:
            with connection(True) as c:
                blob = fetch(c, "SELECT * FROM blobs WHERE id=%s", (call["response_ref"],))
                budget.settle(c, row["id"])
            raw = storage.get(blob["object_key"])
            if sha(raw) != blob["digest"]:
                raise DomainError("MODEL_RESULT_CORRUPTED", "原调用结果字节不符，未重发", 409)
            return json.loads(raw), call["id"]
        raise DomainError(
            "MODEL_CALL_REQUIRES_RECONCILIATION",
            "原调用结果或费用尚未核清，未再次发送",
            409,
            {"call_id": str(call["id"]), "new_attempt_authorized": False},
        )
    sent, result = False, None
    try:
        with connection(True) as c:
            model_calls.lock_execution(c, message, lease)
            assert_source_guards(c, row["input_manifest"])
            budget.before_send(c, row, call["id"], request, client)
        sent = True
        result = client.generate(
            messages=messages, json_schema=schema, max_tokens=max_tokens, temperature=0
        )
        with connection(True) as c:
            budget.observe_usage(c, row["id"], call["id"], result.usage, result.request_id)
        value = {
            "content": result.content,
            "data": result.data,
            "usage": result.usage,
            "request_id": result.request_id,
            "response_id": result.response_id,
            "model": result.model,
        }
        raw = json.dumps(
            clean(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        key = "model-results/" + str(call["id"]) + ".json"
        storage.put(key, raw, "application/json")
        with connection(True) as c:
            c.execute(
                "INSERT INTO blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,%s,'application/json') ON CONFLICT(digest) DO NOTHING",
                (uid(), sha(raw), key, len(raw)),
            )
            blob = fetch(c, "SELECT id FROM blobs WHERE digest=%s", (sha(raw),))
            c.execute(
                "UPDATE model_calls SET state='succeeded',provider_request_id=%s,response_ref=%s,usage=usage||%s WHERE id=%s AND state IN ('reserved','unknown')",
                (
                    result.request_id,
                    blob["id"],
                    Jsonb({"billing_state": "usage_reported", "actual": result.usage}),
                    call["id"],
                ),
            )
        # Do not wait on the budget mutex while holding a native call write lock.
        # The committed native usage remains recoverable by terminal_tick.
        with connection(True) as c:
            budget.settle(c, row["id"])
        return value, call["id"]
    except Exception as error:
        reported = (
            ProviderError(
                "MODEL_RESULT_PERSIST_FAILED",
                "模型结果尚未可靠保存",
                billing_state="usage_reported",
                request_id=result.request_id,
                usage=result.usage,
            )
            if result is not None
            else error
        )
        model_calls._record_failure(call["id"], reported, sent=sent)
        with connection(True) as c:
            budget.settle(c, row["id"])
        if isinstance(error, DomainError):
            raise DomainError(
                error.code, error.message, error.status, error.details, retryable=False
            ) from None
        raise DomainError(
            "ASSISTANT_RESULT_UNKNOWN", "结果或费用尚未可靠完成，未自动补发", 503
        ) from None
