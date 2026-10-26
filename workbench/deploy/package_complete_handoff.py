"""/3 modes behind the existing isolated historical-research launcher."""

from packages.model_governance import package_complete_features as features
from packages.model_governance import package_complete_handoff as handoff
from packages.storage.private_cas import PrivateContentStore


def execute(args):
    if args.purpose == "complete-feature-method":
        return {
            "version": handoff.VERSION,
            "feature_method_digest": features.method_digest(),
            "handoff_method_digest": handoff.method_digest(),
            "provider_requests": 0,
            "paid_calls": 0,
        }
    expected = {
        field: getattr(args, field)
        for field in (
            "source_commit",
            "origin",
            "expected_input_digest",
            "expected_binding_digest",
            "expected_feature_method_digest",
            "expected_handoff_method_digest",
        )
    }
    expected["command_id"] = str(args.command_id)
    with PrivateContentStore(args.material_store) as store:
        if args.purpose == "complete-feature-freeze":
            return handoff.freeze(store, args.artifact_dir, **expected)
        return handoff.reopen(
            store,
            args.artifact_dir,
            expected_artifact_digest=args.expected_artifact_digest,
            **expected,
        )
