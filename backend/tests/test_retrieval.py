from __future__ import annotations

from bidwb.retrieval import rank, tokenize


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
