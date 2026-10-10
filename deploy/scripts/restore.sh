#!/usr/bin/env bash
# =============================================================================
# 恢复：默认是“恢复演练”——把备份恢复到一个新建的临时库并核验，完全不影响线上库。
#
#   演练（默认，安全）：对备份里的每个库，在同一 PostgreSQL 实例中创建 restore_<库名>_<时间戳>，
#                       用 pg_restore --exit-on-error 导入，再核验：
#                         · sha256 与清单一致
#                         · 迁移版本（alembic_version）与清单一致
#                         · 表数量与清单一致
#                         · 总行数与备份时对比（仅报告差异：三库依次转储，备份期间的写入会造成少量差异）
#                       核验结束默认删除临时库（--keep 保留以便人工抽查）。
#   就地恢复（危险）：--in-place --yes。会停止应用、删除并重建线上库、再导入。仅用于灾难恢复。
#
# “SQL 导入成功”不等于“业务恢复成功”：架构文档 8.3 要求导入后还要核对生效对象、抽样打开原页与提交稿、
# 核对快照/结果/发布关联、重建 Milvus 索引、处理未完成任务租约。本脚本结束时会打印这份核对清单。
#
# 退出码：0 通过；1 失败；2 参数错误
# =============================================================================
set -Eeuo pipefail
SCRIPT_NAME="restore"
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<USAGE
用法：scripts/restore.sh --backup <latest|批次ID|目录> [选项]

选项：
  --backup REF        要恢复的备份批次（必填）：latest、20261007-023000 或目录路径
  --db NAME           只处理一个库（bidwb | bidwb_runtime | mlflow），默认处理该批次里的全部库
  --keep              演练后保留临时库（默认删除）。临时库名会打印出来，请事后手工 DROP
  --in-place          就地恢复到线上库（危险，必须同时给 --yes）
  --yes               确认执行 --in-place 的破坏性操作
  --no-pre-backup     就地恢复前不先做一次备份（不推荐）
  -h, --help          显示本帮助

示例：
  scripts/restore.sh --backup latest                       # 演练：恢复到临时库并核验
  scripts/restore.sh --backup 20261007-023000 --db bidwb --keep
  scripts/restore.sh --backup latest --in-place --yes      # 灾难恢复：覆盖线上库
USAGE
}

BACKUP_REF=""; ONLY_DB=""; KEEP=0; IN_PLACE=0; YES=0; PRE_BACKUP=1
while (( $# > 0 )); do
  case "$1" in
    --backup) BACKUP_REF="${2:?--backup 需要参数}"; shift ;;
    --db) ONLY_DB="${2:?--db 需要参数}"; shift ;;
    --keep) KEEP=1 ;;
    --in-place) IN_PLACE=1 ;;
    --yes) YES=1 ;;
    --no-pre-backup) PRE_BACKUP=0 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done
[[ -n "${BACKUP_REF}" ]] || { usage >&2; exit 2; }
if (( IN_PLACE == 1 && YES == 0 )); then
  die "--in-place 会删除并重建线上数据库，必须同时指定 --yes 以确认"
fi
if (( IN_PLACE == 1 && KEEP == 1 )); then die "--keep 只适用于演练模式"; fi

require_cmd docker sha256sum
BDIR="$(resolve_backup_dir "${BACKUP_REF}")"
[[ -f "${BDIR}/manifest.txt" ]] || die "${BDIR} 不是有效的备份批次（缺少 manifest.txt）"
require_postgres_running

# 读取清单中的值
manifest_get() { grep -E "^$1=" "${BDIR}/manifest.txt" | head -n 1 | cut -d= -f2-; }

databases=()
for db in "${BIDWB_DATABASES[@]}"; do
  if [[ -n "${ONLY_DB}" && "${db}" != "${ONLY_DB}" ]]; then continue; fi
  [[ -n "$(manifest_get "db.${db}.file")" ]] || { warn "批次中没有 ${db}，跳过"; continue; }
  databases+=("${db}")
