# syntax=docker/dockerfile:1.7
# =============================================================================
# 施组工作台 · 后端镜像（API / relay / reaper / worker / migrate / admin 共用一个镜像）
#
# 构建上下文：backend（见 deploy/compose.yml 的 build.context）
# 同一镜像通过不同 command 运行不同角色，这样“API 与 worker 版本一致”由构造保证，不会出现灰度错配：
#   bidwb-api | bidwb-relay | bidwb-reaper | bidwb-worker | bidwb-admin ... | alembic upgrade head
#
# 设计要点
#   1. 多阶段：builder 在 venv 里安装依赖与项目 wheel；runtime 只复制 venv，不含编译器、pip 缓存与测试。
#      当前锁仅支持 Linux amd64 / CPython 3.11，依赖只安装已锁定 wheel，不回退到源码构建。
#   2. 非 root（uid/gid 10001），只读根文件系统可运行：不写 .pyc（构建期已预编译），可写目录仅 /tmp（由
#      compose 以 tmpfs 提供）。
#   3. PID 1：镜像内不装 tini，由 compose 的 `init: true`（docker-init，即 tini）回收僵尸进程并转发信号；
#      直接 `docker run` 时请加 `--init`。
#   4. HEALTHCHECK 默认针对 API；其它角色在 compose 里覆盖（见 bidwb-healthcheck 的 proc 模式）。
#   5. requirements-build.lock.txt 与 requirements-runtime.lock.txt 分别固定构建与运行依赖，
#      pip --require-hashes 校验；本项目 wheel 在已锁构建环境生成，不升级 pip、不隔离下载构建工具。
# =============================================================================

# 官方 Python 3.11.18 / slim-bookworm，Linux amd64 manifest（非跨架构 index）。
# 外部覆盖此 ARG 的调用者负责平台、基础镜像与锁的重新验证；Compose 传参同样会覆盖默认值。
ARG PYTHON_IMAGE=python:3.11.18-slim-bookworm@sha256:061c190f3d5815b341a18dfe8a45771f8ba68c15a607ea56997fde3009ac4eec

# -----------------------------------------------------------------------------
# builder：创建 venv 并安装项目
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder

# 兼容现有调用保留参数；锁内 index-url 为权威，不用构建参数绕过锁的来源与 hash。
ARG PIP_INDEX_URL=""
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/build-venv \
 && python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build
COPY pyproject.toml requirements-build.lock.txt requirements-runtime.lock.txt ./
COPY src ./src

# 两个锁分别为 6 个构建包与包含 parsing/retrieval 的 74 个运行包；仅运行 venv 进入最终镜像。
# 本地源码生成的项目 wheel 不属于外部包锁；--no-index --no-deps 禁止安装它时重新解析依赖。
RUN /opt/build-venv/bin/python -m pip --isolated install --require-hashes --no-build-isolation -r requirements-build.lock.txt \
 && /opt/build-venv/bin/python -m pip --isolated wheel --no-index --no-deps --no-build-isolation --wheel-dir /build/wheels . \
 && python -m pip --isolated install --require-hashes --no-build-isolation -r requirements-runtime.lock.txt \
 && for wheel in /build/wheels/bidwb-*.whl; do python -m pip --isolated install --no-index --no-deps --no-build-isolation "${wheel}[parsing,retrieval]"; done \
 && python -m pip check \
 && python -c "import bidwb, fastapi, uvicorn, psycopg, confluent_kafka, pypdfium2, argon2, boto3; print('imports ok')"

# -----------------------------------------------------------------------------
# runtime：精简运行镜像
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ARG APP_UID=10001
ARG APP_GID=10001
ARG VERSION=dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="bidwb-backend" \
      org.opencontainers.image.description="施组工作台后端（API、任务协议、worker）" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:${PATH}" \
    BIDWB_ENVIRONMENT=production \
    BIDWB_API_HOST=0.0.0.0

RUN groupadd --system --gid ${APP_GID} app \
 && useradd --system --uid ${APP_UID} --gid ${APP_GID} --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin app

# 健康检查脚本（仅标准库）：http 模式探测接口；proc 模式确认 bidwb-* 进程仍在运行（worker/relay/reaper 无 HTTP 端口）。
# proc 只是进程存活检查，不能发现“进程卡死”；任务停滞由回收器与租约机制兜底（见架构文档 7.1、8.2）。
COPY --chmod=0755 <<'PYEOF' /usr/local/bin/bidwb-healthcheck
#!/opt/venv/bin/python
"""用法：bidwb-healthcheck http <url> | bidwb-healthcheck proc。退出码 0 = 健康。"""
import os
import sys
import urllib.request


def check_http(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=4) as resp:  # noqa: S310 - 仅探测本机固定地址
            return 0 if 200 <= resp.status < 300 else 1
    except Exception as exc:  # 任何异常都视为不健康
        print(f"unhealthy: {exc}", file=sys.stderr)
        return 1


def check_proc() -> int:
    me = os.getpid()
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == me:
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as fh:
                argv = [a.decode(errors="replace") for a in fh.read().split(b"\0") if a]
        except OSError:
            continue
        if not argv or argv[0].endswith(("docker-init", "tini")):
            continue
        names = [os.path.basename(a) for a in argv]
        if any(n.startswith("bidwb-") and n != "bidwb-healthcheck" for n in names):
            return 0
    print("unhealthy: 未找到 bidwb-* 进程", file=sys.stderr)
    return 1


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "http"
    if mode == "http" and len(sys.argv) > 2:
        sys.exit(check_http(sys.argv[2]))
    if mode == "proc":
        sys.exit(check_proc())
    print(__doc__, file=sys.stderr)
    sys.exit(2)
PYEOF

COPY --from=builder /opt/venv /opt/venv

# Alembic 迁移：工作目录 /backend（alembic.ini 里 script_location = migrations 为相对路径）
WORKDIR /backend
COPY alembic.ini ./
COPY migrations ./migrations
RUN mkdir -p /word-input /word-output \
 && chown 10001:10001 /word-input \
 && chown 65534:65534 /word-output

USER ${APP_UID}:${APP_GID}
EXPOSE 8000

# 默认角色为 API；compose 中各服务用 command 覆盖。HEALTHCHECK 在 compose 中也会按角色覆盖。
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD ["bidwb-healthcheck", "http", "http://127.0.0.1:8000/healthz"]

CMD ["bidwb-api"]
