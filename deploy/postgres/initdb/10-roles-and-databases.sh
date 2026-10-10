#!/usr/bin/env bash
# =============================================================================
# PostgreSQL 首次初始化脚本（官方镜像只在数据目录为空时执行一次，之后不再运行）
#
# 创建：
#   角色   app_api / app_worker（NOLOGIN 权限模板；迁移 0001 用 IF NOT EXISTS 创建同名角色，已存在则跳过，兼容）
#          bidwb_owner   库属主，只给迁移（alembic）使用
#          bidwb_api     登录角色，IN ROLE app_api
#          bidwb_worker  登录角色，IN ROLE app_worker（worker / relay / reaper 使用）
#          bidwb_runtime LangGraph 检查点库的属主与登录角色
#          mlflow        MLflow 元数据库的属主与登录角色
#   数据库 bidwb（业务主库）、bidwb_runtime（LangGraph 运行库）、mlflow（MLflow 元数据库）
#
# 口令来自 /run/secrets/*（compose secrets 文件），用 psql 的 \set x `cat file` 读入：
# 不经过环境变量，也不出现在进程参数里，更不会写进镜像。
# 表的授权不在这里做：由迁移（以 bidwb_owner 执行）按 schema.sql 对 app_api / app_worker 授权。
# =============================================================================
set -Eeuo pipefail

for f in db_password_owner db_password_api db_password_worker db_password_runtime db_password_mlflow; do
  if [ ! -s "/run/secrets/${f}" ]; then
    echo "初始化失败：缺少或为空的 secret /run/secrets/${f}（先运行 scripts/gen-secrets.sh）" >&2
    exit 1
  fi
done

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname postgres <<'SQL'
\set owner_pw   `cat /run/secrets/db_password_owner`
\set api_pw     `cat /run/secrets/db_password_api`
\set worker_pw  `cat /run/secrets/db_password_worker`
\set runtime_pw `cat /run/secrets/db_password_runtime`
\set mlflow_pw  `cat /run/secrets/db_password_mlflow`

-- 权限模板角色（与迁移 0001 的 IF NOT EXISTS 兼容）
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_api')    THEN CREATE ROLE app_api    NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_worker') THEN CREATE ROLE app_worker NOLOGIN; END IF;
END
$$;

-- 登录角色。CONNECTION LIMIT 与 compose 中的 max_connections=150 配合，防止单个角色耗尽连接。
CREATE ROLE bidwb_owner   LOGIN PASSWORD :'owner_pw'   CONNECTION LIMIT 5;
CREATE ROLE bidwb_api     LOGIN PASSWORD :'api_pw'     CONNECTION LIMIT 40  IN ROLE app_api;
CREATE ROLE bidwb_worker  LOGIN PASSWORD :'worker_pw'  CONNECTION LIMIT 70  IN ROLE app_worker;
CREATE ROLE bidwb_runtime LOGIN PASSWORD :'runtime_pw' CONNECTION LIMIT 30;
CREATE ROLE mlflow        LOGIN PASSWORD :'mlflow_pw'  CONNECTION LIMIT 10;

CREATE DATABASE bidwb         OWNER bidwb_owner   ENCODING 'UTF8';
CREATE DATABASE bidwb_runtime OWNER bidwb_runtime ENCODING 'UTF8';
CREATE DATABASE mlflow        OWNER mlflow        ENCODING 'UTF8';

-- 默认任何角色都能连接任何库；收紧为“谁用谁连”
REVOKE CONNECT ON DATABASE postgres      FROM PUBLIC;
REVOKE CONNECT ON DATABASE bidwb         FROM PUBLIC;
REVOKE CONNECT ON DATABASE bidwb_runtime FROM PUBLIC;
REVOKE CONNECT ON DATABASE mlflow        FROM PUBLIC;
GRANT CONNECT ON DATABASE bidwb         TO bidwb_owner, bidwb_api, bidwb_worker;
GRANT CONNECT ON DATABASE bidwb_runtime TO bidwb_runtime;
GRANT CONNECT ON DATABASE mlflow        TO mlflow;
SQL

echo "PostgreSQL 初始化完成：角色 bidwb_owner/bidwb_api/bidwb_worker/bidwb_runtime/mlflow 与数据库 bidwb/bidwb_runtime/mlflow 已创建"