done
(( ${#databases[@]} > 0 )) || die "没有可恢复的数据库（--db ${ONLY_DB:-全部}）"

info "备份批次：$(manifest_get batch_id)（创建于 $(manifest_get created_at_utc)，标注：$(manifest_get label)）"
info "迁移版本：$(manifest_get alembic_revision)；OSS 桶：$(manifest_get oss_bucket)；OSS 清单：$(manifest_get oss_manifest)"

# ---- 通用核验 ------------------------------------------------------------------------
failures=0
fail() { printf '%s  [失败] %s%s\n' "${C_RED}" "$*" "${C_OFF}" >&2; failures=$(( failures + 1 )); }
pass() { printf '%s  [通过] %s%s\n' "${C_GRN}" "$*" "${C_OFF}" >&2; }

verify_checksums() {
  info "校验 sha256 ..."
  if ( cd "${BDIR}" && sha256sum --quiet -c SHA256SUMS ); then pass "文件校验和与清单一致"
  else fail "文件校验和不一致：备份文件已损坏或被改动"; fi
}

# 对恢复出的库做核验。参数：逻辑库名 实际库名
verify_restored() {
  local db="$1" actual="$2" tables rows exp_tables exp_rows rev exp_rev
  read -r tables rows < <(db_table_stats "${actual}")
  exp_tables="$(manifest_get "db.${db}.tables")"
  exp_rows="$(manifest_get "db.${db}.total_rows_at_backup")"
  if [[ "${tables}" == "${exp_tables}" ]]; then pass "${db}：表数量 ${tables} 与清单一致"
  else fail "${db}：表数量 ${tables} ≠ 清单 ${exp_tables}"; fi
  if [[ "${rows}" == "${exp_rows}" ]]; then pass "${db}：总行数 ${rows} 与备份时一致"
  else warn "${db}：总行数 ${rows}，备份时记录 ${exp_rows}（差 $(( rows - exp_rows ))）——三库依次转储，备份期间有写入时会有小差异；差异很大才需要调查"; fi
  if [[ "${db}" == "bidwb" ]]; then
    rev="$(pg_psql "${actual}" -At -c 'SELECT version_num FROM alembic_version' 2>/dev/null || echo none)"
    exp_rev="$(manifest_get alembic_revision)"
    if [[ "${rev}" == "${exp_rev}" ]]; then pass "bidwb：迁移版本 ${rev} 与清单一致"
    else fail "bidwb：迁移版本 ${rev} ≠ 清单 ${exp_rev}"; fi
  fi
}

restore_into() {   # 参数：逻辑库名 目标库名
  local db="$1" target="$2"
  info "导入 ${db}.dump → ${target}（pg_restore --exit-on-error）..."
  if dc exec -T postgres pg_restore -U postgres --no-password --exit-on-error -d "${target}" < "${BDIR}/${db}.dump"; then
    pass "${db}：pg_restore 无错误完成"
  else
    fail "${db}：pg_restore 报错"; return 1
  fi
}

verify_checksums
(( failures == 0 )) || die "备份文件校验失败，停止恢复"

checklist() {
  cat >&2 <<'CHK'

────────────── 业务恢复核对清单（脚本无法替你完成，演练/恢复后必须逐项做）──────────────
 1. 迁移：确认应用镜像版本与备份里的迁移版本匹配（升级失败回退时尤其重要）
 2. 对象：按 manifest 的备份时间点，核对 OSS 中对应的原件与不可变产物仍在、校验值与库内记录一致
 3. 抽样：登录系统，打开 3~5 个项目的原页与提交稿，核对文件版本、校验和与大小
 4. 关联：核对快照、结果、发布路由之间的关联完整（尤其是最近一次发布切换）
 5. 任务：未知租约会被回收器（reaper）自动重排；确认没有“running 但 worker 不存在”的残留，
          LangGraph 失效断点从冻结输入显式重跑，不能当作已完成结果
 6. 索引：Milvus 与 Kafka 不在备份内。恢复后由解析产物重建 Milvus 索引并核对命中（后端没有索引重建命令：当前检索只走关键词通道，不依赖 Milvus 索引，见 README 7.4）；
          Kafka 主题由 kafka-init 重建，未完成任务靠回收器重发
 7. 记录：把本次演练/恢复的时间、批次、耗时、核对结果记入运维台账（RTO ≤ 4 小时需要实测数据）
────────────────────────────────────────────────────────────────────────────────────
CHK
}

# ---- 演练模式 ------------------------------------------------------------------------
if (( IN_PLACE == 0 )); then
  stamp="$(date -u +%Y%m%d%H%M%S)"
  created=()
  drop_created() {
    local t
    for t in "${created[@]}"; do
      pg_psql postgres -c "DROP DATABASE IF EXISTS \"${t}\" WITH (FORCE)" >/dev/null || warn "删除临时库 ${t} 失败，请手工 DROP"
    done
  }
  for db in "${databases[@]}"; do
    target="restore_${db}_${stamp}"
    pg_psql postgres -c "CREATE DATABASE \"${target}\" OWNER \"$(db_owner "${db}")\" ENCODING 'UTF8'" >/dev/null
    created+=("${target}")
    restore_into "${db}" "${target}" && verify_restored "${db}" "${target}"
  done
  if (( KEEP == 1 )); then
    info "已保留临时库：${created[*]}。核验完毕请执行：docker compose exec -T postgres psql -U postgres -c 'DROP DATABASE \"<库名>\"'"
  else
    drop_created
  fi
  checklist
  if (( failures > 0 )); then die "恢复演练发现 ${failures} 项失败"; fi
  ok "恢复演练技术核验通过（业务核对仍需按上面的清单完成）"
  exit 0
fi

# ---- 就地恢复 ------------------------------------------------------------------------
warn "即将就地恢复：${databases[*]}。线上数据将被备份批次 $(manifest_get batch_id) 的内容覆盖。"
if (( PRE_BACKUP == 1 )); then
  info "先对当前线上数据做一次 pre-restore 备份，以便反悔 ..."
  "$(dirname "${BASH_SOURCE[0]}")/backup.sh" --label "pre-restore-of-$(manifest_get batch_id)" --no-prune
fi

info "停止依赖数据库的服务 ..."
dc stop web api relay reaper worker-parse worker-ai worker-experiment worker-export mlflow >/dev/null 2>&1 || true

for db in "${databases[@]}"; do
  owner="$(db_owner "${db}")"
  info "重建数据库 ${db}（属主 ${owner}）"
  pg_psql postgres -c "DROP DATABASE IF EXISTS \"${db}\" WITH (FORCE)" >/dev/null
  pg_psql postgres -c "CREATE DATABASE \"${db}\" OWNER \"${owner}\" ENCODING 'UTF8'" >/dev/null
  pg_psql postgres -c "REVOKE CONNECT ON DATABASE \"${db}\" FROM PUBLIC" >/dev/null
  pg_psql postgres -c "GRANT CONNECT ON DATABASE \"${db}\" TO $(db_connect_roles "${db}")" >/dev/null
  restore_into "${db}" "${db}" && verify_restored "${db}" "${db}"
done

checklist
if (( failures > 0 )); then
  die "就地恢复完成但有 ${failures} 项核验失败；服务保持停止。请排查，必要时用 pre-restore 备份回滚"
fi
ok "数据库已恢复。服务仍处于停止状态：确认无误后执行 docker compose up -d 启动（reaper 会处理未完成任务）"
