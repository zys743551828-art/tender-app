#!/usr/bin/env bash
# =============================================================================
# 创建首个账号。口令取自 secrets/admin_initial_password，不经命令行与环境变量。
# 登录名与显示名取 .env 的 ADMIN_LOGIN / ADMIN_DISPLAY_NAME。
#
# 调用的后端命令（backend/src/bidwb/admin.py）：
#   bidwb-admin create-member --login <登录名> --display-name <显示名> --password-file <口令文件> --if-not-exists
# 系统只有登录一道门：登录后的成员可以访问全部项目（见后端 access.py）。
# =============================================================================
set -Eeuo pipefail
SCRIPT_NAME="create-admin"
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<USAGE
用法：scripts/create-admin.sh [-h]

前提：postgres 已 healthy、迁移已完成（docker compose up -d postgres 后，本脚本会自动确保迁移完成）。
创建成功后请立即登录并修改口令，然后清空 secrets/admin_initial_password 的内容。
USAGE
}
case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) usage >&2; exit 2 ;;
esac

require_cmd docker
[[ -s secrets/admin_initial_password ]] || die "secrets/admin_initial_password 不存在或为空，先运行 scripts/gen-secrets.sh"
login="$(env_get ADMIN_LOGIN admin)"
name="$(env_get ADMIN_DISPLAY_NAME 系统管理员)"

info "创建管理员 ${login}（幂等：已存在则不改动）"
dc run --rm -T admin bidwb-admin create-member \
  --login "${login}" \
  --display-name "${name}" \
  --password-file /run/secrets/admin_initial_password \
  --if-not-exists
ok "完成。请登录后修改口令，并清空 secrets/admin_initial_password。"
