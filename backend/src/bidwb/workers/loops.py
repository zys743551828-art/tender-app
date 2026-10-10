"""发件箱中继与回收器的主循环。"""

from __future__ import annotations

import threading

from bidwb import db, tasks
from bidwb.logs import get_logger
from bidwb.messaging import Producer
from bidwb.runtime import Container
from bidwb.services import pipeline

log = get_logger(__name__)


def relay_forever(ctr: Container, producer: Producer, stop: threading.Event) -> None:
    """持续把未发布的发件箱记录送到 Kafka。有积压时不休眠，空闲时按 ``relay_poll_seconds`` 轮询。"""
    s = ctr.settings
    log.info("relay_started", batch=s.relay_batch_size)
    while not stop.is_set():
        sent = 0
        try:
            with db.transaction(ctr.engine) as conn:
                sent = tasks.relay_outbox(conn, producer, s.relay_batch_size)
        except Exception:
            log.error("relay_error", exc_info=True)
            stop.wait(2.0)
            continue
        if sent == 0:
            stop.wait(s.relay_poll_seconds)
        else:
            log.info("relay_published", count=sent)
    producer.close()
    log.info("relay_stopped")


def reap_forever(ctr: Container, stop: threading.Event) -> None:
    s = ctr.settings
    log.info("reaper_started", interval=s.reaper_interval_seconds)
    while not stop.is_set():
        try:
            with db.transaction(ctr.engine) as conn:
                result = tasks.reap(conn, redispatch_after_seconds=s.redispatch_after_seconds)
            if any(result.values()):
                log.info("reaper_acted", **result)
            if s.auto_analysis:
                with db.transaction(ctr.engine) as conn:
                    pipeline.advance_active(conn, ctr.store)  # 兜底：推进回调丢失而停住的项目
        except Exception:
            log.error("reaper_error", exc_info=True)
        stop.wait(s.reaper_interval_seconds)
    log.info("reaper_stopped")
