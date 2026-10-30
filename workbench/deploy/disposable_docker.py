"""Own and clean only one run's explicitly disposable Docker test resources.

Use as a context manager, including around service startup. Receipts contain no
environment values or command output. Persistent desktop environments never use
this helper and are never discovered or removed by it.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404
from pathlib import Path
from uuid import uuid4

RUN_LABEL = "tender.test.run"
DISPOSABLE_LABEL = "tender.test.disposable"


class DockerTestRun:
    def __init__(self, receipt: Path):
        if receipt.exists():
            raise FileExistsError("DOCKER_TEST_RECEIPT_EXISTS")
        self.receipt = receipt
        self.run_id = uuid4().hex
        self.resources: list[dict] = []
        self.closed = False
        self._save()

    def _save(self):
        self.receipt.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.receipt.with_suffix(self.receipt.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {"run_id": self.run_id, "closed": self.closed, "resources": self.resources},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.receipt)

    @staticmethod
    def _call(*args, timeout=60, env=None):
        return subprocess.run(  # nosec B603
            ["docker", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            check=False,
        )

    def _owned(self, resource):
        target = resource["id"] or resource["name"]
        result = self._call(resource["kind"], "inspect", target)
        if result.returncode:
            missing = (
                f"no such {resource['kind']}: {target}",
                f"{resource['kind']} {target} not found",
                f"get {target}: no such volume",
            )
            if any(message in result.stderr.lower() for message in missing):
                return None
            raise RuntimeError("DOCKER_TEST_INSPECTION_FAILED")
        value = json.loads(result.stdout)[0]
        labels = (value.get("Config") or {}).get("Labels") or value.get("Labels") or {}
        if labels.get(RUN_LABEL) != self.run_id or labels.get(DISPOSABLE_LABEL) != "true":
            raise RuntimeError("DOCKER_TEST_RESOURCE_OWNERSHIP_CHANGED")
        if value.get("Id") and resource["id"] and value["Id"] != resource["id"]:
            raise RuntimeError("DOCKER_TEST_RESOURCE_ID_CHANGED")
        return value

    def _create(self, kind, arguments, *, env=None):
        if self.closed:
            raise RuntimeError("DOCKER_TEST_RUN_CLOSED")
        name = f"tender-test-{self.run_id[:12]}-{len(self.resources) + 1}"
        resource = {"kind": kind, "name": name, "id": None, "state": "creating"}
        # Record the exact generated target before Docker can create anything,
        # so a timeout after creation still follows the ownership check in finally.
        self.resources.append(resource)
        self._save()
        labels = ["--label", f"{RUN_LABEL}={self.run_id}", "--label", f"{DISPOSABLE_LABEL}=true"]
        args = [kind, "create", *labels]
        if kind == "container":
            args += ["--name", name, "--pull", "never", *arguments]
        else:
            args += [*arguments, name]
        result = self._call(*args, env=env)
        if result.returncode:
            raise RuntimeError("DOCKER_TEST_CREATE_FAILED")
        resource["id"] = result.stdout.strip()
        resource["state"] = "created"
        self._save()
        return resource["id"]

    def network(self):
        return self._create("network", ["--internal"])

    def volume(self):
        return self._create("volume", [])

    def container(self, image: str, arguments=(), command=(), *, env=None):
        # Mask image-declared data directories with tmpfs. Docker would otherwise
        # silently create anonymous volumes which have no ownership labels.
        result = self._call("image", "inspect", image)
        if result.returncode:
            raise RuntimeError("DOCKER_TEST_LOCAL_IMAGE_REQUIRED")
        config = json.loads(result.stdout)[0].get("Config") or {}
        temporary = [arg for path in (config.get("Volumes") or {}) for arg in ("--tmpfs", path)]
        return self._create("container", [*temporary, *arguments, image, *command], env=env)

    def start(self, identity: str, *, attach=False, timeout=60):
        resource = next(item for item in self.resources if item["id"] == identity)
        if resource["kind"] != "container" or self._owned(resource) is None:
            raise RuntimeError("DOCKER_TEST_CONTAINER_REQUIRED")
        result = self._call("start", *(["--attach"] if attach else []), identity, timeout=timeout)
        if result.returncode:
            raise RuntimeError("DOCKER_TEST_START_FAILED")
        return result

    def cleanup(self):
        errors = []
        for resource in reversed(self.resources):
            if resource["state"] == "removed":
                continue
            try:
                value = self._owned(resource)
                if value is not None:
                    target = value.get("Id") or resource["name"]
                    flags = ["--force"] if resource["kind"] == "container" else []
                    result = self._call(resource["kind"], "rm", *flags, target)
                    if result.returncode:
                        raise RuntimeError("DOCKER_TEST_REMOVAL_FAILED")
                resource["state"] = "removed"
                resource.pop("cleanup_error", None)
            except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
                resource["cleanup_error"] = (
                    str(error) if isinstance(error, RuntimeError) else "DOCKER_TEST_CLEANUP_FAILED"
                )
                errors.append(resource["cleanup_error"])
            self._save()
        self.closed = not errors
        self._save()
        if errors:
            raise RuntimeError("DOCKER_TEST_CLEANUP_INCOMPLETE: inspect the run receipt")

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        try:
            self.cleanup()
        except RuntimeError:
            if error is None:
                raise
        return False
