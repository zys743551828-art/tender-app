"""Launch one exact-package owned job in a purpose-only child environment.

No paid adapter is constructed. An explicit response fixture exercises the actual
DeepSeek HTTP serialization/parser through httpx.MockTransport with zero network.
The database also requires an owner-registered disposable test environment and a
separate test Worker LOGIN. A request flag cannot qualify a production subject.
"""

import argparse
import json
import os
import shlex
import stat

# A fixed interpreter starts an owned script without a shell.
import subprocess  # nosec B404
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def environment(profile):
    path = Path(profile)
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > 16384
    ):
        raise ValueError("PACKAGE_SCORE_PROFILE_MUST_BE_PRIVATE_REGULAR_FILE")
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, raw = line.partition("=")
        if not separator or key.strip() != "PACKAGE_SCORE_DATABASE_DSN" or values:
            raise ValueError("PACKAGE_SCORE_PROFILE_MUST_CONTAIN_ONE_PURPOSE_DSN")
        items = shlex.split(raw, comments=True)
        if len(items) != 1 or not items[0]:
            raise ValueError("PACKAGE_SCORE_PROFILE_INVALID")
        values[key.strip()] = items[0]
    if not values:
        raise ValueError("PACKAGE_SCORE_PROFILE_MISSING_DSN")
    return values | {
        "WORKBENCH_ENV_FILE": "/dev/null",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }


class FixtureTransport:
    """Explicit local envelopes, real HTTP adapter, and no network-capable fallback."""

    isolated_mechanism_transport = True
    provider = "deepseek"
    model = "deepseek-flash"

    def __init__(self, path):
        import httpx

        from packages.domain.providers.deepseek import DeepSeekClient

        source = Path(path)
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 33554432:
            raise ValueError("PACKAGE_SCORE_FIXTURE_INVALID")
        value = json.loads(source.read_text())
        if (
            set(value) != {"schema", "synthetic", "responses"}
            or value["schema"] != "package-score-http-fixture/1"
            or value["synthetic"] is not True
        ):
            raise ValueError("PACKAGE_SCORE_FIXTURE_INVALID")
        self.responses = value["responses"]
        self.count = 0
        self.client = DeepSeekClient(
            api_key="isolated-mechanism-no-network",
            model=self.model,
            transport=httpx.MockTransport(self.respond),
        )

    def respond(self, request):
        import httpx

        from packages.domain.runtime import sha

        body = json.loads(request.content)
        if self.count >= len(self.responses):
            raise ValueError("PACKAGE_SCORE_FIXTURE_EXHAUSTED")
        row = self.responses[self.count]
        self.count += 1
        if set(row) != {"request_digest", "response"} or sha(body) != row["request_digest"]:
            raise ValueError("PACKAGE_SCORE_FIXTURE_REQUEST_MISMATCH")
        return httpx.Response(200, json=row["response"])

    def generate(self, **request):
        return self.client.generate(**request)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--mechanism-response-fixture", type=Path)
    parser.add_argument("--owned-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.owned_child:
        if args.profile is None:
            parser.error("--profile is required")
        command = [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            "--owned-child",
            "--job-id",
            args.job_id,
            "--generation",
            str(args.generation),
        ]
        if args.mechanism_response_fixture:
            command += [
                "--mechanism-response-fixture",
                str(args.mechanism_response_fixture.resolve()),
            ]
        # Only the running interpreter and this owned script can be executed.
        result = subprocess.run(  # nosec B603
            command, cwd=ROOT, env=environment(args.profile), check=False
        )
        return result.returncode
    if args.profile is not None or os.environ.get("WORKBENCH_ENV_FILE") != "/dev/null":
        raise ValueError("PACKAGE_SCORE_CHILD_NOT_ISOLATED")
    sys.path.insert(0, str(ROOT))
    from uuid import UUID

    from packages.domain.runtime import DomainError
    from packages.model_governance.package_scoring_runtime import execute_job

    transport = (
        FixtureTransport(args.mechanism_response_fixture)
        if args.mechanism_response_fixture
        else None
    )
    try:
        result = execute_job(UUID(args.job_id), args.generation, transport=transport)
    except DomainError as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": error.code,
                    "job_id": args.job_id,
                    "mock_http_calls": transport.count if transport else 0,
                    "paid_calls": 0,
                }
            )
        )
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "job_id": args.job_id,
                "items": len(result["items"]),
                "mock_http_calls": transport.count if transport else 0,
                "paid_calls": 0,
                "execution_mode": result["execution_mode"],
                "formal_scoring_eligible": result["formal_scoring_eligible"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
