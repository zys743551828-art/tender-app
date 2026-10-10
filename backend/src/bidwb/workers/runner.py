"""任务 worker 运行器：消费消息 → 领取租约 → 执行处理器 → 条件提交。

关键时序（TECH-001 §7）：
* 领取成功（或确认无需处理）后**立即**提交 Kafka 位点，之后长任务期间不再轮询，因此不会触发消费组重平衡；
  消息丢失/重复由回收器重发与领取的条件更新吸收，不依赖 Kafka 的投递保证。
* 长任务期间由后台线程按固定间隔续租；续租失败（租约丢失或收到取消请求）会设置标志，处理器在检查点处退出。
* 结果提交在一个事务里完成：登记产物 → ``commit_result`` 校验租约（行锁）→ ``finalize`` 写领域记录。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass

from bidwb import db, tasks
from bidwb.errors import Conflict, DomainError, Unavailable
from bidwb.logs import get_logger
from bidwb.messaging import Consumer, Delivery
from bidwb.runtime import Container
from bidwb.services import pipeline
from bidwb.storage import ObjectStoreError, artifact_key
from bidwb.tasks import Claim
from bidwb.util import new_id, sha256_hex, utcnow
from bidwb.workers.handlers import Handler, HandlerFailure, HandlerOutput, JobContext, LeaseLost

log = get_logger(__name__)


class _LeaseKeeper:
    """后台续租线程；``lost`` / ``cancelled`` 由处理器的检查点读取。"""

    def __init__(self, ctr: Container, claim: Claim) -> None:
        self._ctr, self._claim = ctr, claim
        self._stop = threading.Event()
        self.lost = False
        self.cancelled = False
        self._thread = threading.Thread(target=self._run, name=f"lease-{claim.job_id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        interval = self._ctr.settings.lease_renew_seconds
        while not self._stop.wait(interval):
            try:
                with db.transaction(self._ctr.engine) as conn:
                    tasks.renew_lease(conn, self._claim, self._ctr.settings.lease_seconds)
            except Conflict as exc:
                self.cancelled = exc.code == "cancel_requested"
                self.lost = not self.cancelled
                return
            except Exception:
                log.warning("lease_renew_failed", job_id=self._claim.job_id, exc_info=True)

    def checkpoint(self) -> None:
        if self.lost or self.cancelled:
            raise LeaseLost


@dataclass
class WorkerRunner:
    ctr: Container
    job_class: str
    consumer: Consumer
    handlers: dict[str, Handler]
    consumer_name: str

    # ---- 消息入口
    def handle_delivery(self, delivery: Delivery) -> None:
        try:
            job_id = str(delivery.json()["job_id"])
        except (ValueError, KeyError, json.JSONDecodeError):
            log.error("bad_message", topic=delivery.topic, event_id=delivery.event_id)
            self.consumer.commit(delivery)  # 无法解析的消息重试也没用，提交位点避免卡住分区
            return
        claim: Claim | None = None
        with db.transaction(self.ctr.engine) as conn:
            if not delivery.event_id or tasks.consume_once(conn, self.consumer_name, delivery.event_id):
                claim = tasks.claim_job(conn, job_id, self.ctr.settings.worker_id, self.job_class, self.ctr.settings.lease_seconds)
        self.consumer.commit(delivery)
        if claim is None:
            log.info("job_not_claimed", job_id=job_id)
            return
        self.execute(claim)

    def poll_once(self, timeout: float = 1.0) -> bool:
        delivery = self.consumer.poll(timeout)
        if delivery is None:
            return False
        self.handle_delivery(delivery)
        return True

    # ---- 执行与提交
    def execute(self, claim: Claim) -> None:
        structlog_ctx = {"job_id": claim.job_id, "kind": claim.kind, "attempt": claim.attempt}
        handler = self.handlers.get(claim.kind)
        if handler is None:
            self._fail(claim, "kind_not_implemented")
            return
        keeper = _LeaseKeeper(self.ctr, claim)
        keeper.start()
        try:
            ctx = JobContext(claim, self.ctr.engine, self.ctr.store, self.ctr.settings, keeper.checkpoint)
            outcome = handler(ctx)
            keeper.checkpoint()
        except LeaseLost:
            keeper.stop()
            self._after_interrupt(claim, keeper)
            return
        except (ObjectStoreError, Unavailable) as exc:
            keeper.stop()
            log.warning("job_transient_failure", error=type(exc).__name__, **structlog_ctx)
            self._release(claim, "dependency_unavailable")
            return
        except Exception as exc:
            keeper.stop()
            log.error("job_handler_crashed", exc_info=exc, **structlog_ctx)
            self._fail(claim, f"worker_error:{type(exc).__name__}")
            return
        keeper.stop()
        if isinstance(outcome, HandlerFailure):
            self._fail(claim, outcome.error_code, outcome.message)
        else:
            self._succeed(claim, outcome)

    def _succeed(self, claim: Claim, output: HandlerOutput) -> None:
        artifact_id = new_id("art")
        key = artifact_key(artifact_id)
        try:
            self.ctr.store.put(key, output.artifact_bytes, output.media_type)
            with db.transaction(self.ctr.engine) as conn:
                db.run(
                    conn,
                    """INSERT INTO artifacts(id,sha256,object_key,byte_size,media_type,contract_version,created_at,status)
                       VALUES (:i,:sha,:k,:n,:mt,:cv,:now,'committed')""",
                    {
                        "i": artifact_id,
                        "sha": sha256_hex(output.artifact_bytes),
                        "k": key,
                        "n": len(output.artifact_bytes),
                        "mt": output.media_type,
                        "cv": output.contract_version,
                        "now": utcnow(),
                    },
                )
                tasks.commit_result(
                    conn,
                    claim,
                    input_sha256=claim.input_sha256,
                    artifact_id=artifact_id,
                    coverage=output.coverage,
                    message=output.message or None,
                )
                output.finalize(conn, artifact_id)
        except Conflict as exc:  # 租约已丢/输入不符：整个事务回滚，旧尝试什么都没写进去
            log.warning("job_commit_rejected", job_id=claim.job_id, code=exc.code)
        except (ObjectStoreError, Unavailable):
            self._release(claim, "dependency_unavailable")
        else:
            log.info("job_succeeded", job_id=claim.job_id, kind=claim.kind, attempt=claim.attempt)
            self._advance(claim)

    def _fail(self, claim: Claim, code: str, message: str = "") -> None:
        try:
            with db.transaction(self.ctr.engine) as conn:
                tasks.commit_result(
                    conn, claim, input_sha256=claim.input_sha256, artifact_id=None, error_code=code, error_message=message or None
                )
        except DomainError as exc:
            log.warning("job_fail_rejected", job_id=claim.job_id, code=exc.code)
        else:
            log.warning("job_failed", job_id=claim.job_id, kind=claim.kind, error_code=code, reason=message)
            self._advance(claim)

    def _advance(self, claim: Claim) -> None:
        """任务结束后推进项目的自动评审（独立事务：推进失败不影响已提交的结果，回收器会兜底重试）。"""
        if not self.ctr.settings.auto_analysis or claim.kind not in pipeline.DRIVING_KINDS:
            return
        try:
            with db.transaction(self.ctr.engine) as conn:
                pipeline.advance(conn, self.ctr.store, claim.project_id)
        except Exception:
            log.warning("pipeline_advance_failed", project_id=claim.project_id, exc_info=True)

    def _release(self, claim: Claim, code: str) -> None:
        try:
            with db.transaction(self.ctr.engine) as conn:
                state = tasks.release_for_retry(conn, claim, code)
            log.info("job_released", job_id=claim.job_id, state=state)
        except DomainError as exc:
            log.warning("job_release_rejected", job_id=claim.job_id, code=exc.code)

    def _after_interrupt(self, claim: Claim, keeper: _LeaseKeeper) -> None:
        if keeper.cancelled:
            with db.transaction(self.ctr.engine) as conn:
                tasks.acknowledge_cancel(conn, claim)
            log.info("job_cancelled", job_id=claim.job_id)
        else:
            log.warning("job_lease_lost", job_id=claim.job_id)

    # ---- 主循环
    def run_forever(self, stop: threading.Event) -> None:
        log.info("worker_started", job_class=self.job_class, worker_id=self.ctr.settings.worker_id)
        while not stop.is_set():
            try:
                self.poll_once(1.0)
            except Exception:
                log.error("worker_loop_error", exc_info=True)
                stop.wait(2.0)
        self.consumer.close()
        log.info("worker_stopped", job_class=self.job_class)
