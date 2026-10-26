"""Explicit host injection using existing native roles/stores; no env or secret discovery."""

from packages.package_model_live.producer import Executor
from packages.package_prediction.application import Predictions
from packages.package_prediction.infrastructure import NativeTransactions
from packages.package_prediction_tasks import runtime, worker
from packages.package_prediction_tasks.application import Jobs
from packages.package_prediction_tasks.native import Transactions
from packages.package_prediction_tasks.storage import Objects


def api(app, predictions):
    if (
        type(predictions) is not Predictions
        or type(predictions.transactions) is not NativeTransactions
        or type(predictions.executor) is not Executor
    ):
        raise ValueError("native prediction dependencies required")
    jobs = Jobs(Transactions(predictions.transactions.connections), Objects())
    app.state.package_prediction_service = predictions
    app.state.package_prediction_jobs = jobs
    return jobs


def coordinator(predictions):
    if (
        type(predictions) is not Predictions
        or type(predictions.transactions) is not NativeTransactions
    ):
        raise ValueError("native API transaction factory required")
    jobs = Jobs(Transactions(predictions.transactions.connections), Objects())
    runtime.configure(jobs, predictions.transactions.connections)
    return jobs


def compute(executor):
    worker.configure(executor)
