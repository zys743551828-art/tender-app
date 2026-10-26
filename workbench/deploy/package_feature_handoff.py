"""Local feature modes of the existing history launcher; never load credentials."""

import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"}


def run(args):
    if not args.owned_child:
        command = [
            sys.executable,
            "-I",
            str(ROOT / "deploy/package_history_worker.py"),
            "--owned-child",
            "--purpose",
            args.purpose,
        ]
        for field in (
            "selection",
            "labels",
            "result_dir",
            "expected_selection_digest",
            "expected_labels_digest",
            "expected_calibration_method_digest",
            "material_store",
            "source_commit",
            "expected_input_digest",
            "artifact_dir",
            "command_id",
            "projection",
            "origin",
            "expected_projection_digest",
            "expected_binding_digest",
            "expected_feature_method_digest",
            "expected_handoff_method_digest",
            "expected_artifact_digest",
        ):
            value = getattr(args, field)
            if value is not None:
                command.extend(
                    [
                        "--" + field.replace("_", "-"),
                        str(value.absolute() if isinstance(value, Path) else value),
                    ]
                )
        return subprocess.run(command, cwd=ROOT, env=ENV, check=False).returncode  # nosec B603
    from packages.domain.providers.deepseek_vision import VisionProviderError
    from packages.model_governance import package_feature_handoff as handoff
    from packages.model_governance import package_technical_features as features
    from packages.model_governance.common import GovernanceError

    try:
        if set(os.environ) - set(ENV):
            handoff.fail("ENVIRONMENT_NOT_ISOLATED")
        if args.purpose == "native-feature-method":
            from packages.model_governance import package_history_complete as complete

            value = {
                "version": complete.VERSION,
                "method_digest": complete.method_digest(),
                "provider_requests": 0,
                "paid_calls": 0,
            }
        elif args.purpose.startswith("complete-calibration-"):
            from deploy.package_complete_calibration import execute

            value = execute(args)
        elif args.purpose.startswith("complete-feature-"):
            from deploy.package_complete_handoff import execute

            value = execute(args)
        elif args.purpose == "feature-method":
            value = {
                "version": handoff.VERSION,
                "feature_method_digest": features.method_digest(),
                "handoff_method_digest": handoff.method_digest(),
                "provider_requests": 0,
                "paid_calls": 0,
            }
        else:
            expected = {
                field: getattr(args, field)
                for field in (
                    "origin",
                    "expected_projection_digest",
                    "expected_binding_digest",
                    "expected_feature_method_digest",
                    "expected_handoff_method_digest",
                )
            }
            expected["command_id"] = str(args.command_id)
            if args.purpose == "feature-freeze":
                projection = handoff.decode(
                    handoff.private_read(args.projection, maximum=features.MAX_BYTES)
                )
                value = handoff.freeze(args.artifact_dir, projection, **expected)
            else:
                value = handoff.reopen(
                    args.artifact_dir,
                    expected_artifact_digest=args.expected_artifact_digest,
                    **expected,
                )
    except (GovernanceError, features.FeatureProjectionError) as error:
        print(
            json.dumps({"ok": False, "code": error.code, "provider_requests": 0, "paid_calls": 0})
        )
        return 2
    except (
        OSError,
        TypeError,
        ValueError,
        KeyError,
        ArithmeticError,
        RecursionError,
        VisionProviderError,
    ):
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "PACKAGE_FEATURE_HANDOFF_REJECTED",
                    "provider_requests": 0,
                    "paid_calls": 0,
                }
            )
        )
        return 2
    print(json.dumps({"ok": True, "result": value}))
    return 0
