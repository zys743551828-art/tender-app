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
#      confluent-kafka、psycopg[binary]、pypdfium2、argon2-cffi 均有 manylinux wheel（x86_64 与 aarch64
#      未在真实构建机上验证；其它架构会回退到源码编译并构建失败，这是期望的显式失败）。
#   2. 非 root（uid/gid 10001），只读根文件系统可运行：不写 .pyc（构建期已预编译），可写目录仅 /tmp（由
#      compose 以 tmpfs 提供）。
#   3. PID 1：镜像内不装 tini，由 compose 的 `init: true`（docker-init，即 tini）回收僵尸进程并转发信号；
#      直接 `docker run` 时请加 `--init`。
#   4. HEALTHCHECK 默认针对 API；其它角色在 compose 里覆盖（见 bidwb-healthcheck 的 proc 模式）。
#   5. 可复现性：pyproject.toml 只有下限版本。若仓库根目录有 constraints.txt（pip freeze 或 pip-compile 产物），
#      构建会自动用它锁定全部传递依赖——正式发版前应生成并提交（见 deploy/README.md“未验证项”）。
# =============================================================================

ARG PYTHON_IMAGE=python:3.11-slim-bookworm

# -----------------------------------------------------------------------------
# builder：创建 venv 并安装项目
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder

# 国内网络可通过构建参数指定 PyPI 镜像，例如 --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_INDEX_URL=""
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL}

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build
# constraints.tx[t] 的方括号写法让“文件不存在”也不报错（只要 pyproject.toml 匹配即可）
COPY pyproject.toml constraints.tx[t] ./
COPY src ./src

# 先构建本项目 wheel（构建后端 hatchling 在隔离环境中安装），再用 --only-binary=:all: 安装 wheel 及全部依赖：
# 任何依赖若没有当前平台的预编译包就让构建直接失败，而不是悄悄回退到源码编译（运行镜像不含编译器）。
# 已在 Python 3.11 / linux x86_64 上验证 pyproject 中的全部依赖都能以纯 wheel 安装。
RUN if [ -f constraints.txt ]; then export PIP_CONSTRAINT=/build/constraints.txt; fi \
 && pip install --upgrade pip \
 && pip wheel --no-deps --wheel-dir /build/wheels . \
 && for wheel in /build/wheels/bidwb-*.whl; do pip install --only-binary=:all: "${wheel}[parsing,retrieval]"; done \
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
