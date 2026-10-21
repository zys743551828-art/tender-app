"""Isolated B4 Word output, exact sources, real Worker/S3 and explicit package adoption."""

import argparse
from pathlib import Path

from deploy.authoring_exact_revision_acceptance import EXTENSIONS, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--weed", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path)
    return run(
        parser.parse_args(),
        test_files=("tests/test_authoring_exact_builds_pg.py",),
        stage="B4 exact revision builds, real DOCX/S3, explicit package adoption and current-use guards",
        extensions=(*EXTENSIONS, "packages/contracts/sql/authoring-exact-builds.sql"),
        extra_sources=(
            "deploy/authoring_exact_build_acceptance.py",
            "tests/test_authoring_exact_revisions_pg.py",
            "apps/api/authoring.py",
            "apps/api/authoring_package_routes.py",
            "apps/worker/export_handlers.py",
        ),
        schema="authoring-exact-build-acceptance/1",
    )


if __name__ == "__main__":
    raise SystemExit(main())
