"""HTTP composition root: production adapters are wired here, not in use cases."""

from collections.abc import Callable

from packages.material_jobs.application import MaterialJobs
from packages.material_jobs.infrastructure import SqlTransactions
from packages.model_governance import material_qualified_job_transport as native


def service(connect: Callable) -> MaterialJobs:
    return MaterialJobs(SqlTransactions(connect), native.submit)
