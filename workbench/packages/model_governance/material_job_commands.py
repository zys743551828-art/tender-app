"""Bounded operator commands for existing native jobs; never a live send grant."""

from packages.model_governance import material_judgment_jobs as jobs
from packages.model_governance import package_feature_handoff as files
from packages.storage.private_cas import is_digest, sha

VERSION = "material-job-command/1"
FIELDS = {
    "start": {
        "renewal_id",
        "expected_renewal_digest",
        "profile_id",
        "expected_profile_digest",
        "command_id",
    },
    "read": {"job_id", "expected_job_digest"},
    "refresh": {
        "job_id",
        "expected_job_digest",
        "renewal_id",
        "expected_renewal_digest",
        "expected_revision",
        "command_id",
    },
}


def load(path, expected_digest):
    raw = files.private_read(path, maximum=16384)
    if not is_digest(expected_digest) or sha(raw) != expected_digest:
        jobs.fail("COMMAND_FILE_CHANGED")
    return validate(files.decode(raw))


def validate(value):
    if (
        type(value) is not dict
        or set(value) != {"version", "operation", "arguments"}
        or value["version"] != VERSION
        or type(value["operation"]) is not str
        or value["operation"] not in FIELDS
        or type(value["arguments"]) is not dict
        or set(value["arguments"]) != FIELDS[value["operation"]] | {"expected_method_digest"}
    ):
        jobs.fail("COMMAND_INVALID")
    args = value["arguments"]
    for key, item in args.items():
        if key.endswith("_id"):
            jobs._uuid(item)
        elif key.endswith("_digest"):
            if not is_digest(item):
                jobs.fail("DIGEST_INVALID")
        elif type(item) is not int or not 1 <= item <= 2**63 - 1:
            jobs.fail("REVISION_INVALID")
    if args["expected_method_digest"] != jobs.method_digest():
        jobs.fail("METHOD_MISMATCH")
    return value


def execute(connection, command):
    """Native wrappers own transactions, permission audits and idempotent receipts.

    Start is one existing transaction creating the job, all slots and outbox.
    Read is separate: a failed read cannot obscure a committed start. Repeat the
    identical original start command after lost ACK; never invent a new key.
    """
    validate(command)
    operation = command["operation"]
    if operation == "start":
        result = jobs.start(connection, **command["arguments"])
    elif operation == "read":
        result = jobs.read(connection, **command["arguments"])
    else:
        result = jobs.refresh(connection, **command["arguments"])
    record = result.record if operation == "read" else result
    document = record.metadata["document"]
    receipt = {
        "version": "material-job-command-receipt/1",
        "operation": operation,
        "job_id": document["job_id"],
        "job_digest": document["job_digest"]
        if operation == "refresh"
        else record.metadata["digest"],
        "method_digest": command["arguments"]["expected_method_digest"],
        "execution_authorized": False,
        "formal_prediction_eligible": False,
        "model_requests": 0,
    }
    if operation == "read":
        receipt["current"] = result.metadata["current"]
    elif operation == "start":
        receipt.update(
            bid_id=document["bid_id"],
            scope_id=document["scope_id"],
            generation=document["generation"],
        )
    else:
        receipt.update(
            evidence_id=document["event_id"],
            evidence_digest=record.metadata["digest"],
            evidence_revision=document["revision"],
        )
    return receipt
