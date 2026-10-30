"""Explicit local profile/conversion CLI for the official prebuilt Word candidate.

No image build/pull, business .env, arbitrary endpoint or production wiring.
Use ``describe`` for the candidate's limitations before native qualification.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def write_new(path: Path, content: bytes) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
        file.write(content)


def read_regular(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("WORD_PREBUILT_INPUT_FILE_INVALID")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError("WORD_PREBUILT_INPUT_FILE_INVALID")
    return content


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("describe")
    profile = sub.add_parser("profile")
    profile.add_argument("--profile", type=Path, required=True)
    profile.add_argument("--receipt", type=Path, required=True)
    profile.add_argument("--lane", choices=("external", "page", "rich"), default="external")
    convert = sub.add_parser("convert")
    convert.add_argument("--profile", type=Path, required=True)
    convert.add_argument("--receipt", type=Path, required=True)
    convert.add_argument("--source", type=Path, required=True)
    convert.add_argument("--output", type=Path, required=True)
    convert.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    previous = os.environ.get("WORKBENCH_ENV_FILE")
    try:
        # Existing OOXML inspection imports a compatibility module with dotenv
        # bootstrap. Select a guaranteed nonexistent file for this isolated CLI.
        with tempfile.TemporaryDirectory(prefix="word-prebuilt-cli-") as directory:
            os.environ["WORKBENCH_ENV_FILE"] = str(Path(directory) / "no-business.env")
            from packages.word_intake import prebuilt

            if args.action == "describe":
                print(json.dumps(prebuilt.capabilities(), ensure_ascii=False))
                return 0
            destinations = (
                [args.profile] if args.action == "profile" else [args.output, args.report]
            )
            if any(path.exists() or path.is_symlink() for path in [*destinations, args.receipt]):
                raise ValueError("WORD_PREBUILT_DESTINATION_EXISTS")
            if (
                len({path.resolve() for path in [*destinations, args.receipt]})
                != len(destinations) + 1
            ):
                raise ValueError("WORD_PREBUILT_DESTINATIONS_MUST_DIFFER")
            if args.action == "profile":
                value = prebuilt.build_profile(receipt=args.receipt)
                if args.lane == "page":
                    from packages.authoring.prebuilt_generated import profile_for

                    value = profile_for(value)
                elif args.lane == "rich":
                    from packages.authoring.prebuilt_rich import profile_for

                    value = profile_for(value)
                write_new(
                    args.profile, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
                )
                print(
                    json.dumps(
                        {
                            "profile_digest": value["profile_digest"],
                            "protocol": value["identity"]["protocol"],
                        }
                    )
                )
                return 0
            value = json.loads(read_regular(args.profile, 1024 * 1024))
            result = prebuilt.render(
                read_regular(args.source, prebuilt.MAX_SOURCE), value, receipt=args.receipt
            )
            pdf = result.pop("pdf", None)
            if pdf is not None:
                write_new(args.output, pdf)
            write_new(
                args.report, (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
            )
            print(json.dumps({key: result[key] for key in ("state", "coverage", "error_code")}))
            return 0 if result["state"] == "succeeded" else 1
    except Exception as error:
        # Never emit raw exception, source, Docker output or private paths.
        code = str(error) if type(error).__name__ == "PrebuiltError" else "WORD_PREBUILT_CLI_FAILED"
        print(json.dumps({"state": "failed", "error_code": code}), file=sys.stderr)
        return 1
    finally:
        if previous is None:
            os.environ.pop("WORKBENCH_ENV_FILE", None)
        else:
            os.environ["WORKBENCH_ENV_FILE"] = previous


if __name__ == "__main__":
    raise SystemExit(main())
