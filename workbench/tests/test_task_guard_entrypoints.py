"""Fresh interpreters prove independent composition without a Web import or resource I/O."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def fresh(script):
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=os.environ | {"WORKBENCH_ENV_FILE": "review-readonly", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_domain_alone_retains_fail_closed_task_guard():
    result = fresh(
        """
from packages.domain import reviews
from packages.domain.runtime import DomainError
assert reviews.TASK_INPUT_GUARD is reviews._unregistered_task_guard
assert reviews.TASK_INPUT_GUARD(None, None, {}) is True
try:
    reviews.TASK_INPUT_GUARD(None, None, {'task_binding': {'run_id': 'synthetic'}})
except DomainError as error:
    assert error.code == 'TASK_REVIEW_EXECUTOR_NOT_READY'
else:
    raise AssertionError('unconfigured task inputs were authorized')
"""
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "entry", ["apps.api.review_coordinator", "packages.tasks.runner", "apps.api.main"]
)
def test_each_entrypoint_installs_exact_guard_without_opening_resources(entry):
    result = fresh(
        f"""
import importlib
import sys
from packages.domain import runtime, reviews
def unexpected(*args, **kwargs):
    raise AssertionError('composition opened a resource')
runtime.connection = unexpected
runtime.assert_role = unexpected
assert reviews.TASK_INPUT_GUARD is reviews._unregistered_task_guard
importlib.import_module({entry!r})
from packages.tasks.inputs import review_guard
assert reviews.TASK_INPUT_GUARD is review_guard
if {entry!r} != 'apps.api.main':
    assert 'apps.api.main' not in sys.modules
assert review_guard(None, None, {{}}) is True
"""
    )
    assert result.returncode == 0, result.stderr
