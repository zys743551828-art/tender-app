"""Authenticated target-program execution; durable command precedes every IO."""

from dataclasses import dataclass
from pathlib import Path

from deploy import fusion_verified_material as controller
from packages.domain.review_identity import digest
from packages.model_governance import material_verification_program as port
from packages.model_governance import package_current_material as current
from packages.storage.private_cas import sha


@dataclass(frozen=True, repr=False)
class ProgramExecution:
    result: port.NativeProgramResult
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "fusion-verification-program/1",
            "source": sha(Path(__file__).read_bytes()),
            "port_method": port.method_digest(),
            "controller_method": controller.method_digest(),
            "grants_input_authority": False,
        }
    )


async def execute(
    program_connection,
    registration_connection,
    store_connection,
    scope_connection,
    original_connection,
    parse_connection,
    issuer_connection,
    *,
    runtime,
    command_id,
    expected_command_digest,
    expected_method_digest,
    profile,
    url_for_locator,
    byte_client=None,
):
    method = method_digest()
    if method != expected_method_digest:
        port.fail("PROGRAM_METHOD_MISMATCH")
    connections = (
        program_connection,
        registration_connection,
        store_connection,
        scope_connection,
        original_connection,
        parse_connection,
        issuer_connection,
    )
    if len({id(c) for c in connections}) != 7:
        port.fail("INDEPENDENT_CONNECTIONS_REQUIRED")
    current._idle(connections)
    owned = port.context(
        program_connection,
        command_id=command_id,
        expected_command_digest=expected_command_digest,
        expected_method_digest=port.method_digest(),
    )
    resumed = owned.prior_result is not None
    if resumed:
        result = owned.prior_result
    else:
        state = owned.metadata["current"]
        if not all(
            state[k] for k in ("program_configuration_current", "case_current", "review_current")
        ):
            port.fail("PROGRAM_CONFIGURATION_UNAVAILABLE")
        cfg = owned.metadata["configuration"]
        expected_profile = (
            "development_s3" if cfg["origin"] == "synthetic_mechanism" else "oss_hangzhou"
        )
        if (
            profile != expected_profile
            or cfg["controller_method_digest"] != controller.method_digest()
            or cfg["authority_policy_digest"] != port.policy_digest()
        ):
            port.fail("PROGRAM_POLICY_MISMATCH")
        args = dict(owned.metadata["review_arguments"]) | {
            "profile": profile,
            "url_for_locator": url_for_locator,
        }
        live = await controller.collect(
            *connections[1:],
            runtime=runtime,
            review_arguments=args,
            expected_method_digest=controller.method_digest(),
            byte_client=byte_client,
        )
        current._idle(connections)
        if method_digest() != method:
            port.fail("PROGRAM_METHOD_CHANGED")
        observation = {
            "version": "material-verification-execution/1",
            "command_id": command_id,
            "command_digest": expected_command_digest,
            "program_method_digest": method,
            "port_method_digest": port.method_digest(),
            "policy_digest": port.policy_digest(),
            "controller_method_digest": controller.method_digest(),
            "byte_profile": profile,
            "verified_material": live.metadata,
        }
        observation["digest"] = digest(observation)
        result = port.record_result(
            program_connection,
            command_id=command_id,
            expected_command_digest=expected_command_digest,
            observation=observation,
            expected_observation_digest=observation["digest"],
            expected_method_digest=port.method_digest(),
        )
    current._idle(connections)
    if method_digest() != method:
        port.fail("PROGRAM_METHOD_CHANGED")
    metadata = {
        "version": "material-verification-program-execution/1",
        "method_digest": method,
        "command_id": command_id,
        "command_digest": expected_command_digest,
        "result_digest": result.metadata["digest"],
        "resumed_completed_native_result": resumed,
        "new_controller_execution_performed": not resumed,
        "input_authority_granted": False,
        "execution_authorized": False,
    }
    return ProgramExecution(result, metadata | {"digest": digest(metadata)})
