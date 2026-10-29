"""Short authority transactions around CPU work; no ambient DB or framework."""

from typing import Protocol

from packages.domain.review_identity import digest
from packages.model_governance import package_complete_calibration as shape
from packages.model_governance import package_feature_handoff as files
from packages.package_model_registry import artifact

VERSION = "package-internal-observation-request/1"


class Transaction(Protocol):
    def replay(self, actor, request): ...
    def source(self, actor, request): ...
    def record(self, actor, request, source_digest, result): ...


class Executor(Protocol):
    def __call__(self, source, request): ...


def validate_request(request):
    shape.exact(
        request,
        {
            "version",
            "command_id",
            "model_id",
            "admission_id",
            "artifact_digest",
            "method_digest",
            "reference",
        },
    )
    if request["version"] != VERSION:
        artifact.fail()
    for key in ("command_id", "model_id", "admission_id"):
        files.command(request[key])
    for key in ("artifact_digest", "method_digest"):
        files.checksum(request[key])
    shape.exact(request["reference"], shape.REFERENCE)


class Observations:
    def __init__(self, transactions, executor: Executor):
        self.transactions = transactions
        self.executor = executor

    def execute(self, actor, request):
        validate_request(request)
        request_digest = digest(request)
        with self.transactions() as tx:
            previous = tx.replay(actor, request)
            if previous is not None:
                # An immutable historical receipt is not a current qualification.
                return previous
            source = tx.source(actor, request)
        pinned = digest(source)
        result = self.executor(source, request)
        if digest(source) != pinned or digest(request) != request_digest:
            artifact.fail()
        with self.transactions() as tx:
            # record rechecks source under native locks, including concurrent revoke.
            return tx.record(actor, request, pinned, result)
