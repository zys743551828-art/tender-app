"""消息端口与 Kafka 适配器。

Kafka 只负责“通知有活干”，任务状态以 PostgreSQL 为准（TECH-001 §7）：消息丢失由回收器重发补偿，
消息重复由领域层的条件领取与 ``processed_messages`` 去重吸收。因此这里的适配器保持很薄：
发送要等确认，消费用手动提交，不做任何业务判断。
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from confluent_kafka import Consumer as KafkaConsumer
from confluent_kafka import KafkaError, KafkaException
from confluent_kafka import Message as KafkaMessage
from confluent_kafka import Producer as KafkaProducer
from confluent_kafka.admin import AdminClient
from confluent_kafka.cimpl import NewTopic

if TYPE_CHECKING:
    from bidwb.config import Settings

TOPIC_PARTITIONS = {"job.parse": 3, "job.ai": 3, "job.experiment": 1, "job.export": 1, "domain.events": 3}
DLQ_SUFFIX = ".dlq"
PRODUCE_TIMEOUT_SECONDS = 10.0
# 单个任务可能运行到租约上限（900 s）；轮询间隔必须大于它，否则消费组会误判成员失联而重平衡。
MAX_POLL_INTERVAL_MS = 30 * 60 * 1000


class PublishError(Exception):
    """发送未得到确认。"""


@dataclass(frozen=True)
class Delivery:
    topic: str
    key: str
    value: bytes
    event_id: str
    handle: Any = None

    def json(self) -> dict[str, Any]:
        loaded = json.loads(self.value)
        if not isinstance(loaded, dict):
            msg = "消息体必须是 JSON 对象"
            raise ValueError(msg)
        return loaded


class Producer(Protocol):
    def send(self, topic: str, key: str, value: bytes, event_id: str) -> None:
        """同步发送，收到 broker 确认才返回；否则抛 ``PublishError``。"""

    def close(self) -> None: ...


class Consumer(Protocol):
    def poll(self, timeout: float) -> Delivery | None: ...
    def commit(self, delivery: Delivery) -> None: ...
    def close(self) -> None: ...


def _client_config(settings: Settings) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "bootstrap.servers": settings.kafka_bootstrap_servers,
        "client.id": settings.kafka_client_id,
        "security.protocol": settings.kafka_security_protocol,
    }
    if settings.kafka_sasl_mechanism:
        cfg["sasl.mechanism"] = settings.kafka_sasl_mechanism
        cfg["sasl.username"] = settings.kafka_sasl_username or ""
        cfg["sasl.password"] = settings.kafka_sasl_password.get_secret_value() if settings.kafka_sasl_password else ""
    return cfg


def prefixed(settings: Settings, topic: str) -> str:
    return f"{settings.kafka_topic_prefix}{topic}"


class KafkaEventProducer:
    """幂等生产者；``flush`` 等待确认，超时即视为失败，由发件箱保留重试。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._producer = KafkaProducer(
            {
                **_client_config(settings),
                "enable.idempotence": True,
                "acks": "all",
                "linger.ms": 5,
                "message.timeout.ms": int(PRODUCE_TIMEOUT_SECONDS * 1000),
            }
        )

    def send(self, topic: str, key: str, value: bytes, event_id: str) -> None:
        outcome: list[KafkaError | None] = []

        def _on_delivery(err: KafkaError | None, _msg: KafkaMessage) -> None:
            outcome.append(err)

        try:
            self._producer.produce(
                prefixed(self._settings, topic),
                key=key.encode(),
                value=value,
                headers=[("event_id", event_id.encode())],
                on_delivery=_on_delivery,
            )
            self._producer.flush(PRODUCE_TIMEOUT_SECONDS)
        except (KafkaException, BufferError) as exc:
            raise PublishError(str(exc)) from exc
        if not outcome or outcome[0] is not None:
            raise PublishError(str(outcome[0]) if outcome else "delivery timeout")

    def close(self) -> None:
        self._producer.flush(PRODUCE_TIMEOUT_SECONDS)


