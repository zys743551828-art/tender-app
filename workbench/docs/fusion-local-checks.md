# 本机融合验证环境

融合入口为独立文档仓库的《标书工作台融合实施计划》，开发分支为 `dev`，`fusion/bid-workbench`保留来源历史。本目录是Codex工作台主线；根部旧backend/frontend/deploy只保留供体或历史证据。当前规格以文档仓库的AI投标工作台PRD、融合技术方案及融合详细设计为准。

## Windows运行时

优先PowerShell 7。使用本机已有Python 3.12，建立本目录专属 `.venv`，不改原Python 3.11或全局依赖。Node 22.23.2满足本机已执行前端检查，不必另装Node。安装后端检查依赖：

```powershell
& .venv/Scripts/python.exe -m pip install -r requirements-fusion-checks.txt
& .venv/Scripts/python.exe -m pip check
```

主API锁与生产解析锁存在版本差异，不能简单把两个锁依次覆盖同一环境。融合检查依赖保留API锁定版本，另固定测试所需的图像、解析及合成PDF工具；生产解析Worker仍使用独立解析环境。

本机npm证书链需要系统CA时，只对该进程启用现有Node系统信任：

```powershell
$env:NODE_OPTIONS='--use-system-ca'
npm ci --no-audit --no-fund
```

不关闭TLS校验。活跃前端源码通过 `.gitattributes` 固定LF，归档证据目录不批量格式化。构建产生的已跟踪tsbuildinfo不属于实现改动，应核对后恢复，不能混入业务提交。

## 隔离数据库

一次性 Docker 验证遵守[测试资源规则](docker-test-hygiene.md)：唯一 run ID、精确资源回执、成功/失败/取消均收尾，只删除本轮自建资源。历史验证容器及数据卷另行盘点确认，不按前缀直接清理。

预算、角色ACL和整包仓储分别使用独立临时数据库，不连接原业务库。新测试需显式提供各自测试DSN，默认跳过；它们不读取本机业务 `.env`。临时PG使用工作台Compose锁定的PG17／pgvector镜像，并绑定127.0.0.1。容器和临时库在验证完成后清理，不重启原Claude测试容器，不停止正常Word服务。

```powershell
$env:FUSION_ROLE_ACL_TEST_DSN='<仅限独立fusion_role_acl库>'
& .venv/Scripts/python.exe -m pytest -q tests/test_bootstrap_role_isolation_pg.py
$env:FUSION_RECONCILIATION_TEST_DSN='<仅限独立预算测试库>'
& .venv/Scripts/python.exe -m pytest -q tests/test_assistant_budget_reconciliation.py tests/test_assistant_budget_dispatch.py
```

POSIX 0600／0700及symlink守卫需在真实Linux文件系统验证。可复用现有本机Linux镜像，将源码只读挂载后复制到容器临时目录；不在Windows共享挂载上把权限位失败当产品逻辑失败，也不放宽守卫。

全量基线的原云端固定证据路径缺失、POSIX差异及未恢复输入必须登记具体失败。静态契约导出、局部PG检查、Mock链路、浏览器、真实模型和业务精度分层记录，未通过的全量检查不能因局部测试通过而关闭。

## 实际接口与前端类型

融合实际接口清单位于 `packages/contracts/fusion-implemented.openapi.json`，从已注册路由及当前实现契约导出。前端 `scripts/generate-contracts.py` 默认读取此文件，使用 UTF-8 生成 `src/contracts.ts`；原目标快照和旧验证输入保持原字节。新增目录的契约存在不表示界面已接入相应操作。

```powershell
& .venv/Scripts/python.exe -X utf8 -m apps.api.export_openapi > packages/contracts/fusion-implemented.openapi.json
& .venv/Scripts/python.exe -X utf8 apps/web/scripts/generate-contracts.py
```

## SQL 输入字节

活跃的直接 `packages/*/sql` 目录及 `deploy/sql` 使用显式 LF 检出规则；归档与 QA 冻结输入保持原字节。Git 归档和 Linux／Windows fresh 引导应据实际输入字节冻结 SHA，不使用另一种换行下的摘要作为当前文件摘要。

`docs/fusion-sql-input-bytes.json` 逐项记录固定 Git blob、LF SHA256 和首批 Windows 工作树原始 SHA256，只有字节来源含义，不授 SQL 审查或执行资格。首批 Windows 原始验证输入及证据保留，不通过改预期摘要隐藏旧输入；后续 Linux 精确候选使用表内 `git_sha256`。
