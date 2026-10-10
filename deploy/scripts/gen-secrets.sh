#!/usr/bin/env bash
# =============================================================================
# 生成部署所需的 secret 文件到 ./secrets/（已存在的文件绝不覆盖，可重复运行）。
#
#   自动生成：数据库各角色口令与连接串、PostgreSQL 超级用户口令、首个管理员初始口令
#   需手工提供：OSS AccessKey、模型 API Key（脚本只建空文件，由你填写）
#
# 权限说明：目录 0700（只有部署用户能进入），文件默认 0444。
#   不能用 0600：secrets 以 bind mount 方式挂进容器，容器里的非 root 用户（postgres 999、应用 10001、
#   nginx 101、mlflow 10002）要能读取文件；Docker Compose（非 Swarm）不会改写文件属主与权限。
#   0444 只在“目录 0700 + 宿主机不给其他人 docker 权限”的前提下才安全，见 secrets/README.md。
#   如果你把 secrets 放在共享目录，请不要使用本脚本的默认权限，改用 Docker Swarm secrets 或外部密钥管理。
# =============================================================================
set -Eeuo pipefail
SECRETS_DIR_DEFAULT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/secrets"

usage() {
  cat <<USAGE
用法：scripts/gen-secrets.sh [选项]

选项：
  --dev          同时生成开发环境用的 MinIO 凭据（minio_root_user / minio_root_password）
  --dir DIR      secrets 目录（默认 ${SECRETS_DIR_DEFAULT}）
  --mode MODE    文件权限（默认 0444，原因见脚本头注释）
  -h, --help     显示本帮助

行为：已存在且非空的文件保持不变；绝不覆盖，也不会打印任何口令内容。
USAGE
}

DEV=0
SECRETS_DIR="${SECRETS_DIR_DEFAULT}"
FILE_MODE="0444"
while (( $# > 0 )); do
  case "$1" in
    --dev) DEV=1 ;;
    --dir) SECRETS_DIR="${2:?--dir 需要参数}"; shift ;;
    --mode) FILE_MODE="${2:?--mode 需要参数}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

command -v openssl >/dev/null 2>&1 || { echo "错误：需要 openssl" >&2; exit 1; }

umask 077
mkdir -p "${SECRETS_DIR}"
chmod 0700 "${SECRETS_DIR}"

created=()
kept=()
manual=()

path_of() { printf '%s/%s' "${SECRETS_DIR}" "$1"; }
exists_nonempty() { [[ -s "$(path_of "$1")" ]]; }
read_value() { tr -d '\r\n' < "$(path_of "$1")"; }

# 写文件：内容经标准输入，末尾不带换行（后端读取时会 strip，psql 的反引号也会去掉换行，二者都兼容）
write_secret() {
  local name="$1" mode="${2:-${FILE_MODE}}" tmp
  tmp="$(mktemp "${SECRETS_DIR}/.tmp.XXXXXX")"
  cat > "${tmp}"
  chmod "${mode}" "${tmp}"
  mv -f "${tmp}" "$(path_of "${name}")"
}

# 随机口令：48 位十六进制（192 位熵）。只含 [0-9a-f]，可直接放进连接串，无需转义。
gen_hex() { openssl rand -hex 24; }

ensure_random() {
  local name="$1"
  if exists_nonempty "${name}"; then kept+=("${name}"); return; fi
  gen_hex | tr -d '\n' | write_secret "${name}"
  created+=("${name}")
}

# 连接串由口令文件派生；口令存在而连接串缺失时据现有口令重建
ensure_url() {
  local name="$1" user="$2" db="$3" scheme="$4" pwfile="$5"
  if exists_nonempty "${name}"; then kept+=("${name}"); return; fi
  printf '%s://%s:%s@postgres:5432/%s' "${scheme}" "${user}" "$(read_value "${pwfile}")" "${db}" | write_secret "${name}"
  created+=("${name}")
}

# 需要人工填写的文件：只建空文件
ensure_manual() {
  local name="$1"
  if exists_nonempty "${name}"; then kept+=("${name}"); return; fi
  if [[ ! -e "$(path_of "${name}")" ]]; then
    # 手工填写的文件给属主写权限（0644），否则编辑器保存会失败；仍对容器内用户可读
    : | write_secret "${name}" 0644
    created+=("${name}")
  fi
  manual+=("${name}")
}

# ---- 自动生成 ---------------------------------------------------------------
ensure_random postgres_password
ensure_random db_password_owner
ensure_random db_password_api
ensure_random db_password_worker
ensure_random db_password_runtime
ensure_random db_password_mlflow
ensure_random admin_initial_password

# 应用使用 SQLAlchemy + psycopg3 驱动（postgresql+psycopg），MLflow 使用 psycopg2（postgresql）
ensure_url db_url_owner   bidwb_owner   bidwb         'postgresql+psycopg' db_password_owner
ensure_url db_url_api     bidwb_api     bidwb         'postgresql+psycopg' db_password_api
ensure_url db_url_worker  bidwb_worker  bidwb         'postgresql+psycopg' db_password_worker
ensure_url db_url_runtime bidwb_runtime bidwb_runtime 'postgresql+psycopg' db_password_runtime
ensure_url db_url_mlflow  mlflow        mlflow        'postgresql'         db_password_mlflow

# ---- 需手工提供 -------------------------------------------------------------
ensure_manual oss_access_key_id
ensure_manual oss_secret_access_key
ensure_manual llm_api_key

# ---- 开发环境 ---------------------------------------------------------------
if (( DEV == 1 )); then
  if ! exists_nonempty minio_root_user; then
    printf 'bidwb-dev' | write_secret minio_root_user
    created+=(minio_root_user)
  else
    kept+=(minio_root_user)
  fi
  ensure_random minio_root_password
fi

printf '\n目录：%s\n' "${SECRETS_DIR}"
(( ${#created[@]} > 0 )) && printf '新建：%s\n' "${created[*]}"
(( ${#kept[@]} > 0 ))    && printf '保留：%s\n' "${kept[*]}"
if (( ${#manual[@]} > 0 )); then
  printf '\n以下文件需要你手工填写（内容为单行，不要带引号；写入后保持文件权限不变）：\n'
  for f in "${manual[@]}"; do printf '  %s\n' "$(path_of "${f}")"; done
  printf '  其中 oss_access_key_id / oss_secret_access_key 必填；llm_api_key 不填则 AI 任务不可用。\n'
fi
printf '\n首个管理员的初始口令在 %s ；创建管理员后请修改口令并把该文件内容清空或删除。\n' "$(path_of admin_initial_password)"
printf '请立即把整个 secrets 目录离线备份到受控位置：它丢失后数据库角色口令只能重置，OSS 与模型密钥需重新签发。\n'
