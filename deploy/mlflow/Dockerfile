# syntax=docker/dockerfile:1.7
# =============================================================================
# MLflow Tracking Server 镜像（自建原因：官方镜像不一定带 PostgreSQL 驱动与 boto3，这里显式安装）
#
# requirements.lock.txt 固定 mlflow[db]==3.17.0、boto3 及完整 96 包闭包；不升级 pip、不下载隔离构建工具。
# MLFLOW_VERSION 仅检查与锁一致，覆盖它不能绕过锁。升级需同步重新生成并验证锁；
# 后端库结构升级仍需 `mlflow db upgrade`，见 deploy/README.md“升级”一节。
# 非 root 运行（uid 10002），根文件系统只读，可写目录仅 /tmp 与挂载的产物卷。
# =============================================================================
# 官方 Python 3.11.18 / slim-bookworm，仅 Linux amd64；外部 ARG（含 Compose）覆盖由调用者重新验证。
ARG PYTHON_IMAGE=python:3.11.18-slim-bookworm@sha256:061c190f3d5815b341a18dfe8a45771f8ba68c15a607ea56997fde3009ac4eec
FROM ${PYTHON_IMAGE}

ARG MLFLOW_VERSION=3.17.0
# 兼容旧调用保留；实际包来源由锁内 index-url 决定。
ARG PIP_INDEX_URL=""
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# mlflow[db] = psycopg2-binary + psycopg；boto3 用于 S3 兼容的产物存储（阿里云 OSS）
COPY requirements.lock.txt /tmp/mlflow-requirements.lock.txt
RUN python -m pip --isolated install --require-hashes --no-build-isolation -r /tmp/mlflow-requirements.lock.txt \
 && python -m pip check \
 && python -c "from importlib.metadata import version; import sys; assert version('mlflow') == sys.argv[1], 'MLFLOW_VERSION must match requirements.lock.txt'" "${MLFLOW_VERSION}" \
 && rm /tmp/mlflow-requirements.lock.txt \
 && groupadd --system --gid 10002 mlflow \
 && useradd --system --uid 10002 --gid 10002 --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin mlflow \
 && mkdir -p /mlflow/artifacts && chown 10002:10002 /mlflow/artifacts

USER 10002:10002
WORKDIR /tmp
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=4).status == 200 else 1)"]
CMD ["mlflow", "server", "--help"]
