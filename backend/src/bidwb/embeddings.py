"""固定指纹的本地 BGE ONNX 编码器。运行时不下载模型，也不加载远程代码。"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
DIMENSIONS = 512
MAX_TOKENS = 512
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
MODEL_SHA256 = "99ea2ac0fbba56422236660acb8fa9b5e8bf811bb72b23bf719cebe2413c7e92"
TOKENIZER_SHA256 = "48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26"
_IDENTITY = {
    "model": MODEL_NAME,
    "onnx": MODEL_SHA256,
    "tokenizer": TOKENIZER_SHA256,
    "dimensions": DIMENSIONS,
    "max_tokens": MAX_TOKENS,
    "query_prefix": QUERY_PREFIX,
    "pooling": "CLS",
    "normalize": True,
}
MODEL_FINGERPRINT = hashlib.sha256(json.dumps(_IDENTITY, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class EmbeddingUnavailable(RuntimeError):
    """编码不可用；调用方应保留关键词结果，向用户说明缺口。"""


@dataclass(frozen=True)
class Encoded:
    vectors: list[list[float]]
    truncated: list[bool]
    model_fingerprint: str = MODEL_FINGERPRINT


def validate_vector(vector: Sequence[float]) -> None:
    """拒绝非有限数、错维度和非单位向量，避免坏索引参与余弦检索。"""
    if len(vector) != DIMENSIONS or not all(math.isfinite(value) for value in vector):
        raise EmbeddingUnavailable("embedding_invalid_vector")
    if not math.isclose(sum(value * value for value in vector), 1.0, abs_tol=0.002):
        raise EmbeddingUnavailable("embedding_not_normalized")


def _verified_file(root: Path, name: str, expected: str) -> Path:
    path = root / name
    try:
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as exc:
        raise EmbeddingUnavailable("embedding_model_missing") from exc
    if actual != expected:
        raise EmbeddingUnavailable("embedding_model_hash_mismatch")
    return path


class LocalEmbedder:
    """CPU 编码；每批至多 32 条，分词器状态在锁内访问，可供 API 多线程共享。"""

    def __init__(self, root: Path) -> None:
        model_path = _verified_file(root, "model.onnx", MODEL_SHA256)
        tokenizer_path = _verified_file(root, "tokenizer.json", TOKENIZER_SHA256)
        try:
            import onnxruntime as ort  # noqa: PLC0415
            from tokenizers import Tokenizer  # noqa: PLC0415

            ort.disable_telemetry_events()
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            self._session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
            self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
            self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")  # noqa: S106  BERT 填充符
            self._tokenizer.enable_truncation(max_length=MAX_TOKENS)
        except Exception as exc:
            raise EmbeddingUnavailable("embedding_initialization_failed") from exc
        self._lock = threading.Lock()

    def encode(self, texts: Sequence[str], *, query: bool = False) -> Encoded:
        if not texts:
            return Encoded([], [])
        if any(not text.strip() for text in texts):
            raise ValueError("embedding_empty_input")
        vectors: list[list[float]] = []
        truncated: list[bool] = []
        try:
            import numpy as np  # noqa: PLC0415

            for start in range(0, len(texts), 32):
                batch = [(QUERY_PREFIX if query else "") + text for text in texts[start : start + 32]]
                with self._lock:
                    tokens = self._tokenizer.encode_batch(batch)
                inputs: dict[str, Any] = {
                    "input_ids": np.asarray([token.ids for token in tokens], dtype=np.int64),
                    "attention_mask": np.asarray([token.attention_mask for token in tokens], dtype=np.int64),
                    "token_type_ids": np.asarray([token.type_ids for token in tokens], dtype=np.int64),
                }
                output = self._session.run(["embeddings"], inputs)[0]
                if output.shape != (len(batch), DIMENSIONS):
                    raise EmbeddingUnavailable("embedding_invalid_shape")
                for vector in output.tolist():
                    validate_vector(vector)
                    vectors.append(vector)
                truncated.extend(bool(token.overflowing) for token in tokens)
        except EmbeddingUnavailable:
            raise
        except Exception as exc:
            raise EmbeddingUnavailable("embedding_inference_failed") from exc
        return Encoded(vectors, truncated)


@lru_cache(maxsize=1)
def get_embedder(model_dir: str) -> LocalEmbedder:
    return LocalEmbedder(Path(model_dir))
