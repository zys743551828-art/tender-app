#!/usr/bin/env bash
# =============================================================================
# 运维脚本公共函数。只被其它脚本 source，不单独执行。
# 约定：所有脚本启动后工作目录都切到 deploy（compose.yml 所在目录），
#       docker compose 读取该目录下的 .env（含可选的 COMPOSE_FILE，用于启用 TLS 覆盖文件）。
# =============================================================================

# 不允许被直接执行
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "lib.sh 只能被 source" >&2
  exit 2
fi

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DEPLOY_DIR
cd "${DEPLOY_DIR}" || exit 1

# shellcheck disable=SC2034  # C_BLD 预留给调用方
if [[ -t 2 ]]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_BLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_RED=''; C_GRN=''; C_YEL=''; C_BLD=''; C_OFF=''
fi

log()  { printf '%s [%s] %s\n' "$(date '+%F %T')" "${SCRIPT_NAME:-script}" "$*" >&2; }
info() { log "$*"; }
ok()   { printf '%s%s%s\n' "${C_GRN}" "$*" "${C_OFF}" >&2; }
warn() { printf '%s警告：%s%s\n' "${C_YEL}" "$*" "${C_OFF}" >&2; }
die()  { printf '%s错误：%s%s\n' "${C_RED}" "$*" "${C_OFF}" >&2; exit 1; }

require_cmd() {
  local c
  for c in "$@"; do
    command -v "${c}" >/dev/null 2>&1 || die "缺少命令 ${c}，请先安装"
  done
}

# docker compose 封装：始终在 DEPLOY_DIR 下运行，读取 .env
dc() { docker compose "$@"; }

# 从 .env 读取变量（不 source，避免 shell 与 compose 对引号/空格/# 的解释不一致）。
# 用法：env_get 变量名 [默认值]。环境里已导出的同名变量优先（与 compose 的优先级一致）。
env_get() {
  local name="$1" default="${2:-}" line value
  if [[ -n "${!name:-}" ]]; then
    printf '%s' "${!name}"
    return 0
  fi
  if [[ -f .env ]]; then
    line="$(grep -E "^[[:space:]]*${name}=" .env | tail -n 1 || true)"
    if [[ -n "${line}" ]]; then
      value="${line#*=}"
      value="${value%%[[:space:]]#*}"                   # 去掉行内注释
      value="${value%"${value##*[![:space:]]}"}"          # 去掉尾部空白
      value="${value#\"}"; value="${value%\"}"
      value="${value#\'}"; value="${value%\'}"
      if [[ -n "${value}" ]]; then
        printf '%s' "${value}"
        return 0
      fi
    fi
  fi
  printf '%s' "${default}"
}

# 在 postgres 容器内以超级用户执行 psql（容器内本地套接字信任认证，无需口令）。
# 用法：pg_psql 数据库 [psql 参数...]；SQL 经标准输入或 -c 传入
pg_psql() {
  local db="$1"; shift
  dc exec -T postgres psql -X -q -v ON_ERROR_STOP=1 -U postgres -d "${db}" "$@"
}

# 业务数据库清单：备份与恢复都以它为准（名称与 postgres/initdb 脚本一致）
# shellcheck disable=SC2034  # 由 backup.sh / restore.sh 使用
BIDWB_DATABASES=(bidwb bidwb_runtime mlflow)

# 确认容器 postgres 正在运行且健康
require_postgres_running() {
  local state
  state="$(dc ps --format '{{.Health}}' postgres 2>/dev/null || true)"
  [[ "${state}" == "healthy" ]] || die "postgres 容器未处于 healthy 状态（当前：${state:-未运行}），先执行 docker compose up -d postgres"
}

# 把秒数格式化为易读文本
human_age() {
  local s="$1"
  if (( s < 3600 )); then printf '%d 分钟' $(( s / 60 ))
  elif (( s < 86400 )); then printf '%d 小时' $(( s / 3600 ))
  else printf '%d 天' $(( s / 86400 ))
  fi
}

# 跨平台的文件修改时间（秒）
file_mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1"; }

# 数据库 → 属主与允许连接的角色。与 postgres/initdb/10-roles-and-databases.sh 保持一致：
# restore.sh 在“就地恢复”重建数据库后，用它重新授予连接权限。
db_owner() {
  case "$1" in
    bidwb) echo bidwb_owner ;;
    bidwb_runtime) echo bidwb_runtime ;;
    mlflow) echo mlflow ;;
    *) die "未知数据库：$1" ;;
  esac
}
db_connect_roles() {
  case "$1" in
    bidwb) echo "bidwb_owner, bidwb_api, bidwb_worker" ;;
    bidwb_runtime) echo "bidwb_runtime" ;;
    mlflow) echo "mlflow" ;;
    *) die "未知数据库：$1" ;;
  esac
}

# 统计某库 public 之外所有用户模式下的表数量与精确总行数，输出“表数 总行数”。
# 用于备份清单与恢复核验。总行数用 query_to_xml 逐表精确计数，库较大时会慢（本系统一期库很小）。
db_table_stats() {
  local db="$1"
  pg_psql "${db}" -At -F ' ' -c "
    SELECT count(*),
           COALESCE(sum((xpath('/row/c/text()',
             query_to_xml(format('SELECT count(*) AS c FROM %I.%I', schemaname, tablename), false, true, '')))[1]::text::bigint), 0)
    FROM pg_tables
    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')"
}

# 解析备份批次参数：接受 latest、批次 ID（20261007-023000）或目录路径，输出目录绝对路径
resolve_backup_dir() {
  local arg="$1" base
  base="$(env_get BACKUP_DIR ./backups)"
  [[ "${base}" = /* ]] || base="${DEPLOY_DIR}/${base#./}"
  if [[ "${arg}" == latest ]]; then
    [[ -L "${base}/latest" ]] || die "${base}/latest 不存在：还没有成功的备份"
    arg="$(readlink -f "${base}/latest")"
  elif [[ -d "${arg}" ]]; then
    arg="$(cd "${arg}" && pwd)"
  elif [[ -d "${base}/${arg}" ]]; then
    arg="${base}/${arg}"
  else
    die "找不到备份批次：${arg}（在 ${base} 下查找）"
  fi
  printf '%s' "${arg}"
}

# 备份目录绝对路径
backup_base_dir() {
  local base
  base="$(env_get BACKUP_DIR ./backups)"
  [[ "${base}" = /* ]] || base="${DEPLOY_DIR}/${base#./}"
  printf '%s' "${base}"
}
