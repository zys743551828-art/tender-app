#!/usr/bin/env bash
# =============================================================================
# 部署前检查：Docker/Compose 版本、主机资源、.env 必填项与占位值、secrets 文件、compose 语法、端口占用。
# 只读检查，不改动任何东西。首次部署前、升级前（upgrade.sh 自动调用）都应通过。
#
# 退出码：0 无失败；1 有失败（警告不影响退出码，除非 --strict）
# =============================================================================
set -Eeuo pipefail
SCRIPT_NAME="preflight"
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<USAGE
用法：scripts/preflight.sh [--strict] [-h]
  --strict   警告也视为失败
USAGE
}
STRICT=0
case "${1:-}" in
  --strict) STRICT=1 ;;
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) usage >&2; exit 2 ;;
esac

n_warn=0; n_fail=0
p_ok()   { printf '[ OK ] %s\n' "$*"; }
p_warn() { n_warn=$(( n_warn + 1 )); printf '%s[WARN] %s%s\n' "${C_YEL}" "$*" "${C_OFF}"; }
p_fail() { n_fail=$(( n_fail + 1 )); printf '%s[FAIL] %s%s\n' "${C_RED}" "$*" "${C_OFF}"; }

require_cmd docker

# ---- Docker / Compose 版本 ------------------------------------------------------------------
# 本编排用到 depends_on.condition、service_completed_successfully、init、profiles、变量嵌套默认值。
# 已在 Docker 29.4.3 / Compose 5.1.3 上通过 `docker compose config` 校验；更低版本未逐一验证，
# 这里按“Docker >= 24、Compose >= 2.24”作为建议下限（只在 Docker 29.4.3 / Compose 5.1.3 上做过语法校验）。
if ! docker info >/dev/null 2>&1; then
  p_fail "无法连接 Docker 守护进程（服务未启动，或当前用户没有权限）"
else
  dv="$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 0)"
  if [[ "${dv%%.*}" =~ ^[0-9]+$ ]] && (( ${dv%%.*} >= 24 )); then p_ok "Docker Engine ${dv}"; else p_warn "Docker Engine ${dv}（建议 >= 24）"; fi
fi
if cv="$(docker compose version --short 2>/dev/null)"; then
  cv="${cv#v}"
  major="${cv%%.*}"; rest="${cv#*.}"; minor="${rest%%.*}"
  if [[ "${major}" =~ ^[0-9]+$ && "${minor}" =~ ^[0-9]+$ ]] && { (( major > 2 )) || (( major == 2 && minor >= 24 )); }; then p_ok "Docker Compose ${cv}"
  else p_warn "Docker Compose ${cv}（建议 >= 2.24）"; fi
else
  p_fail "未安装 docker compose 插件（需要 Compose v2）"
fi

# ---- 主机资源（架构文档 8.1 假设：8 vCPU / 32 GiB / 500 GB SSD，未在真机核对）----------------------------------
cpus="$(nproc 2>/dev/null || echo 0)"
if (( cpus >= 8 )); then p_ok "CPU ${cpus} 核"; else p_warn "CPU ${cpus} 核 < 8（compose 的 cpus 限额按 8 核估计）"; fi
mem_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
if (( mem_kb >= 30 * 1024 * 1024 )); then p_ok "内存 $(( mem_kb / 1024 / 1024 )) GiB"
else p_warn "内存 $(( mem_kb / 1024 / 1024 )) GiB < 32 GiB（各服务 mem_limit 之和约 26 GiB，可能不足）"; fi
root="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)"
if [[ -d "${root}" ]]; then
  avail_gb=$(( $(df -Pk "${root}" | awk 'NR==2 {print $4}') / 1024 / 1024 ))
  if (( avail_gb >= 100 )); then p_ok "Docker 数据盘可用 ${avail_gb} GiB"; else p_warn "Docker 数据盘可用 ${avail_gb} GiB（建议 >= 100 GiB，设计容量 500 GB SSD）"; fi
fi

# ---- .env ------------------------------------------------------------------------------------------------
if [[ ! -f .env ]]; then
  p_fail "缺少 .env（cp .env.example .env 后修改）"
