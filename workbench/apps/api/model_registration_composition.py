"""HTTP wiring for model registration; no new model authority or configuration."""

from collections.abc import Callable

from packages.model_registration.application import ModelRegistration
from packages.model_registration.infrastructure import RegistryObjects, SqlTransactions


def service(connect: Callable) -> ModelRegistration:
    return ModelRegistration(SqlTransactions(connect), RegistryObjects())
