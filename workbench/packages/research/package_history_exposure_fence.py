"""Bounded legacy object read under the same exposure fence, without a DB transaction.

The dedicated research Worker runs on its main thread. A session advisory lock
survives each metadata commit and prevents final exposure while original object
bytes are being read. Closing the dedicated connection releases the lock on
success, error, cancellation or the total read deadline. No provider is invoked.
"""

import signal
import threading
from contextlib import contextmanager

from packages.domain.runtime import DomainError
from packages.research.ledger import lock_run_scope, research_connection

READ_SECONDS = 45


class _ReadDeadline(BaseException):
    """Cannot be swallowed by an object adapter's ordinary Exception retry handler."""


def _expired(signum, frame):
    raise _ReadDeadline


def _renew_owned_read(c, message, lease):
    changed = c.execute(
        "UPDATE design.step_receipts s SET heartbeat_at=clock_timestamp(),lease_until=clock_timestamp()+interval '120 seconds' "
        "WHERE operation_id=%s AND step_key=%s AND input_digest=%s AND fence=%s AND owner_token=%s "
        "AND state='running' AND lease_until>clock_timestamp() "
        "AND EXISTS(SELECT FROM design.operations o JOIN design.operation_steps p ON p.operation_id=o.id "
        "JOIN design.research_run_attempts a ON a.operation_id=o.id JOIN design.research_runs r ON r.id=a.run_id "
        "WHERE o.id=s.operation_id AND o.bid_id=%s AND o.state='running' AND o.cancel_requested_at IS NULL "
        "AND p.step_key=s.step_key AND p.input_digest=s.input_digest AND p.dispatch_generation=%s "
        "AND a.run_id=%s AND a.sample_id=%s AND r.state='running' AND r.cancel_requested_at IS NULL)",
        (
            message["operation_id"],
            message["step_key"],
            message["input_digest"],
            lease["fence"],
            lease["owner"],
            message["bid_id"],
            message["generation"],
            lease["run_id"],
            lease["sample_id"],
        ),
    ).rowcount
    if changed != 1:
        raise DomainError(
            "RESEARCH_EXECUTION_STALE", "读取原件前执行租约或任务状态已失效，未读取对象", 409
        )


@contextmanager
def source_read_fence(message, lease):
    # Do not replace another caller's alarm or pretend that an unsupported
    # threaded/platform runtime provides the same bounded cancellation guarantee.
    if (
        threading.current_thread() is not threading.main_thread()
        or not hasattr(signal, "SIGALRM")
        or not hasattr(signal, "setitimer")
        or signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0)
        or type(READ_SECONDS) is not int
        or not 1 <= READ_SECONDS <= 45
    ):
        raise DomainError(
            "RESEARCH_READ_FENCE_RUNTIME_UNAVAILABLE",
            "研究原件读取须使用支持有界取消的独立主线程进程",
            503,
        )
    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _expired)
    signal.setitimer(signal.ITIMER_REAL, READ_SECONDS)
    try:
        with research_connection() as c:
            # research_connection has already acquired the transaction form of
            # this key. Session acquisition is reentrant on this same connection.
            c.execute("SELECT pg_advisory_lock(91143,1)")
            try:
                # The legacy connection uses SET LOCAL. This dedicated session
                # crosses metadata commits, so fix its path for its whole life.
                c.execute("SET SESSION search_path=pg_catalog,design,pg_temp")
                lock_run_scope(c, lease["run_id"])
                _renew_owned_read(c, message, lease)
                c.commit()
                # The refreshed 120s lease outlasts the whole <=45s scope. A
                # separate heartbeat may wait on this fence but cannot expire it.
                yield c
            finally:
                # No explicit unlock/commit sequence can leave a session lock
                # behind if a transaction is aborted or cancellation interrupts.
                c.close()
    except _ReadDeadline:
        raise DomainError(
            "RESEARCH_SOURCE_READ_TIMEOUT",
            "完整原件读取超过总时限，已释放曝光栅栏；未发送模型请求",
            409,
        ) from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
