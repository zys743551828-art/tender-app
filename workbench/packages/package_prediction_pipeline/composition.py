"""Opt-in composition; original task/worker protocol and credentials remain unchanged."""

from packages.package_prediction_pipeline import runtime
from packages.package_prediction_pipeline.application import Pipeline
from packages.package_prediction_pipeline.native import Transactions
from packages.package_prediction_tasks import composition as tasks
from packages.package_prediction_tasks import runtime as task_runtime
from packages.package_prediction_tasks.application import Jobs
from packages.package_prediction_tasks.storage import Objects


def api(app, predictions):
    tasks.api(app, predictions)
    tx = Transactions(predictions.transactions.connections)
    jobs = Jobs(tx.tasks, Objects())
    app.state.package_prediction_jobs = jobs
    app.state.package_prediction_pipeline = Pipeline(tx, jobs)
    return app.state.package_prediction_pipeline


def coordinator(predictions):
    tasks.coordinator(predictions)
    tx = Transactions(predictions.transactions.connections)
    jobs = Jobs(tx.tasks, Objects())
    service = Pipeline(tx, jobs)
    task_runtime.configure(jobs, predictions.transactions.connections)
    runtime.configure(service, predictions.transactions.connections)
    return service