def _as_text(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    return raw if isinstance(raw, str) else raw.decode()


class KafkaEventConsumer:
    """手动提交的消费者：领取任务成功（或确认不必处理）后立即提交位点，长任务期间不再轮询。"""

    def __init__(self, settings: Settings, group_id: str, topics: list[str]) -> None:
        self._consumer = KafkaConsumer(
            {
                **_client_config(settings),
                "group.id": group_id,
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
                "max.poll.interval.ms": MAX_POLL_INTERVAL_MS,
                "partition.assignment.strategy": "cooperative-sticky",
            }
        )
        self._consumer.subscribe([prefixed(settings, t) for t in topics])
        self._prefix = settings.kafka_topic_prefix

    def poll(self, timeout: float) -> Delivery | None:
        msg = self._consumer.poll(timeout)
        if msg is None:
            return None
        if (err := msg.error()) is not None:
            if err.code() == KafkaError._PARTITION_EOF:
                return None
            raise KafkaException(err)
        headers = dict(msg.headers() or [])
        event_id = _as_text(headers.get("event_id"))
        topic = (msg.topic() or "").removeprefix(self._prefix)
        value = msg.value()
        return Delivery(topic, _as_text(msg.key()), value if isinstance(value, bytes) else (value or "").encode(), event_id, handle=msg)

    def commit(self, delivery: Delivery) -> None:
        self._consumer.commit(message=delivery.handle, asynchronous=False)

    def close(self) -> None:
        self._consumer.close()


def ensure_topics(settings: Settings, *, replication_factor: int = 1) -> list[str]:
    """幂等创建业务主题及其死信主题；返回新建的主题名。"""
    admin = AdminClient(_client_config(settings))
    existing = set(admin.list_topics(timeout=10).topics)
    wanted: list[NewTopic] = []
    for topic, partitions in TOPIC_PARTITIONS.items():
        for name, parts in ((prefixed(settings, topic), partitions), (prefixed(settings, topic + DLQ_SUFFIX), 1)):
            if name not in existing:
                wanted.append(NewTopic(name, parts, replication_factor))
    created: list[str] = []
    for name, future in admin.create_topics(wanted).items():
        try:
            future.result()
            created.append(name)
        except KafkaException as exc:
            if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                raise
    return created


class InMemoryBus:
    """测试用总线：同一进程内的生产者/消费者共享队列，语义对齐 Kafka 的“至少一次”。"""

    def __init__(self) -> None:
        self._queues: dict[str, deque[Delivery]] = defaultdict(deque)
        self.sent: list[Delivery] = []
        self.fail_next = 0

    def producer(self) -> Producer:
        return _MemoryProducer(self)

    def redeliver(self, index: int = 0) -> None:
        """把已发送的第 ``index`` 条消息再投递一次，模拟 Kafka 的“至少一次”重复。"""
        delivery = self.sent[index]
        self._queues[delivery.topic].append(delivery)

    def consumer(self, topics: list[str]) -> Consumer:
        return _MemoryConsumer(self, topics)


class _MemoryProducer:
    def __init__(self, bus: InMemoryBus) -> None:
        self._bus = bus

    def send(self, topic: str, key: str, value: bytes, event_id: str) -> None:
        if self._bus.fail_next:
            self._bus.fail_next -= 1
            raise PublishError("simulated broker failure")
        delivery = Delivery(topic, key, value, event_id)
        self._bus.sent.append(delivery)
        self._bus._queues[topic].append(delivery)

    def close(self) -> None:
        return None


class _MemoryConsumer:
    def __init__(self, bus: InMemoryBus, topics: list[str]) -> None:
        self._bus = bus
        self._topics = topics

    def poll(self, timeout: float) -> Delivery | None:
        for topic in self._topics:
            queue = self._bus._queues[topic]
            if queue:
                return queue.popleft()
        return None

    def commit(self, delivery: Delivery) -> None:
        return None

    def close(self) -> None:
        return None
