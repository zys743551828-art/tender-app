"""CPU-only Worker adapter; private input/output references, existing lease fencing."""

from pathlib import Path

from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, connection
from packages.package_model_certification.policy import method_digest as cm
from packages.package_model_live.producer import Executor
from packages.package_prediction.application import method_digest
from packages.package_prediction_tasks.application import HANDLER, STEP, task_method
from packages.package_prediction_tasks.native import EVENT
from packages.package_prediction_tasks.storage import Objects

_executor = None
_store = None


def configure(executor, store=None):
    global _executor, _store
    if (
        type(executor) is not Executor
        or not isinstance(executor.index, (str, Path))
        or not isinstance(executor.store, (str, Path))
    ):
        raise ValueError("fixed native material executor required")
    _executor, _store = executor, store or Objects()


def record(c, message):
    if message["handler_version"] != HANDLER or message["step_key"] != STEP:
        raise DomainError("PREDICTION_TASK_STAGE_INVALID", "预测任务阶段不符", 409)
    rows = c.execute(
        "SELECT payload FROM design.audit_entries WHERE event_type=%s AND payload->>'request_id'=%s",
        (EVENT, message["payload_ref"]),
    ).fetchall()
    if len(rows) != 1:
        raise DomainError("PREDICTION_TASK_INVALID", "预测任务身份不符", 409)
    job = rows[0]["payload"]
    if (
        job["operation_id"] != str(message["operation_id"])
        or job["body"]["bid"] != str(message["bid_id"])
        or job["input_ref"] != message["input_digest"]
    ):
        raise DomainError("PREDICTION_TASK_INVALID", "预测任务身份不符", 409)
    return job


def calculate(job, executor, store):
    frozen = store.get(job["input_ref"])
    if (
        frozen["schema"] != HANDLER
        or frozen["task_method"] != task_method()
        or frozen["body"] != job["body"]
        or digest(frozen["packet"]) != job["authority_digest"]
        or frozen["prediction_method"] != method_digest()
        or frozen["certificate_method"] != cm()
    ):
        raise DomainError("PREDICTION_TASK_CHANGED", "固定预测方法或输入已变化", 409)
    authority = frozen["packet"]["authority"]["source"]
    packet = {
        "source": authority["current_source"],
        "artifact": authority["model"],
        "reference": frozen["packet"]["reference"],
    }
    pinned = digest(packet)
    result = executor(packet)
    if digest(packet) != pinned or result["packet_digest"] != pinned:
        raise DomainError("PREDICTION_TASK_CHANGED", "固定预测输入在计算中变化", 409)
    return {"input_ref": job["input_ref"], "result_ref": store.put(result)}


def compute(message, lease=None):
    if _executor is None or _store is None:
        raise DomainError("PREDICTION_WORKER_DISABLED", "预测Worker未配置", 503)
    with connection(True) as c:
        job = record(c, message)
    return calculate(job, _executor, _store)


def publish(c, message, outcome):
    job = record(c, message)
    if (
        set(outcome) != {"input_ref", "result_ref"}
        or outcome["input_ref"] != job["input_ref"]
        or not isinstance(outcome["result_ref"], str)
        or len(outcome["result_ref"]) != 64
        or any(x not in "0123456789abcdef" for x in outcome["result_ref"])
    ):
        raise DomainError("PREDICTION_TASK_RESULT_INVALID", "预测计算回执不符", 409)
    # engine.finish owns the actual fence/generation/lease/terminal-state checks.
    # No authority access, database score writes or object I/O inside this transaction.
    return outcome
