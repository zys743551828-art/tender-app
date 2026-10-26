"""Consume fixed package predictions through existing official-label authority."""

from packages.metrics.results import timestamp
from packages.metrics.sources import outcome_reasons
from packages.package_model_certification.policy import method_digest as certificate_method
from packages.package_prediction.application import method_digest
from packages.research.identities import submission_identity
from packages.research.outcomes import outcome_view


def eligible_pair(c, submission, as_of):
    if not c.execute(
        "SELECT to_regprocedure('package_prediction.submission_pair(uuid,timestamptz,text,text)') IS NOT NULL AS ready"
    ).fetchone()["ready"]:
        return None, "package_prediction_producer_unavailable"
    prediction = c.execute(
        "SELECT package_prediction.submission_pair(%s,%s,%s,%s) AS value",
        (submission["id"], as_of, method_digest(), certificate_method()),
    ).fetchone()["value"]
    if not prediction:
        return None, "no_server_fixed_pre_submission_pair"
    outcome = c.execute(
        "SELECT o.* FROM outcome_heads h JOIN outcomes o ON o.id=h.outcome_id WHERE h.submission_id=%s",
        (submission["id"],),
    ).fetchone()
    if not outcome:
        return None, "official_outcome_missing"
    if outcome["known_at"] > as_of:
        return None, "official_label_after_as_of"
    if outcome["known_at"] <= timestamp(prediction["created_at"]):
        return None, "label_known_before_prediction_freeze"
    verification = c.execute(
        "SELECT d.created_at FROM decision_heads h JOIN decisions d ON d.id=h.decision_id WHERE h.object_kind='outcome' AND h.object_id=%s",
        (outcome["id"],),
    ).fetchone()
    if not verification or verification["created_at"] > as_of:
        return None, "official_verification_not_observed_at_as_of"
    if outcome_view(c, outcome)["verification"] != "verified":
        return None, "official_outcome_unverified"
    if (
        outcome["score_kind"] != "technical_total"
        or outcome["value"] is None
        or outcome["maximum"] is None
    ):
        return None, "not_official_technical_total"
    if outcome_reasons(c, outcome, as_of):
        return None, "official_outcome_source_unusable"
    if submission_identity(c, submission)["status"] != "confirmed":
        return None, "submission_identity_unavailable"
    return {
        "predicted": prediction["value"],
        "prediction_maximum": prediction["maximum"],
        "official": outcome["value"],
        "official_maximum": outcome["maximum"],
    }, None
