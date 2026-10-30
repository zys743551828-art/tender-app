"""Explicit local-only Docker cleanup acceptance; never discovers business data."""

import json
import os
from pathlib import Path

import pytest

from deploy.disposable_docker import DockerTestRun

IMAGE = os.environ.get("DISPOSABLE_DOCKER_TEST_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="requires explicit existing local Python image")


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_native_resource_cleanup_for_every_outcome(tmp_path, outcome):
    assert IMAGE
    output = os.environ.get("DISPOSABLE_DOCKER_TEST_EVIDENCE")
    receipt = (Path(output) if output else tmp_path) / f"docker-{outcome}.json"
    run = DockerTestRun(receipt)
    try:
        with run:
            network = run.network()
            volume = run.volume()
            identity = run.container(
                IMAGE,
                [
                    "--network",
                    network,
                    "--read-only",
                    "--memory",
                    "128m",
                    "--entrypoint",
                    "python",
                    "--mount",
                    f"type=volume,source={volume},target=/test-data",
                ],
                [
                    "-c",
                    "from pathlib import Path;Path('/test-data/synthetic').write_bytes(b'test')",
                ],
            )
            run.start(identity, attach=True)
            if outcome == "failure":
                raise RuntimeError("synthetic-test-failure")
            if outcome == "cancel":
                raise KeyboardInterrupt
    except RuntimeError as error:
        assert outcome == "failure" and str(error) == "synthetic-test-failure"
    except KeyboardInterrupt:
        assert outcome == "cancel"
    assert run.closed
    assert all(item["state"] == "removed" for item in json.loads(receipt.read_text())["resources"])
    for item in run.resources:
        assert run._owned(item) is None
