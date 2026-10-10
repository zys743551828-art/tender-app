"""进程入口（pyproject 的 console scripts）。每个入口只做装配与信号处理。"""

from __future__ import annotations

import os
import signal
import sys
import threading

import uvicorn

from bidwb.ai.handlers import build_handlers
from bidwb.ai.llm import build_llm
from bidwb.config import get_settings
from bidwb.logs import configure_logging, get_logger
from bidwb.messaging import KafkaEventConsumer, KafkaEventProducer
from bidwb.runtime import build_worker_container
from bidwb.workers.loops import reap_forever, relay_forever
from bidwb.workers.runner import WorkerRunner

log = get_logger(__name__)
WORKER_CLASSES = ("parse", "ai", "experiment", "export")


def _stop_event() -> threading.Event:
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    return stop


def run_api() -> None:
    settings = get_settings()
    uvicorn.run(
        "bidwb.api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        access_log=False,
        reload=os.environ.get("BIDWB_API_RELOAD", "").lower() == "true",
        log_config=None,
        timeout_graceful_shutdown=30,
    )


def run_relay() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    ctr = build_worker_container(settings, "bidwb-relay")
    relay_forever(ctr, KafkaEventProducer(settings), _stop_event())
    ctr.close()


def run_reaper() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    ctr = build_worker_container(settings, "bidwb-reaper")
    reap_forever(ctr, _stop_event())
    ctr.close()


def run_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    job_class = os.environ.get("BIDWB_WORKER_CLASS", "")
    if job_class not in WORKER_CLASSES:
        log.error("invalid_worker_class", value=job_class, allowed=WORKER_CLASSES)
        sys.exit(2)
    ctr = build_worker_container(settings, f"bidwb-worker-{job_class}")
    consumer = KafkaEventConsumer(settings, group_id=f"bidwb-{job_class}", topics=[f"job.{job_class}"])
    runner = WorkerRunner(ctr, job_class, consumer, build_handlers(build_llm(ctr.settings)), consumer_name=f"worker-{job_class}")
    runner.run_forever(_stop_event())
    ctr.close()