else
  required=(APP_IMAGE WEB_IMAGE MLFLOW_IMAGE POSTGRES_IMAGE KAFKA_IMAGE MILVUS_IMAGE PUBLIC_BASE_URL
            OSS_ENDPOINT_URL OSS_PUBLIC_ENDPOINT_URL OSS_REGION OSS_BUCKET KAFKA_CLUSTER_ID)
  for v in "${required[@]}"; do
    val="$(env_get "${v}")"
    if [[ -z "${val}" ]]; then p_fail ".env：${v} 为空"
    elif [[ "${val}" == *CHANGE_ME* || "${val}" == *example.com* || "${val}" == *your-bucket-name* ]]; then
      p_fail ".env：${v}=${val} 仍是占位值，必须改成实际值"
    fi
  done
  [[ "$(env_get PUBLIC_BASE_URL)" == https://* ]] || p_fail ".env：PUBLIC_BASE_URL 必须以 https:// 开头（后端生产模式要求）"
  [[ "$(env_get PUBLIC_BASE_URL)" != */ ]] || p_fail ".env：PUBLIC_BASE_URL 不要以 / 结尾"
  if [[ "$(env_get WEB_SET_REAL_IP_FROM 10.0.0.0/8)" == "10.0.0.0/8" && "$(env_get COMPOSE_FILE)" != *tls* ]]; then
    p_warn ".env：WEB_SET_REAL_IP_FROM 仍是默认的 10.0.0.0/8，请收紧为 SLB 实际私网网段"
  fi
  for v in APP_IMAGE WEB_IMAGE MLFLOW_IMAGE POSTGRES_IMAGE KAFKA_IMAGE MILVUS_IMAGE; do
    [[ "$(env_get "${v}")" != *:latest && "$(env_get "${v}")" == *:* ]] || p_fail ".env：${v} 必须带固定版本标签且不能是 latest"
  done
  if (( n_fail == 0 )); then p_ok ".env 必填项齐全且无占位值"; fi
fi

# ---- secrets ------------------------------------------------------------------------------------------------
must=(postgres_password db_password_owner db_password_api db_password_worker db_password_runtime db_password_mlflow
      db_url_owner db_url_api db_url_worker db_url_runtime db_url_mlflow oss_access_key_id oss_secret_access_key)
optional=(llm_api_key admin_initial_password)
if [[ ! -d secrets ]]; then
  p_fail "缺少 secrets/ 目录（运行 scripts/gen-secrets.sh）"
else
  mode="$(stat -c %a secrets 2>/dev/null || echo '?')"
  if [[ "${mode}" == 700 ]]; then p_ok "secrets/ 目录权限 700"; else p_warn "secrets/ 目录权限为 ${mode}，应为 700（文件为 444，靠目录权限保护）"; fi
  bad=0
  for f in "${must[@]}"; do
    if [[ ! -s "secrets/${f}" ]]; then p_fail "secrets/${f} 不存在或为空"; bad=1; fi
  done
  for f in "${optional[@]}"; do
    [[ -e "secrets/${f}" ]] || { p_fail "secrets/${f} 文件不存在（可为空，但文件必须存在，否则 compose 挂载失败）"; bad=1; }
  done
  # 连接串必须包含对应口令（口令轮换后只改了一个文件的常见错误）
  for pair in "owner:db_url_owner" "api:db_url_api" "worker:db_url_worker" "runtime:db_url_runtime" "mlflow:db_url_mlflow"; do
    pw="secrets/db_password_${pair%%:*}"; url="secrets/${pair##*:}"
    if [[ -s "${pw}" && -s "${url}" ]] && ! grep -qF -- "$(tr -d '\r\n' < "${pw}")" "${url}"; then
      p_fail "${url} 中的口令与 ${pw} 不一致"; bad=1
    fi
  done
  [[ -s secrets/llm_api_key ]] || p_warn "secrets/llm_api_key 为空：AI 类任务将无法调用模型"
  if (( bad == 0 )); then p_ok "secrets 文件齐全，连接串与口令一致"; fi
  if [[ "$(env_get COMPOSE_FILE)" == *tls* ]]; then
    if [[ -s secrets/tls/fullchain.pem && -s secrets/tls/privkey.pem ]]; then p_ok "TLS 证书文件存在"; else p_fail "已启用 compose.tls.yml，但 secrets/tls/fullchain.pem 或 privkey.pem 缺失"; fi
  fi
fi

# ---- compose 语法 ------------------------------------------------------------------------------------------------
if [[ -f .env ]]; then
  if out="$(dc config -q 2>&1)"; then p_ok "docker compose config 语法校验通过"; else p_fail "docker compose config 失败：${out}"; fi
fi

# ---- 端口占用 -------------------------------------------------------------------------------------------------------
port="$(env_get WEB_HTTP_PORT 8080)"
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"; then
  if dc ps --format '{{.Service}}' 2>/dev/null | grep -qx web; then p_ok "端口 ${port} 已由本栈的 web 使用"
  else p_warn "宿主机端口 ${port} 已被占用"; fi
fi

printf '\n汇总：%d 警告，%d 失败\n' "${n_warn}" "${n_fail}"
if (( n_fail > 0 )); then exit 1; fi
if (( STRICT == 1 && n_warn > 0 )); then exit 1; fi
exit 0
