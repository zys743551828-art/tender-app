"""Pending command records cannot be interpreted as executed authority."""

from copy import deepcopy
from uuid import uuid4

import pytest

from packages.domain.review_identity import digest
from packages.model_governance import material_verification_commands as commands


def record():
    d = {
        **{k: str(uuid4()) for k in commands.UUID_FIELDS},
        **{k: "a" * 64 for k in commands.SHA_FIELDS},
        **{k: False for k in commands.FALSE_FIELDS},
        "version": "material-verification-command/1",
        "target_login": "synthetic_target",
        "target_login_oid": 1234,
        "origin": "synthetic_mechanism",
        "profile_head_revision": 1,
        "case_head_revision": 1,
        "recorded_by": "synthetic_requester",
        "recorded_by_oid": 1235,
        "recorded_at": "2026-10-24T00:00:00Z",
        "status": "pending_controlled_verification",
    }
    return {"document": d, "digest": digest(d)}


def test_pending_native_command_has_no_program_or_input_authority():
    result = commands._record(record())
    assert not any(result.metadata["document"][k] for k in commands.FALSE_FIELDS)


@pytest.mark.parametrize(
    "change", ["extra", "executed", "oid", "zero", "revision", "time", "status"]
)
def test_rehashed_command_cannot_change_schema_identity_or_qualification(change):
    value = deepcopy(record())
    d = value["document"]
    if change == "extra":
        d["execution_receipt"] = {}
    elif change == "executed":
        d["controlled_program_executed"] = True
    elif change == "oid":
        d["target_login_oid"] = True
    elif change == "zero":
        d["controller_method_digest"] = "0" * 64
    elif change == "revision":
        d["profile_head_revision"] = 0
    elif change == "time":
        d["recorded_at"] = "2026-10-24T00:00:00"
    else:
        d["status"] = "input_verified"
    value["digest"] = digest(d)
    with pytest.raises(commands.VerificationCommandError):
        commands._record(value)
