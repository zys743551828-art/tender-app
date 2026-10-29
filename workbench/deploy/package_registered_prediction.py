"""Local /3 research inference from a fixed registry artifact; no network or DB."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.path.insert(0, str(ROOT))
    from packages.domain.review_identity import canonical
    from packages.model_governance import package_complete_handoff as handoff
    from packages.model_governance import package_feature_handoff as files
    from packages.package_model_registry import artifact
    from packages.storage.private_cas import PrivateContentStore, sha

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--registry-receipt", type=Path)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--expected-request-digest", required=True)
    args = parser.parse_args()
    try:
        raw = files.private_read(args.request, maximum=16384)
        if sha(raw) != files.checksum(args.expected_request_digest):
            artifact.fail()
        request = files.decode(raw)
        handoff.exact(
            request,
            {"version", "command_id", "artifact_digest", "reference", "expected_input_digest"},
        )
        if request["version"] != "registered-package-research-request/1":
            artifact.fail()
        files.command(request["command_id"])
        with PrivateContentStore(args.store) as store:
            if args.registry_receipt:
                receipt = files.decode(
                    files.private_read(args.registry_receipt, maximum=artifact.MAX_BYTES)
                )
                handoff.exact(
                    receipt,
                    {
                        "schema",
                        "model_id",
                        "document",
                        "artifact_digest",
                        "created_at",
                        "research_only",
                        "formal_eligibility",
                        "certification_issued",
                    },
                )
                if (
                    receipt["schema"] != "registered-package-score-receipt/1"
                    or receipt["artifact_digest"] != request["artifact_digest"]
                    or receipt["research_only"] is not True
                    or receipt["certification_issued"] is not False
                    or receipt["formal_eligibility"] != "unavailable"
                    or receipt["model_id"] != receipt["document"].get("model_id")
                ):
                    artifact.fail()
                blob = canonical(receipt["document"])
                artifact.load(blob, request["artifact_digest"])
                if store.put_object(blob) != request["artifact_digest"]:
                    artifact.fail()
            document = artifact.load(
                store.get_object(request["artifact_digest"]), request["artifact_digest"]
            )
            result = artifact.consume(
                document,
                store,
                args.artifact_dir,
                request["reference"],
                expected_input_digest=request["expected_input_digest"],
            )
            result_digest = store.put_object(canonical(result))
            if store.get_object(result_digest) != canonical(result):
                artifact.fail()
            record = canonical(
                {
                    "version": "registered-package-research-receipt/1",
                    "command_id": request["command_id"],
                    "request_digest": sha(raw),
                    "result_digest": result_digest,
                    "artifact_digest": request["artifact_digest"],
                    "formal_eligibility": "unavailable",
                }
            )
            replayed = handoff._index(args.result_dir, record, request["command_id"])
        print(json.dumps(files.decode(record) | {"replayed": replayed}))
        return 0
    except Exception:
        # Never print private paths, DSNs, source bytes or provider content.
        print(json.dumps({"ok": False, "code": "PACKAGE_REGISTERED_RESEARCH_REJECTED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
