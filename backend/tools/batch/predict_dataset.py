"""系统批量预测：对评分配对集（交接格式 A）里的每份样本，用产品本身的流水线跑一遍评审与评分预测，输出交接格式 B。

运行方式（在 backend 目录）::

    python -m tools.batch.predict_dataset <评分配对集.json> --out <输出目录> [--admin-dsn …] [--cache-dir …]

进程内运行完整产品链路：独立新建的 PostgreSQL 库（Alembic 迁移、worker 用只有 ``app_worker`` 权限的角色）、
真实 API（上传、流水线状态、规则、响应矩阵、报告）、内存对象存储、内存总线上的发件箱中继与回收器、parse/ai worker。
模型取 ``BIDWB_LLM_*`` 配置（OpenAI 兼容接口），外面包一层磁盘缓存。

只上传招标文件与补遗（按发布顺序）和技术标正文；成绩来源文件从不读取、从不上传；项目不设截止时间。
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND / "src") not in sys.path:
    sys.path.insert(0, str(BACKEND / "src"))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from bidwb import db, parsing  # noqa: E402
from bidwb.ai import anchors, predict, prompts  # noqa: E402
from bidwb.ai.handlers import RULES_BATCH, build_handlers  # noqa: E402
from bidwb.ai.llm import LlmClient, LlmResult, Usage, build_llm  # noqa: E402
from bidwb.ai.sections import build_sections  # noqa: E402
from bidwb.api.app import create_app  # noqa: E402
from bidwb.checks import Passage  # noqa: E402
from bidwb.config import Settings  # noqa: E402
from bidwb.messaging import InMemoryBus  # noqa: E402
from bidwb.runtime import Container  # noqa: E402
from bidwb.ai.anchors import Anchor, AnchorPack, LoadedPack, parse_pack  # noqa: E402
from bidwb.services import auth as auth_service  # noqa: E402
from bidwb.services import score_pairs  # noqa: E402
from bidwb.storage import MemoryObjectStore, ObjectInfo, content_key  # noqa: E402
from bidwb.workers.handlers import Handler, HandlerFailure, HandlerOutput, JobContext  # noqa: E402
from bidwb.workers.loops import reap_forever, relay_forever  # noqa: E402
from bidwb.workers.runner import WorkerRunner  # noqa: E402

SCHEMA_IN = "score-pairs/1"
SCHEMA_OUT = "system-prediction/1"
DEFAULT_ADMIN_DSN = "postgresql+psycopg://postgres@127.0.0.1:5432/postgres"
TOOL_LOGIN = "batch"
TOOL_PASSWORD = "batch-runner-" + "x" * 8
ROLE_BY_KIND = {"tender": "tender", "addendum": "supplement"}  # 格式 A 的 role → 产品的资料用途
SKIP_EXCLUSIONS = frozenset({"duplicate_body", "missing_files"})  # 默认不跑：重复正文不是独立样本；缺文件跑不了
ITEM_KEYS = score_pairs.ITEM_KEYS


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    """先写临时文件再改名：中断不会留下半截的结果文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def code_sha256() -> str:
    """产品代码（src/bidwb 下全部 .py）与本工具的摘要：任何一处改动都会让旧结果的指纹失效。"""
    digest = hashlib.sha256()
    files = [*sorted((BACKEND / "src" / "bidwb").rglob("*.py")), Path(__file__).resolve()]
    for path in files:
        digest.update(str(path.relative_to(BACKEND)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


# ------------------------------------------------------------------ 交接格式 A
@dataclass(frozen=True)
class FileRef:
    file_id: str | None
    path: Path
    declared_sha256: str | None
    role: str  # 产品的资料用途：tender / supplement / body


@dataclass
class Sample:
    sample_id: str
    raw: dict[str, Any]
    tender: list[FileRef]
    body: FileRef | None
    eligible: bool
    exclusion: str | None
    shas: dict[Path, str] = field(default_factory=dict)

    def files(self) -> list[FileRef]:
        return [*self.tender, *([self.body] if self.body else [])]

    def resolve_shas(self) -> None:
        """算出每个文件的实际 SHA-256，与格式 A 声明的不一致即报错（文件被替换过）。"""
        for ref in self.files():
            if ref.path in self.shas:
                continue
            if not ref.path.is_file():
                msg = f"missing_file: {ref.path}"
                raise SampleError(msg)
            actual = _sha256_file(ref.path)
            if ref.declared_sha256 and ref.declared_sha256.lower() != actual:
                msg = f"sha256_mismatch: {ref.path}"
                raise SampleError(msg)
            self.shas[ref.path] = actual

    def tender_shas(self) -> list[str]:
        return [self.shas[r.path] for r in self.tender]

    def body_sha(self) -> str | None:
        return self.shas[self.body.path] if self.body else None


class SampleError(Exception):
    """单个样本的确定性失败（缺文件、校验值不符、超时、流水线失败）；记录后继续下一份。"""


def load_dataset(path: Path, datasets_root: Path | None = None) -> list[Sample]:
    """读取格式 A。``datasets_root`` 为相对路径时相对于该 JSON 文件所在目录；样本内的文件路径相对于 ``datasets_root``（绝对路径原样使用）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA_IN:
        msg = f"不是 {SCHEMA_IN} 文件：schema={data.get('schema')!r}"
        raise ValueError(msg)
    root = datasets_root or Path(data.get("datasets_root") or ".")
    if not root.is_absolute():
        root = (path.parent / root).resolve()

    def ref(item: dict[str, Any], role: str) -> FileRef:
        p = Path(item["path"])
        return FileRef(item.get("file_id"), p if p.is_absolute() else root / p, item.get("sha256"), role)

    samples: list[Sample] = []
    for raw in data.get("samples", []):
        tender = []
        for item in raw.get("tender_files") or []:
            kind = item.get("role") or "tender"
            if kind not in ROLE_BY_KIND:
                msg = f"{raw.get('sample_id')}: 招标资料 role 只能是 tender 或 addendum，实际 {kind!r}"
                raise ValueError(msg)
            tender.append(ref(item, ROLE_BY_KIND[kind]))
        body = ref(raw["body_file"], "body") if raw.get("body_file") else None
        samples.append(
            Sample(
                sample_id=str(raw["sample_id"]),
                raw=raw,
                tender=tender,
                body=body,
                eligible=bool(raw.get("eligible", True)),
                exclusion=raw.get("exclusion"),
            )
        )
    return samples


def fingerprint(
    sample: Sample, model: str, prompt_version: str, code_sha: str, anchor_pack: str | None = None, repeat_index: int = 0
) -> str:
    """输入指纹：招标与正文 SHA（招标按发布顺序）、模型、提示词版本、代码摘要、锚点包（给了 ``--anchor-pack`` 时）、运行序号。"""
    payload = {
        "anchor_pack": anchor_pack,
        "repeat_index": repeat_index,
        "tender_sha256": sample.tender_shas(),
        "body_sha256": sample.body_sha(),
        "model": model,
        "prompt_version": prompt_version,
        "code_sha256": code_sha,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ------------------------------------------------------------------ 模型磁盘缓存
_ID = re.compile(r"\b[a-z][a-z0-9]{1,15}_[0-9a-f]{16}\b")  # util.new_id 生成的标识
_PLACEHOLDER = re.compile(r"@ID(\d+)@")
_CURRENT = threading.local()  # 当前 worker 线程正在执行的任务属于哪个项目：用于把调用量记到样本上


@dataclass
class CallStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    cache_hits: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


class CachedLlm:
    """磁盘缓存包装：键为 sha256(model, system, user, max_tokens, temperature, 运行序号[, 重复序号])，命中直接返回，不付费。

    温度大于 0 的调用是有意的重复抽样（评分预测每条款判断多次），内容完全相同；键里另含它在本次任务执行中的重复序号
    （同一任务里第几次发出这条调用），使第 2、3 次各有自己的缓存条目，重跑时按同样的顺序命中。

    提示词里的证据、规则等标识每个项目随机生成（同一份招标文件在两个项目里的证据 ID 不同，重跑时也不同），
    因此计算键之前按出现顺序把这类标识换成占位符 ``@IDn@``；存盘的回复同样换成占位符，命中时再换回本次的标识。
    这样同一招标文件被多家样本复用、或中断后重跑时，内容相同的调用只付一次费。
    命中返回零用量（产物里的 usage 只记真实付费）。
    """

    def __init__(self, inner: LlmClient, cache_dir: Path | None, namespace: int = 0) -> None:
        self.inner = inner
        self.namespace = namespace  # 重复运行序号（--repeat-index）：不同序号互不命中，用于测量整条流水线的稳定性
        self.model = inner.model
        self.cache_dir = cache_dir
        self._lock = threading.Lock()
        self.total = CallStats()
        self.by_project: dict[str, CallStats] = {}

    def _record(self, hit: bool, usage: Usage | None) -> None:
        project = getattr(_CURRENT, "project", None)
        with self._lock:
            targets = [self.total]
            if project is not None:
                targets.append(self.by_project.setdefault(project, CallStats()))
            for s in targets:
                if hit:
                    s.cache_hits += 1
                elif usage is not None:
                    s.prompt_tokens += usage.prompt_tokens
                    s.completion_tokens += usage.completion_tokens
                    s.calls += usage.calls

    def stats_for(self, project_id: str) -> CallStats:
        with self._lock:
            return CallStats(**self.by_project.get(project_id, CallStats()).as_dict())

    def complete(self, *, system: str, user: str, max_tokens: int = 4096, temperature: float = 0.0) -> LlmResult:
        mapping: dict[str, int] = {}

        def canon(m: re.Match[str]) -> str:
            return f"@ID{mapping.setdefault(m.group(0), len(mapping) + 1)}@"

        canon_system = _ID.sub(canon, system)
        canon_user = _ID.sub(canon, user)
        parts: list[Any] = [self.model, canon_system, canon_user, max_tokens, temperature, self.namespace]
        if temperature > 0:
            seen: dict[str, int] = getattr(_CURRENT, "repeats", None) or {}
            base = hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()
            seen[base] = seen.get(base, 0) + 1
            _CURRENT.repeats = seen
            parts.append(seen[base])
        key = hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()
        path = self.cache_dir / key[:2] / f"{key}.json" if self.cache_dir else None
        if path is not None and path.is_file():
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
                reverse = {n: ident for ident, n in mapping.items()}
                restored = _PLACEHOLDER.sub(lambda m: reverse.get(int(m.group(1)), m.group(0)), entry["text"])
            except (OSError, ValueError, KeyError):
                restored = None
            if restored is not None:
                self._record(True, None)
                return LlmResult(restored, Usage(0, 0, 0))
        result = self.inner.complete(system=system, user=user, max_tokens=max_tokens, temperature=temperature)
        self._record(False, result.usage)
        if path is not None:
            stored = _ID.sub(lambda m: f"@ID{mapping[m.group(0)]}@" if m.group(0) in mapping else m.group(0), result.text)
            _write_json(
                path,
                {
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "text": stored,
                    "usage": result.usage.__dict__,
                    "created_at": _now(),
                },
            )
        return result


def _attributed(handlers: dict[str, Handler]) -> dict[str, Handler]:
    """处理器在 worker 线程里同步执行：执行期间记下任务所属项目（模型调用量据此归到样本）与重复抽样的计数。"""

    def wrap(handler: Handler) -> Handler:
        def run(ctx: JobContext) -> HandlerOutput | HandlerFailure:
            _CURRENT.project = ctx.claim.project_id
            _CURRENT.repeats = {}  # 重复抽样的序号按每次任务执行重新计数
            try:
                return handler(ctx)
            finally:
                _CURRENT.project = None
                _CURRENT.repeats = None

        return run

    return {kind: wrap(h) for kind, h in handlers.items()}


def leaks(anchor: Anchor, template_group: str | None, project_key: str | None) -> bool:
    """锚点与样本同源：同一模板组，或同一项目（招标编号＋标段）。"""
    return (template_group is not None and anchor.group_id == template_group) or (
        project_key is not None and anchor.project_key == project_key
    )


# ------------------------------------------------------------------ 进程内运行环境
class LockedMemoryStore(MemoryObjectStore):
    """多个样本并发上传时，内存存储的分片会话计数与字典更新需要串行。"""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.RLock()

    def create_multipart(self, key: str, content_type: str) -> str:
        with self._lock:
            return super().create_multipart(key, content_type)

    def put_part(self, upload_id: str, part_number: int, data: bytes) -> str:
        with self._lock:
            return super().put_part(upload_id, part_number, data)

    def complete_multipart(self, key: str, upload_id: str, parts: Sequence[tuple[int, str]]) -> None:
        with self._lock:
            super().complete_multipart(key, upload_id, parts)

    def abort_multipart(self, key: str, upload_id: str) -> None:
        with self._lock:
            super().abort_multipart(key, upload_id)

    def head(self, key: str) -> ObjectInfo | None:
        with self._lock:
            return super().head(key)

    def copy_if_absent(self, source: str, destination: str) -> bool:
        with self._lock:
            return super().copy_if_absent(source, destination)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        with self._lock:
            super().put(key, data, content_type)

    def delete(self, key: str) -> None:
        with self._lock:
            super().delete(key)

    def bytes_held(self) -> int:
        with self._lock:
            return sum(len(v) for v in self.objects.values())


class Runtime:
    """一次批量运行的进程内产品环境；``close`` 时停止后台线程并删除临时库（``keep_db`` 时保留）。"""

    WORKER_ROLE = "bidwb_batch_worker"

    def __init__(
        self, admin_dsn: str, llm: CachedLlm, *, concurrency: int, keep_db: bool, log_level: str, anchor_pack: AnchorPack | None = None
    ) -> None:
        self.keep_db = keep_db
        self.anchor_pack = anchor_pack
        self._samples: dict[str, tuple[str | None, str | None, str | None]] = {}  # 项目 ID → （模板组, 项目键, 评标办法）
        self.admin = create_engine(admin_dsn, isolation_level="AUTOCOMMIT")
        self.db_name = f"bidwb_batch_{uuid.uuid4().hex[:8]}"
        with self.admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{self.db_name}"'))
        self.url = make_url(admin_dsn).set(database=self.db_name).render_as_string(hide_password=False)
        done = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env={**os.environ, "BIDWB_MIGRATION_DATABASE_URL": self.url},
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            self._drop()
            msg = f"迁移失败：{done.stderr[-2000:]}"
            raise RuntimeError(msg)
        self.owner = create_engine(self.url, isolation_level="AUTOCOMMIT", pool_size=2, max_overflow=4)
        password = uuid.uuid4().hex
        with self.owner.connect() as conn:  # 受限 worker 角色：证明批量运行只用到产品 worker 被授予的权限
            conn.execute(
                text(
                    f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{self.WORKER_ROLE}') "
                    f"THEN CREATE ROLE {self.WORKER_ROLE} LOGIN IN ROLE app_worker; END IF; END $$"
                )
            )
            conn.execute(text(f"ALTER ROLE {self.WORKER_ROLE} PASSWORD '{password}'"))
        worker_url = make_url(self.url).set(username=self.WORKER_ROLE, password=password).render_as_string(hide_password=False)
        self.settings = Settings(
            environment="development",
            cookie_secure=False,
            session_cookie_name="sid",
            login_rate_limit_per_minute=100000,
            auto_analysis=True,
            relay_poll_seconds=0.2,
            reaper_interval_seconds=10,
            log_level=log_level,
        )
        self.store = LockedMemoryStore()
        self.api_engine = db.make_engine(self.url, pool_size=2 * concurrency + 4, application_name="bidwb-batch-api")
        self.worker_engine = db.make_engine(worker_url, pool_size=3 * concurrency + 6, application_name="bidwb-batch-worker")
        api_ctr = Container(self.settings, self.api_engine, self.store)
        self.worker_ctr = Container(self.settings, self.worker_engine, self.store)
        with db.transaction(self.api_engine) as conn:
            auth_service.create_local_member(conn, login=TOOL_LOGIN, display_name="批量预测", password=TOOL_PASSWORD)
        self.app = create_app(self.settings, api_ctr)
        self.bus = InMemoryBus()
        handlers = _attributed(build_handlers(llm, anchor_source=self._anchors if anchor_pack is not None else None))
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []
        # pdfium 不是线程安全的（同一进程里并发解析会崩溃），解析只开一个线程；模型调用按样本并发数开线程
        for job_class, n in (("parse", 1), ("ai", concurrency)):
            for i in range(n):
                runner = WorkerRunner(
                    self.worker_ctr, job_class, self.bus.consumer([f"job.{job_class}"]), handlers, consumer_name=f"batch-{job_class}"
                )
                self._spawn(f"{job_class}-{i}", functools.partial(self._work, runner))
        self._spawn("relay", lambda: relay_forever(self.worker_ctr, self.bus.producer(), self.stop))
        self._spawn("reaper", lambda: reap_forever(self.worker_ctr, self.stop))
        self._content_lock = threading.Lock()
        self._in_flight: dict[str, set[str]] = {}

    def bind_sample(self, project_id: str, sample: Sample) -> None:
        with self._content_lock:
            self._samples[project_id] = (sample.raw.get("template_group"), sample.raw.get("project_key"), sample.raw.get("scoring_scheme"))

    def _anchors(self, _conn: Any, _store: Any, project_id: str) -> LoadedPack | None:
        """直接使用 ``--anchor-pack`` 给出的锚点包（不经路由）；与本样本同一模板组或同一项目（project_key）的锚点一律不用，
        避免同源泄漏（与本样本正文相同的锚点由选锚点时按正文 SHA 排除）。"""
        pack = self.anchor_pack
        if pack is None:
            return None
        with self._content_lock:
            group, key, scheme = self._samples.get(project_id, (None, None, None))
        usable = tuple(a for a in pack.anchors if not leaks(a, group, key))
        return LoadedPack(pack.pack_id, "file", usable, scoring_scheme=scheme)

    def _spawn(self, name: str, target: Callable[[], None]) -> None:
        thread = threading.Thread(target=target, name=f"batch-{name}", daemon=True)
        thread.start()
        self.threads.append(thread)

    def _work(self, runner: WorkerRunner) -> None:
        """内存总线的 poll 不阻塞：没有消息时短暂休眠，避免空转。"""
        while not self.stop.is_set():
            try:
                if not runner.poll_once(0):
                    self.stop.wait(0.2)
            except Exception as exc:
                print(f"worker 循环异常：{exc!r}", file=sys.stderr, flush=True)
                self.stop.wait(1.0)

    # ---- 内存回收
    def claim_contents(self, sample_id: str, shas: Iterable[str]) -> None:
        """登记样本将上传的内容；必须在上传之前调用，回收时据此判断内容寻址对象是否仍被在途样本使用。"""
        with self._content_lock:
            self._in_flight[sample_id] = set(shas)

    def release_project(self, sample_id: str, project_id: str | None) -> None:
        """删除该项目在内存存储里的全部对象：资料原件（没有其他在途样本使用时）与各任务产物。"""
        with self._content_lock:
            mine = self._in_flight.pop(sample_id, set())
            shared = set().union(*self._in_flight.values()) if self._in_flight else set()
            keys: set[str] = {content_key(s) for s in mine - shared}
            if project_id is not None:
                keys |= self._project_object_keys(project_id, shared)
            for key in keys:
                self.store.delete(key)
        self.bus.sent.clear()  # 内存总线保留的已发送记录只用于测试重放，批量运行时不需要

    def _project_object_keys(self, project_id: str, shared: set[str]) -> set[str]:
        """项目引用的全部产物键：按库结构找出所有带 project_id 的表里名为 *artifact_id 的列。"""
        keys: set[str] = set()
        with self.owner.connect() as conn:
            cols = db.all_(
                conn,
                """SELECT c.table_name, c.column_name FROM information_schema.columns c
                   WHERE c.table_schema='public' AND c.column_name LIKE '%artifact_id'
                     AND EXISTS (SELECT 1 FROM information_schema.columns p WHERE p.table_schema='public'
                                 AND p.table_name=c.table_name AND p.column_name='project_id')""",
            )
            for col in cols:
                rows = db.all_(
                    conn,
                    f'SELECT a.object_key, a.sha256 FROM artifacts a JOIN "{col["table_name"]}" t ON a.id=t."{col["column_name"]}" '
                    "WHERE t.project_id=:p",
                    {"p": project_id},
                )
                keys |= {r["object_key"] for r in rows if not (r["object_key"].startswith("objects/") and r["sha256"] in shared)}
        return keys

    def close(self) -> None:
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=10)
        self.api_engine.dispose()
        self.worker_engine.dispose()
        self.owner.dispose()
        if not self.keep_db:
            self._drop()
        self.admin.dispose()

    def _drop(self) -> None:
        with self.admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{self.db_name}" WITH (FORCE)'))


class Api:
    """每个样本一个客户端：像浏览器一样带会话 cookie、CSRF 令牌与幂等键。"""

    def __init__(self, app: Any) -> None:
        self.http = TestClient(app, base_url="http://batch")
        r = self.http.post("/api/v1/auth/login", json={"username": TOOL_LOGIN, "password": TOOL_PASSWORD})
        r.raise_for_status()
        self.csrf = r.json()["csrf_token"]

    def get(self, path: str) -> Any:
        r = self.http.get("/api/v1" + path)
        if r.status_code != 200:
            msg = f"GET {path} → {r.status_code} {r.text[:300]}"
            raise SampleError(msg)
        return r.json()

    def post(self, path: str, body: object, *, ok: Sequence[int] = (200, 201, 202)) -> Any:
        headers = {"X-CSRF-Token": self.csrf, "Idempotency-Key": f"batch-{uuid.uuid4().hex}"}
        r = self.http.post("/api/v1" + path, json=body, headers=headers)
        if r.status_code not in ok:
            msg = f"POST {path} → {r.status_code} {r.text[:300]}"
            raise SampleError(msg)
        return r.json()


def upload(api: Api, store: MemoryObjectStore, project_id: str, data: bytes, *, name: str, role: str) -> dict[str, Any]:
    """走真实上传接口：申请分片会话 → 通过同源接口写分片（内存存储适配器） → 完成并由服务端复算校验值。"""
    sha = hashlib.sha256(data).hexdigest()
    session = api.post(
        f"/projects/{project_id}/uploads",
        {"original_name": name, "role": role, "byte_size": len(data), "sha256": sha, "media_type": "application/pdf"},
    )
    size = session["part_bytes"]
    parts = []
    for part in session["parts"]:
        n = part["part_number"]
        response = api.http.put(part["url"], content=data[(n - 1) * size : n * size], headers={"X-CSRF-Token": api.csrf})
        if response.status_code != 200:
            raise SampleError(f"分片上传失败：HTTP {response.status_code}")
        parts.append({"part_number": n, "etag": response.headers["ETag"]})
    return dict(api.post(f"/uploads/{session['upload_id']}/complete", {"sha256": sha, "parts": parts}))


# ------------------------------------------------------------------ 单个样本
@dataclass
class Options:
    dataset: Path
    out: Path
    admin_dsn: str = DEFAULT_ADMIN_DSN
    datasets_root: Path | None = None
    cache_dir: Path | None = None
    only: list[str] = field(default_factory=list)
    limit: int | None = None
    concurrency: int = 2
    sample_timeout: float = 30 * 60
    poll_seconds: float = 2.0
    include_excluded: bool = False
    skip_failed: bool = False
    keep_db: bool = False
    log_level: str = "WARNING"
    estimate_only: bool = False
    price_in: float | None = None
    price_out: float | None = None
    anchor_pack: Path | None = None
    repeat_index: int = 0


def _project_body(sample: Sample) -> dict[str, Any]:
    raw = sample.raw
    key = str(raw.get("project_key") or "")
    number, _, lot = key.partition("|")
    title = f"{sample.sample_id} {raw.get('bidder') or ''}".strip()
    return {
        "title": title[:200],
        "tender_number": number or None,
        "lot": lot or None,
        "round": 1,
        "region": raw.get("region"),
        "engineering_type": raw.get("engineering_type"),
        "deadline": None,
    }


def _wait(api: Api, project_id: str, deadline: float, poll: float) -> dict[str, Any]:
    """轮询流水线直到终态：某环节失败；或评审完成且评分预测已结束（成功或失败）。"""
    while True:
        status = api.get(f"/projects/{project_id}/pipeline")
        steps = {s["key"]: s for s in status["steps"]}
        if status["stage"] == "failed":
            return dict(status)
        if status["stage"] == "done" and steps["prediction"]["state"] in {"done", "failed"}:
            return dict(status)
        if time.monotonic() > deadline:
            msg = f"timeout: 流水线停在 {status['stage']}（" + "，".join(f"{k}={s['state']}" for k, s in steps.items()) + "）"
            raise SampleError(msg)
        time.sleep(poll)


def _cancel_active(api: Api, project_id: str) -> None:
    for task in api.get(f"/projects/{project_id}/tasks"):
        if task["state"] in {"queued", "running", "waiting_input"}:
            with contextlib.suppress(SampleError):
                api.post(f"/tasks/{task['task_id']}/cancel", {})


def _failure_reason(api: Api, project_id: str, status: dict[str, Any]) -> str | None:
    parts = [f"{s['key']}: {s['message'] or 'failed'}" for s in status["steps"] if s["state"] == "failed"]
    for task in api.get(f"/projects/{project_id}/tasks"):
        if task["state"] == "failed":
            parts.append(f"task {task['kind']} {task['error_code']}" + (f"：{task['message']}" if task.get("message") else ""))
    return "；".join(parts) or None


def _collect(rt: Runtime, api: Api, project_id: str, body_version_id: str, record: dict[str, Any]) -> None:
    """读取规则、响应矩阵、问题分类、预测与明细、正文页数与字数；评审没完成的部分保持为空。"""
    rules = api.get(f"/projects/{project_id}/rules")["rules"] if _has_rules(api, project_id) else []
    kinds = [r["kind"] for r in rules]
    record["rules"] = {
        "disqualification": kinds.count("disqualification"),
        "mandatory": kinds.count("mandatory"),
        "scoring": kinds.count("scoring"),
        "with_points": sum(1 for r in rules if r["kind"] == "scoring" and r["max_points"] is not None),
        "total": len(rules),
    }
    with rt.owner.connect() as conn:
        parse = db.one(
            conn,
            """SELECT ps.page_count, a.object_key FROM parses ps LEFT JOIN artifacts a ON a.id=ps.artifact_id
               WHERE ps.file_version_id=:v ORDER BY ps.created_at DESC, ps.id DESC LIMIT 1""",
            {"v": body_version_id},
        )
    if parse is not None:
        chars = None
        if parse["object_key"]:
            summary = json.loads(rt.store.get(parse["object_key"]))
            chars = sum(summary.get("page_text_chars") or [])
        record["body"] = {"pages": parse["page_count"], "chars": chars}
    r = api.http.get(f"/api/v1/projects/{project_id}/report")
    if r.status_code != 200:
        return
    report = r.json()
    q = report["qualification"]
    record["compliance"] = {
        "qualification_total": q["qualification"]["total"],
        "satisfied": q["qualification"]["satisfied"],
        "violated": q["qualification"]["violated"],
        "unclear": q["qualification"]["unclear"],
        "failed": q["qualification"]["failed"],
        "coverage": (q.get("coverage") or {}).get("status"),
        "scoring": q["scoring"],
    }
    by = {c["category"]: c["total"] for c in report["categories"]}
    record["findings"] = {k: by.get(k, 0) for k in ("disqualification", "response", "consistency", "scope", "improvement")}
    pred = api.get(f"/projects/{project_id}/prediction?snapshot_id={report['snapshot_id']}")
    if not pred:
        return
    record["technical_full_score"] = pred.get("technical_full_score")
    record["prediction"] = {
        "status": pred["status"],
        "estimate": pred.get("estimated_value"),
        "low": pred.get("low"),
        "high": pred.get("high"),
        "maximum": pred.get("maximum"),
    }
    with rt.owner.connect() as conn:
        key = db.scalar(
            conn,
            "SELECT a.object_key FROM predictions p JOIN artifacts a ON a.id=p.detail_artifact_id WHERE p.id=:i",
            {"i": pred["prediction_id"]},
        )
    if key:
        detail = json.loads(rt.store.get(key))
        record["items"] = score_pairs.format_b_items(detail)
        record["artifact_extra"] = score_pairs.jsonable({k: v for k, v in detail.items() if k not in {"items", "usage"}})


def _has_rules(api: Api, project_id: str) -> bool:
    return bool(api.http.get(f"/api/v1/projects/{project_id}/rules").status_code == 200)


_INPUT_ERRORS = ("missing_file", "sha256_mismatch", "parse_unreadable", "parse_unsupported", "body_has_no_evidence", "no_evidence")
_INFRASTRUCTURE_ERRORS = ("timeout", "tool_error", "worker_error", "llm_not_configured", "unavailable", "provider_", "lease", "GET ", "POST ")


def failure_kind(error: str | None) -> str | None:
    """失败归类：input＝资料缺失或读不出；infrastructure＝超时、数据库、模型服务不可用、工具自身异常；
    model＝模型输出不可用或流水线因内容失败（如没提取出规则、没有评分预测）。"""
    if error is None:
        return None
    if any(code in error for code in _INPUT_ERRORS):
        return "input"
    if any(code in error for code in _INFRASTRUCTURE_ERRORS):
        return "infrastructure"
    return "model"


def empty_record(
    sample_id: str, model: str, code_sha: str, fp: str | None, error: str | None = None, *, run_id: str = "", repeat_index: int = 0
) -> dict[str, Any]:
    """格式 B 的骨架：状态先记为失败，各部分为空，运行中逐项填入。"""
    return {
        "schema": SCHEMA_OUT,
        "sample_id": sample_id,
        "run_id": run_id,
        "repeat_index": repeat_index,
        "status": "failed",
        "error": error,
        "failure_kind": failure_kind(error),
        "fingerprint": fp,
        "model": model,
        "prompt_version": prompts.PROMPT_VERSION,
        "code_sha256": code_sha,
        "started_at": _now(),
        "finished_at": None,
        "inputs": None,
        "technical_full_score": None,
        "prediction": None,
        "items": [],
        "artifact_extra": None,
        "rules": None,
        "compliance": None,
        "findings": None,
        "body": None,
        "usage": CallStats().as_dict(),
    }


def run_sample(rt: Runtime, llm: CachedLlm, sample: Sample, fp: str, code_sha: str, opts: Options, run_id: str) -> dict[str, Any]:
    record = empty_record(sample.sample_id, llm.model, code_sha, fp, run_id=run_id, repeat_index=opts.repeat_index)
    record["inputs"] = {"tender_sha256": sample.tender_shas(), "body_sha256": sample.body_sha()}
    project_id: str | None = None
    rt.claim_contents(sample.sample_id, [x for x in [*sample.tender_shas(), sample.body_sha()] if x])
    try:
        if not sample.tender or sample.body is None:
            raise SampleError("missing_files: 样本缺少招标文件或技术标正文")
        api = Api(rt.app)
        deadline = time.monotonic() + opts.sample_timeout
        project_id = api.post("/projects", _project_body(sample))["project_id"]
        record["project_id"] = project_id
        rt.bind_sample(project_id, sample)
        for ref in sample.tender:  # 按发布顺序，招标文件与补遗在正文之前全部入库，流水线据此一次提取规则
            upload(api, rt.store, project_id, ref.path.read_bytes(), name=ref.path.name, role=ref.role)
        body_version = upload(api, rt.store, project_id, sample.body.path.read_bytes(), name=sample.body.path.name, role="body")
        try:
            status = _wait(api, project_id, deadline, opts.poll_seconds)
        except SampleError:
            _cancel_active(api, project_id)
            raise
        _collect(rt, api, project_id, body_version["version_id"], record)
        reason = _failure_reason(api, project_id, status)
        if reason is None and record["prediction"] is None:
            reason = "prediction_missing: 评审完成但没有评分预测"
        record["status"] = "failed" if reason else "succeeded"
        record["error"] = reason
    except SampleError as exc:
        record["error"] = str(exc)
    except Exception as exc:  # 单个样本的意外错误不中断全批
        record["error"] = f"tool_error: {type(exc).__name__}: {exc}"
    finally:
        if project_id is not None:
            record["usage"] = llm.stats_for(project_id).as_dict()
        try:
            rt.release_project(sample.sample_id, project_id)
        except Exception as exc:
            print(f"{sample.sample_id} 回收内存对象失败：{exc!r}", file=sys.stderr, flush=True)
        record["finished_at"] = _now()
        record["failure_kind"] = failure_kind(record["error"]) if record["status"] != "succeeded" else None
    return record


# ------------------------------------------------------------------ 费用粗估
# 粗估口径（不调用模型；只用于决定是否开跑与预算，误差可达 ±50%）：
# * 规则提取：招标资料按产品同样的解析切成证据块，每 RULES_BATCH 块一次调用；同一组招标文件（SHA 序列相同）只计一次（缓存复用）。
# * 规则条数 R：招标证据块中含要求性措辞（必须／不得／应当／须／严禁／否决／废标／无效／不予）或分值写法（“N分”）的块数，上限 200
#   （与产品单个规则包上限一致）。诊断按每条规则一次调用，计 R 次。
# * 评分条款数 S：招标证据块中同时含分值写法与评分措辞（评分／得分／分值／满分／扣／得）的块数，上限 40（产品预测条款上限）。
#   评分预测：条款对应章节 1 次（带正文目录与全部条款），逐项判断 S × K 次（K = BIDWB_PREDICTION_REPEATS，默认 3）。
# * 比较式锚定（给了 --anchor-pack 时）：参与比较的条款数取 min(S, 6)，每条与 M 份锚点各比较一次（M = BIDWB_PREDICTION_ANCHORS，
#   默认 6，不超过可用锚点数），每次带双方各至多 6000 字。
# * 输入 token：系统提示词＋数据字符数 × TOKENS_PER_CHAR。规则提取每次带 RULES_BATCH 个招标块；诊断每次带 1 个招标块（规则出处）
#   ＋ 5 个正文块；逐项判断带 1 个招标块＋对应章节内容，按 min(14000, max(12 个正文块, 正文字数 ÷ 章节数 × 2)) 计；
#   对应章节一次带目录（每节约 SECTION_LINE_CHARS 字）与全部条款（每条约 ITEM_LINE_CHARS 字）。各加固定模板开销。
# * 输出 token：每次调用按固定均值计（规则提取 OUT_RULES，诊断 OUT_DIAGNOSIS，对应章节 OUT_MAPPING，逐项判断 OUT_JUDGEMENT，
#   锚点比较 OUT_COMPARISON）。
# * 结构修复重发按调用次数 × RETRY_FACTOR 计入。
TOKENS_PER_CHAR = 0.7
TEMPLATE_CHARS = 300
OUT_RULES, OUT_DIAGNOSIS, OUT_MAPPING, OUT_JUDGEMENT, OUT_COMPARISON = 1200, 350, 400, 700, 120
SECTION_LINE_CHARS, ITEM_LINE_CHARS = 110, 80
RETRY_FACTOR = 1.1
MAX_RULES, MAX_SCORING, BODY_TOP_K = 200, predict.MAX_ITEMS, 5
_REQUIREMENT = re.compile(r"必须|不得|应当|须|严禁|否决|废标|无效|不予|\d+(?:\.\d+)?\s*分")
_POINTS = re.compile(r"\d+(?:\.\d+)?\s*分")
_SCORING_WORDS = re.compile(r"评分|得分|分值|满分|扣|得")


@dataclass
class _Doc:
    chunks: list[str]
    pages: int
    chars: int


def _parse_cached(path: Path, sha: str, cache: dict[str, _Doc]) -> _Doc:
    if sha not in cache:
        try:
            doc = parsing.parse_pdf(path.read_bytes())
            cache[sha] = _Doc([c.quote for c in doc.chunks], doc.page_count, sum(doc.page_text_chars))
        except parsing.ParseError:
            cache[sha] = _Doc([], 0, 0)
    return cache[sha]


def estimate(samples: list[Sample], opts: Options, skipped: set[str], pack: AnchorPack | None = None) -> dict[str, Any]:
    docs: dict[str, _Doc] = {}
    seen_tender_sets: set[tuple[str, ...]] = set()
    calls = {"rules": 0.0, "diagnosis": 0.0, "prediction": 0.0, "anchors": 0.0}
    settings = Settings()
    repeats = settings.prediction_repeats
    anchors_per_item = min(settings.prediction_anchors, len(pack.anchors)) if pack else 0
    tokens_in = tokens_out = 0.0
    counted = 0
    for sample in samples:
        if sample.sample_id in skipped:
            continue
        try:
            sample.resolve_shas()
        except SampleError as exc:
            print(f"  {sample.sample_id}: 无法估算（{exc}）", flush=True)
            continue
        if sample.body is None:
            continue
        counted += 1
        tender_chunks = [c for ref in sample.tender for c in _parse_cached(ref.path, sample.shas[ref.path], docs).chunks]
        body = _parse_cached(sample.body.path, sample.shas[sample.body.path], docs)
        avg_tender = sum(map(len, tender_chunks)) / len(tender_chunks) if tender_chunks else 0
        avg_body = sum(map(len, body.chunks)) / len(body.chunks) if body.chunks else 0
        key = tuple(sample.tender_shas())
        if key not in seen_tender_sets:
            seen_tender_sets.add(key)
            n = math.ceil(len(tender_chunks) / RULES_BATCH)
            calls["rules"] += n
            tokens_in += n * (len(prompts.RULES_SYSTEM) + TEMPLATE_CHARS + RULES_BATCH * (avg_tender + 30)) * TOKENS_PER_CHAR
            tokens_out += n * OUT_RULES
        rules = min(MAX_RULES, sum(1 for c in tender_chunks if _REQUIREMENT.search(c)))
        scoring = min(MAX_SCORING, sum(1 for c in tender_chunks if _POINTS.search(c) and _SCORING_WORDS.search(c)))
        context = avg_tender + BODY_TOP_K * avg_body + TEMPLATE_CHARS
        calls["diagnosis"] += rules
        tokens_in += rules * (len(prompts.DIAGNOSIS_SYSTEM) + context) * TOKENS_PER_CHAR
        tokens_out += rules * OUT_DIAGNOSIS
        if scoring:
            sections = max(1, len(build_sections([Passage(f"c{i}", 1, c) for i, c in enumerate(body.chunks)])))
            item_body = min(predict.CONTEXT_CHARS, max(predict.FALLBACK_TOP_K * avg_body, body.chars / sections * 2))
            mapping_in = len(prompts.MAPPING_SYSTEM) + TEMPLATE_CHARS + sections * SECTION_LINE_CHARS + scoring * ITEM_LINE_CHARS
            judge_in = len(prompts.JUDGEMENT_SYSTEM) + TEMPLATE_CHARS + avg_tender + item_body
            calls["prediction"] += 1 + scoring * repeats
            tokens_in += (mapping_in + scoring * repeats * judge_in) * TOKENS_PER_CHAR
            tokens_out += OUT_MAPPING + scoring * repeats * OUT_JUDGEMENT
            compared = min(scoring, anchors.MAX_ITEMS) * anchors_per_item
            calls["anchors"] += compared
            compare_in = len(prompts.COMPARISON_SYSTEM) + TEMPLATE_CHARS + avg_tender + 2 * anchors.EXCERPT_CHARS
            tokens_in += compared * compare_in * TOKENS_PER_CHAR
            tokens_out += compared * OUT_COMPARISON
    total_calls = sum(calls.values()) * RETRY_FACTOR
    tokens_in *= RETRY_FACTOR
    tokens_out *= RETRY_FACTOR
    result: dict[str, Any] = {
        "samples": counted,
        "skipped": len(skipped),
        "unique_tender_sets": len(seen_tender_sets),
        "calls": {k: round(v * RETRY_FACTOR) for k, v in calls.items()} | {"total": round(total_calls)},
        "prompt_tokens": round(tokens_in),
        "completion_tokens": round(tokens_out),
        "cost": None,
    }
    if opts.price_in is not None and opts.price_out is not None:
        result["cost"] = round(tokens_in / 1e6 * opts.price_in + tokens_out / 1e6 * opts.price_out, 2)
    return result


# ------------------------------------------------------------------ 批量入口
@dataclass
class Summary:
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    excluded: int = 0
    stats: CallStats = field(default_factory=CallStats)
    seconds: float = 0.0
    db_name: str | None = None
    bytes_left: int = 0  # 结束时内存对象存储里仍留存的字节数（每个样本完成即回收，正常为 0）
    estimate: dict[str, Any] | None = None

    def lines(self) -> list[str]:
        if self.estimate is not None:
            e = self.estimate
            cost = f"，估算费用 {e['cost']}" if e["cost"] is not None else "（给出 --price-per-mtok-in/out 可估算费用）"
            return [
                f"粗估：待跑样本 {e['samples']}（已完成跳过 {e['skipped']}），不同招标文件组 {e['unique_tender_sets']}",
                f"  调用次数 {e['calls']['total']}（规则提取 {e['calls']['rules']}，核对 {e['calls']['diagnosis']}，预测 {e['calls']['prediction']}，"
                f"锚点比较 {e['calls']['anchors']}）",
                f"  输入 token ≈ {e['prompt_tokens']:,}，输出 token ≈ {e['completion_tokens']:,}{cost}",
            ]
        s = self.stats
        return [
            f"成功 {self.succeeded}，失败 {self.failed}，跳过（已完成）{self.skipped}，未纳入（排除项）{self.excluded}",
            f"模型调用 {s.calls} 次，输入 token {s.prompt_tokens:,}，输出 token {s.completion_tokens:,}，缓存命中 {s.cache_hits} 次",
            f"耗时 {self.seconds:.0f} 秒",
        ]


def _previous_ok(path: Path, fp: str, skip_failed: bool) -> bool:
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(old.get("fingerprint") == fp and (old.get("status") == "succeeded" or skip_failed))


def run_batch(opts: Options, llm: LlmClient | None = None) -> Summary:
    """批量运行；``llm`` 为空时按 ``BIDWB_LLM_*`` 构建真实模型客户端（测试注入脚本化模型）。"""
    started = time.monotonic()
    samples = load_dataset(opts.dataset, opts.datasets_root)
    if opts.only:
        wanted = set(opts.only)
        samples = [s for s in samples if s.sample_id in wanted]
    summary = Summary()
    if not opts.include_excluded:
        kept = [s for s in samples if s.eligible or s.exclusion not in SKIP_EXCLUSIONS]
        summary.excluded = len(samples) - len(kept)
        samples = kept
    if opts.limit is not None:
        samples = samples[: opts.limit]
    if llm is None and not opts.estimate_only:
        llm = build_llm(Settings())
        if llm is None:
            msg = "未配置模型：设置 BIDWB_LLM_BASE_URL 与 BIDWB_LLM_MODEL（以及 BIDWB_LLM_API_KEY）"
            raise SystemExit(msg)
    model = llm.model if llm is not None else (Settings().llm_model or "unconfigured")
    code_sha = code_sha256()
    pack = parse_pack(json.loads(opts.anchor_pack.read_text(encoding="utf-8"))) if opts.anchor_pack else None
    todo: list[tuple[Sample, str]] = []
    skipped: set[str] = set()
    errors: dict[str, str] = {}
    for sample in samples:
        try:
            sample.resolve_shas()
        except SampleError as exc:
            errors[sample.sample_id] = str(exc)
            todo.append((sample, ""))
            continue
        fp = fingerprint(sample, model, prompts.PROMPT_VERSION, code_sha, pack.pack_id if pack else None, opts.repeat_index)
        if _previous_ok(opts.out / f"{sample.sample_id}.json", fp, opts.skip_failed):
            skipped.add(sample.sample_id)
        else:
            todo.append((sample, fp))
    summary.skipped = len(skipped)
    if opts.estimate_only:
        summary.estimate = estimate(samples, opts, skipped, pack)
        summary.seconds = time.monotonic() - started
        return summary
    assert llm is not None
    cached = CachedLlm(llm, opts.cache_dir, namespace=opts.repeat_index)
    run_id = uuid.uuid4().hex
    opts.out.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    done = [0]

    def one(item: tuple[Sample, str]) -> None:
        sample, fp = item
        if sample.sample_id in errors or rt is None:
            record = empty_record(
                sample.sample_id, cached.model, code_sha, None, errors.get(sample.sample_id), run_id=run_id, repeat_index=opts.repeat_index
            )
            record["finished_at"] = _now()
        else:
            record = run_sample(rt, cached, sample, fp, code_sha, opts, run_id)
        _write_json(opts.out / f"{sample.sample_id}.json", record)
        with lock:
            done[0] += 1
            if record["status"] == "succeeded":
                summary.succeeded += 1
            else:
                summary.failed += 1
            p = record["prediction"] or {}
            shown = f"{p.get('estimate')}/{p.get('maximum')}" if p.get("estimate") is not None else (record["error"] or "")[:160]
            u = record["usage"]
            print(
                f"[{done[0]}/{len(todo)}] {sample.sample_id} {record['status']} {shown}"
                f"（调用 {u['calls']}，命中 {u['cache_hits']}；内存对象 {rt.store.bytes_held() / 1e6 if rt else 0:.1f} MB）",
                flush=True,
            )

    if not todo:
        summary.seconds = time.monotonic() - started
        return summary
    rt: Runtime | None = None
    if any(s.sample_id not in errors for s, _ in todo):  # 只有预检失败的样本时不必建库
        rt = Runtime(
            opts.admin_dsn, cached, concurrency=opts.concurrency, keep_db=opts.keep_db, log_level=opts.log_level, anchor_pack=pack
        )
        summary.db_name = rt.db_name
    try:
        with ThreadPoolExecutor(max_workers=opts.concurrency, thread_name_prefix="batch-sample") as pool:
            list(pool.map(one, todo))
        summary.bytes_left = rt.store.bytes_held() if rt else 0
    finally:
        if rt is not None:
            rt.close()
    summary.stats = cached.total
    summary.seconds = time.monotonic() - started
    return summary


def parse_args(argv: Sequence[str] | None = None) -> Options:
    p = argparse.ArgumentParser(description="用产品流水线批量跑评分预测（交接格式 A → B）")
    p.add_argument("dataset", type=Path, help="评分配对集.json（交接格式 A）")
    p.add_argument("--out", type=Path, required=True, help="输出目录：每个样本一个 <sample_id>.json（交接格式 B）")
    p.add_argument("--datasets-root", type=Path, help="覆盖格式 A 里的 datasets_root")
    p.add_argument(
        "--admin-dsn",
        default=os.environ.get("BIDWB_BATCH_ADMIN_DSN", DEFAULT_ADMIN_DSN),
        help="有建库权限的 PostgreSQL 连接串（默认取 BIDWB_BATCH_ADMIN_DSN）",
    )
    p.add_argument("--cache-dir", type=Path, help="模型调用磁盘缓存目录（不给则不缓存）")
    p.add_argument("--only", action="append", default=[], help="只跑这些样本编号（可重复，或用逗号分隔）")
    p.add_argument("--limit", type=int, help="只跑前 N 份（试点）")
    p.add_argument("--concurrency", type=int, default=2, help="同时在途的样本数（默认 2）")
    p.add_argument("--sample-timeout", type=float, default=30, help="每个样本的总超时，分钟（默认 30）")
    p.add_argument("--include-excluded", action="store_true", help="也跑 exclusion 为 duplicate_body / missing_files 的样本")
    p.add_argument("--skip-failed", action="store_true", help="指纹一致的失败结果也跳过（默认只跳过成功的）")
    p.add_argument("--keep-db", action="store_true", help="运行结束后保留临时数据库（排查用）")
    p.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p.add_argument("--estimate-only", action="store_true", help="不调用模型，只粗估调用次数、token 与费用")
    p.add_argument("--price-per-mtok-in", type=float, help="每百万输入 token 价格")
    p.add_argument("--price-per-mtok-out", type=float, help="每百万输出 token 价格")
    p.add_argument(
        "--repeat-index", type=int, default=0, help="运行序号（默认 0）：换一个序号即整批重跑、互不命中缓存，用于测量稳定性"
    )
    p.add_argument(
        "--anchor-pack", type=Path, help="比较锚点包（anchor-pack/1）：直接使用，不经登记与路由；与样本同一模板组的锚点一律不用"
    )
    a = p.parse_args(argv)
    if a.concurrency < 1:
        p.error("--concurrency 至少为 1")
    if a.repeat_index < 0:
        p.error("--repeat-index 不能为负")
    return Options(
        dataset=a.dataset,
        out=a.out,
        admin_dsn=a.admin_dsn,
        datasets_root=a.datasets_root,
        cache_dir=a.cache_dir,
        only=[x.strip() for item in a.only for x in item.split(",") if x.strip()],
        limit=a.limit,
        concurrency=a.concurrency,
        sample_timeout=a.sample_timeout * 60,
        include_excluded=a.include_excluded,
        skip_failed=a.skip_failed,
        keep_db=a.keep_db,
        log_level=a.log_level,
        estimate_only=a.estimate_only,
        price_in=a.price_per_mtok_in,
        price_out=a.price_per_mtok_out,
        anchor_pack=a.anchor_pack,
        repeat_index=a.repeat_index,
    )


def main(argv: Sequence[str] | None = None, llm: LlmClient | None = None) -> int:
    summary = run_batch(parse_args(argv), llm)
    for line in summary.lines():
        print(line, flush=True)
    return 1 if summary.failed else 0


if __name__ == "__main__":
    sys.exit(main())
