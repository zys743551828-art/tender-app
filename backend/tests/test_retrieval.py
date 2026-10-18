from __future__ import annotations

import math
from pathlib import Path

import pytest

from bidwb.embeddings import DIMENSIONS, EmbeddingUnavailable, LocalEmbedder, validate_vector
from bidwb.retrieval import Scored, exact_terms, rank, rank_exact, reciprocal_rank_fusion, tokenize


def test_tokenize_cjk_bigrams_and_words() -> None:
    assert tokenize("施工组织") == ["施工", "工组", "组织"]
    assert tokenize("GB 50300-2013 规范") == ["规范", "gb", "50300-2013"]
    assert tokenize("工") == ["工"]
    assert tokenize("") == []


def test_rank_prefers_exact_phrase_and_is_stable() -> None:
    docs = ["本工程安全文明施工措施", "工期不得超过一百八十日历天", "工期不得超过一百八十日历天（复述）", "无关内容"]
    hits = rank("工期 日历天", docs, top_k=5)
    assert [h.index for h in hits] == [1, 2]  # 同分按原顺序
    assert rank("完全不存在的词语", docs, top_k=5) == []


def test_rank_respects_top_k_and_empty_inputs() -> None:
    assert rank("", ["a"], 3) == []
    assert rank("施工", [], 3) == []
    assert len(rank("施工", ["施工方案"] * 5, 2)) == 2
    assert rank("施工", ["施工"], 0) == []
    assert rank("施工", ["施工"], -1) == []


def test_exact_numbers_identifiers_and_units() -> None:
    assert exact_terms("ＧＢ５０３００－２０１３、15.12%、15.12‰") == {"gb50300-2013", "15.12%", "15.12‰"}
    docs = ["15.12%", "115.12%", "15.120%", "15.12‰", "15.12"]
    assert [item.index for item in rank_exact("要求15.12%", docs, 5)] == [0]
    assert [item.index for item in rank_exact("GB50300-2013", ["GB50300-2013", "GB50300-20130"], 5)] == [0]
    assert rank_exact("施工工期", docs, 5) == []


def test_rrf_uses_ranks_and_deduplicates_each_channel() -> None:
    first = [Scored(0, 1000), Scored(0, 1000), Scored(1, 0.1)]
    second = [Scored(1, 0.001), Scored(2, 0.0001)]
    hits = reciprocal_rank_fusion([first, second], 3)
    assert [hit.index for hit in hits] == [1, 0, 2]
    assert math.isclose(hits[0].score, 1 / 62 + 1 / 61)
    assert reciprocal_rank_fusion([], 5) == []
    assert reciprocal_rank_fusion([first], 0) == []
    with pytest.raises(ValueError, match="offset"):
        reciprocal_rank_fusion([first], 5, offset=0)


def test_embedding_rejects_missing_or_replaced_model(tmp_path: Path) -> None:
    with pytest.raises(EmbeddingUnavailable, match="model_missing"):
        LocalEmbedder(tmp_path)
    (tmp_path / "model.onnx").write_bytes(b"replaced")
    with pytest.raises(EmbeddingUnavailable, match="hash_mismatch"):
        LocalEmbedder(tmp_path)


@pytest.mark.parametrize("vector", [[1.0], [float("nan")] * DIMENSIONS, [float("inf")] * DIMENSIONS, [0.0] * DIMENSIONS])
def test_embedding_rejects_invalid_vectors(vector: list[float]) -> None:
    with pytest.raises(EmbeddingUnavailable):
        validate_vector(vector)


def test_embedding_accepts_normalized_vector() -> None:
    validate_vector([1.0] + [0.0] * (DIMENSIONS - 1))


def test_embedding_batches_preserve_lease_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    from bidwb.embeddings import Encoded
    from bidwb.services import vector_index
    from bidwb.workers.handlers import LeaseLost

    class Encoder:
        def encode(self, texts: list[str]) -> Encoded:
            return Encoded([[1.0] + [0.0] * 511 for _ in texts], [False] * len(texts))

    monkeypatch.setattr(vector_index, "get_embedder", lambda _: Encoder())
    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise LeaseLost

    with pytest.raises(LeaseLost):
        vector_index.prepare("local", ["施工"] * 33, checkpoint)
    assert calls == 2
