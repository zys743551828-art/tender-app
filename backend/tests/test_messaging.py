"""Kafka 初始化可在容器重启时重复执行。"""

from unittest.mock import Mock

import pytest

from bidwb import messaging
from bidwb.config import Settings


def test_ensure_topics_when_all_topics_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(kafka_topic_prefix="local-test.")
    topics = {
        messaging.prefixed(settings, name + suffix): Mock() for name in messaging.TOPIC_PARTITIONS for suffix in ("", messaging.DLQ_SUFFIX)
    }
    admin = Mock()
    admin.list_topics.return_value.topics = topics
    monkeypatch.setattr(messaging, "AdminClient", Mock(return_value=admin))

    assert messaging.ensure_topics(settings) == []
    admin.create_topics.assert_not_called()
