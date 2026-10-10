#!/bin/sh
# =============================================================================
# 开发环境一次性初始化（由 compose.dev.yml 的 dev-init 服务在后端镜像内执行）
#   1. 在 MinIO（模拟 OSS）里创建桶（幂等）
#   2. 创建本地管理员账号（口令来自 secret 文件 admin_initial_password，不写死在任何文件里）
# 仅用于开发；生产环境的首个账号见 README“创建首个账号”与 scripts/create-admin.sh。
# =============================================================================
set -eu

echo "[dev-init] 创建 MinIO 桶：${BIDWB_STORAGE_BUCKET}"
python - <<'PY'
import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def secret(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip()


s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["BIDWB_STORAGE_ENDPOINT_URL"],
    region_name=os.environ["BIDWB_STORAGE_REGION"],
    aws_access_key_id=secret(os.environ["BIDWB_STORAGE_ACCESS_KEY_ID_FILE"]),
    aws_secret_access_key=secret(os.environ["BIDWB_STORAGE_SECRET_ACCESS_KEY_FILE"]),
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)
bucket = os.environ["BIDWB_STORAGE_BUCKET"]
try:
    s3.create_bucket(Bucket=bucket)
    print(f"[dev-init] 桶 {bucket} 已创建")
except ClientError as exc:
    if exc.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
        raise
    print(f"[dev-init] 桶 {bucket} 已存在")
# CORS：MinIO 不支持按桶设置 CORS（PutBucketCors），而是由服务端环境变量 MINIO_API_CORS_ALLOW_ORIGIN 统一控制，
# 已在 compose.dev.yml 的 minio 服务里配置。
PY

echo "[dev-init] 创建本地管理员：${ADMIN_LOGIN}"
# create-member 幂等（--if-not-exists），口令用 --password-file 传入，不出现在进程参数里
bidwb-admin create-member \
  --login "${ADMIN_LOGIN}" \
  --display-name "${ADMIN_DISPLAY_NAME}" \
  --password-file /run/secrets/admin_initial_password \
  --if-not-exists

echo "[dev-init] 完成。登录名：${ADMIN_LOGIN}；口令见 secrets/admin_initial_password"
