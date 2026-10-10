# syntax=docker/dockerfile:1.7
# =============================================================================
# MLflow Tracking Server 镜像（自建原因：官方镜像不一定带 PostgreSQL 驱动与 boto3，这里显式安装）
#
# 版本由构建参数 MLFLOW_VERSION 固定（默认值取自 PyPI 2026-10-07 的最新版；升级前先看 MLflow 发行说明，
# 后端库结构升级需要 `mlflow db upgrade`，见 deploy/README.md“升级”一节）。
# 非 root 运行（uid 10002），根文件系统只读，可写目录仅 /tmp 与挂载的产物卷。
# =============================================================================
ARG PYTHON_IMAGE=python:3.11-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG MLFLOW_VERSION=3.17.0
ARG PIP_INDEX_URL=""
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# mlflow[db] = psycopg2-binary + psycopg；boto3 用于 S3 兼容的产物存储（阿里云 OSS）
RUN pip install --only-binary=:all: "mlflow[db]==${MLFLOW_VERSION}" boto3 \
 && groupadd --system --gid 10002 mlflow \
 && useradd --system --uid 10002 --gid 10002 --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin mlflow \
 && mkdir -p /mlflow/artifacts && chown 10002:10002 /mlflow/artifacts

USER 10002:10002
WORKDIR /tmp
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=4).status == 200 else 1)"]
CMD ["mlflow", "server", "--help"]
