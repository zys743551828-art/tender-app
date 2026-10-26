"""Purpose-separated package history processes; no application configuration loader."""

import os
import threading
from contextlib import contextmanager
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.model_governance.common import GovernanceError, digest

ROLES = {
    "verify": ("PACKAGE_HISTORY_VERIFY_DSN", "tender_package_history_verify"),
    "train": ("PACKAGE_HISTORY_TRAIN_DSN", "tender_package_history_train"),
    "evaluate": ("PACKAGE_HISTORY_EVALUATE_DSN", "tender_package_history_evaluate"),
}


@contextmanager
def connection(purpose):
    if purpose not in ROLES:
        raise GovernanceError(
            "PACKAGE_HISTORY_PURPOSE_INVALID", "Explicit dedicated purpose required"
        )
    variable, role = ROLES[purpose]
    if set(os.environ) - {variable, "LANG", "LC_ALL", "LC_CTYPE", "TZ"}:
        raise GovernanceError(
            "PACKAGE_HISTORY_ENVIRONMENT_NOT_ISOLATED", "Use the fixed private purpose launcher"
        )
    if not os.environ.get(variable):
        raise GovernanceError(
            "PACKAGE_HISTORY_PURPOSE_NOT_CONFIGURED", "Dedicated LOGIN is missing"
        )
    with psycopg.connect(os.environ[variable], row_factory=dict_row) as c:
        who = c.execute(
            "SELECT current_user,session_user,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication,rolcanlogin,pg_has_role(session_user,%s,'MEMBER') AS allowed FROM pg_roles WHERE rolname=session_user",
            (role,),
        ).fetchone()
        if (
            who is None
            or who["current_user"] != who["session_user"]
            or not who["allowed"]
            or not who["rolcanlogin"]
            or any(
                who[key]
                for key in (
                    "rolsuper",
                    "rolbypassrls",
                    "rolcreatedb",
                    "rolcreaterole",
                    "rolreplication",
                )
            )
        ):
            raise GovernanceError(
                "PACKAGE_HISTORY_ROLE_DENIED", "Actual dedicated nonowner LOGIN required"
            )
        yield c


def ingest(*, scope_id, submission_id, outcome_id, adapter_id, envelope):
    """The two short transactions surround byte/signature checks, not vice versa."""
    from packages.model_governance import package_history_proofs as proofs

    with connection("verify") as c:
        material = c.execute(
            "SELECT package_historical_research.verification_material(%s,%s,%s,%s) AS value",
            (scope_id, submission_id, outcome_id, adapter_id),
        ).fetchone()["value"]
    normalized = proofs.verify(
        envelope,
        adapter=material["adapter"],
        context=material["context"],
        observed_at=material["observed_at"],
    )
    with connection("verify") as c:
        identity = c.execute(
            "SELECT package_historical_research.record_proof(%s,%s,%s,%s,%s,%s,%s) AS value",
            (
                scope_id,
                submission_id,
                outcome_id,
                adapter_id,
                Jsonb(envelope),
                Jsonb(normalized),
                material["context_digest"],
            ),
        ).fetchone()["value"]
    return {
        "proof_id": str(identity),
        "context_digest": material["context_digest"],
        "proof_digest": digest(normalized),
        "origin": material["adapter"]["origin"],
        "research_only": True,
        "formal_eligibility": "unavailable",
        "provider_requests": 0,
        "paid_calls": 0,
    }


def run(purpose, job_id, generation, *, complete_material=None):
    """Recover CPU work through its owned lease; final exposure commits first."""
    from packages.model_governance import package_history_cpu as cpu

    if purpose not in {"train", "evaluate"}:
        raise GovernanceError("PACKAGE_HISTORY_PURPOSE_INVALID", "Explicit CPU purpose required")
    if complete_material is not None and purpose != "train":
        raise GovernanceError("PACKAGE_HISTORY_COMPLETE_PURPOSE_DENIED", "Training purpose only")
    owner = uuid4()
    with connection(purpose) as c:
        lease = c.execute(
            "SELECT package_historical_research.claim_job(%s,%s,%s) AS value",
            (job_id, generation, owner),
        ).fetchone()["value"]
    if lease["state"] == "succeeded":
        if complete_material is not None:
            raise GovernanceError(
                "PACKAGE_HISTORY_COMPLETE_RESULT_ALREADY_FINISHED",
                "Read the existing job result; no new material was checked",
            )
        return lease | {"provider_requests": 0, "paid_calls": 0}
    lease_arguments = (job_id, lease["generation"], lease["fence"], owner)
    stopped = threading.Event()
    failures: list[BaseException] = []

    def renew():
        while not stopped.wait(25):
            try:
                with connection(purpose) as c:
                    c.execute(
                        "SELECT package_historical_research.renew_job(%s,%s,%s,%s)", lease_arguments
                    )
            except (psycopg.Error, GovernanceError) as error:
                failures.append(error)
                return

    heartbeat = threading.Thread(target=renew, daemon=True)
    heartbeat.start()
    try:
        if purpose == "train":
            with connection(purpose) as c:
                bundle = c.execute(
                    "SELECT package_historical_research.read_training(%s,%s,%s,%s) AS value",
                    lease_arguments,
                ).fetchone()["value"]
            from packages.model_governance import package_history_complete as complete

            result = (
                complete.run(bundle, complete_material)
                if complete_material is not None
                else cpu.train(complete.training_export(bundle))
            )
        else:
            with connection(purpose) as c:
                c.execute(
                    "SELECT package_historical_research.open_final(%s,%s,%s,%s)", lease_arguments
                )
            # The preceding context committed the irreversible exposure. This is
            # deliberately a different transaction and a different connection.
            with connection(purpose) as c:
                bundle = c.execute(
                    "SELECT package_historical_research.read_final(%s,%s,%s,%s) AS value",
                    lease_arguments,
                ).fetchone()["value"]
            result = cpu.evaluate(bundle)
        if failures:
            raise GovernanceError(
                "PACKAGE_HISTORY_LEASE_LOST", "CPU lease renewal failed; result is not published"
            )
        with connection(purpose) as c:
            c.execute(
                "SELECT package_historical_research.finish_job(%s,%s,%s,%s,%s,%s)",
                (*lease_arguments, Jsonb(result), digest(result)),
            )
        return {
            "job_id": str(job_id),
            "state": "succeeded",
            "result_digest": digest(result),
            "research_only": True,
            "formal_eligibility": "unavailable",
            "provider_requests": 0,
            "paid_calls": 0,
        }
    finally:
        stopped.set()
        heartbeat.join(timeout=10)
