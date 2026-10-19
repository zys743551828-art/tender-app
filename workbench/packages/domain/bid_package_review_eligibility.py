"""Read one immutable root and current exact-reference evidence in a readonly snapshot."""

from packages.domain import bid_package_review_input_repository as inputs
from packages.domain import bid_package_review_repository as selected
from packages.domain import package_review_context
from packages.domain.bid_package_review_documents import evidence_matches
from packages.domain.package_review_eligibility import assess
from packages.domain.runtime import DomainError, connection


def inspect(scope: tuple[str, str, str, str], input_id: str, frozen_digest: str):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        packet = inputs.load_input(c, scope, input_id)
        if packet.digest != frozen_digest:
            raise DomainError(
                "PACKAGE_REVIEW_FROZEN_INPUT_CHANGED",
                "冻结记录摘要与明确选择不一致，请重读原记录",
                409,
            )
        root = packet.evidence()
        observations = selected.observations(c, root["selection"])
        matches = evidence_matches(c, root["selection"])
        context = package_review_context.capture(c, root["selection"], observations)
        return assess(packet.view(), root, observations, context, evidence_matches=matches)
