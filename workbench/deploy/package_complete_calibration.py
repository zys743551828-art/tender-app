"""Synthetic-only calibration modes of the existing isolated history launcher."""

from packages.model_governance import package_complete_calibration as calibration
from packages.model_governance import package_feature_handoff as local
from packages.storage.private_cas import PrivateContentStore


def execute(args):
    if args.purpose == "complete-calibration-method":
        return {
            "version": calibration.VERSION,
            "calibration_method_digest": calibration.method_digest(),
            "provider_requests": 0,
            "paid_calls": 0,
        }
    with PrivateContentStore(args.material_store) as store:
        if args.expected_feature_training_method_digest is not None:
            from packages.model_governance import package_feature_training_io as feature_io

            if args.purpose == "complete-calibration-read":
                return feature_io.reopen(
                    store,
                    args.artifact_dir,
                    args.result_dir,
                    command_id=str(args.command_id),
                    expected_artifact_digest=args.expected_artifact_digest,
                    expected_feature_training_method_digest=args.expected_feature_training_method_digest,
                )
            return feature_io.freeze(
                store,
                args.artifact_dir,
                args.result_dir,
                local.private_read(args.selection, maximum=calibration.MAX_BYTES),
                local.private_read(args.labels, maximum=calibration.MAX_BYTES),
                command_id=str(args.command_id),
                expected_feature_training_method_digest=args.expected_feature_training_method_digest,
                **{
                    field: getattr(args, field)
                    for field in (
                        "expected_selection_digest",
                        "expected_labels_digest",
                        "expected_calibration_method_digest",
                    )
                },
            )
        if args.purpose == "complete-calibration-read":
            return calibration.reopen(
                store,
                args.artifact_dir,
                args.result_dir,
                command_id=str(args.command_id),
                expected_artifact_digest=args.expected_artifact_digest,
            )
        return calibration.freeze(
            store,
            args.artifact_dir,
            args.result_dir,
            local.private_read(args.selection, maximum=calibration.MAX_BYTES),
            local.private_read(args.labels, maximum=calibration.MAX_BYTES),
            command_id=str(args.command_id),
            **{
                field: getattr(args, field)
                for field in (
                    "expected_selection_digest",
                    "expected_labels_digest",
                    "expected_calibration_method_digest",
                )
            },
        )
