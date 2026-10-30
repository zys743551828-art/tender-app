> 后续开发统一使用 `dev`，跟踪 `origin/dev`。应用源码主目录为 `workbench/`；旧供体及历史分支作为来源保留。跨仓维护策略见[正式交接](https://github.com/zys743551828-art/tender-docs/blob/dev/00-项目管理/工作交接.md)。

> 当前工作交接请先读 [HANDOFF-20261017.md](HANDOFF-20261017.md)，该记录对应`handoff/2026-10-17`历史分支。以下历史说明保留原范围。

当前新增系统在 [workbench](workbench/README.md)，当前开发分支 `dev`（保留 `render-acceptance-20261026` 来源历史）。正式[需求与实现追溯](https://github.com/zys743551828-art/tender-docs/blob/dev/02-业务与产品/实现追溯矩阵.md)及[运行说明](https://github.com/zys743551828-art/tender-docs/blob/dev/05-技术与设计/工作台运行与验收.md)与代码同步。以下旧交接及 backend/frontend 是历史来源，不要求切回旧分支。

# tender-app

施组（施工组织设计）投标评审工作台的代码仓库。目标是中标：上传招标文件与技术标正文后，系统自动评审，给出废标／否决风险、强制性要求的响应矩阵、前后矛盾与范围残留、评分预测（未校准的估计）和报价模拟，并导出 Word 评审报告与批注版 PDF。

| 目录 | 内容 |
|---|---|
| `backend/` | FastAPI 模块化单体、PostgreSQL 迁移、任务与消息 worker、自动评审流水线，见 [backend/README.md](backend/README.md) |
| `frontend/` | React + TypeScript 前端，见 [frontend/README.md](frontend/README.md) |
| `deploy/` | Docker Compose、镜像与运维脚本，见 [deploy/README.md](deploy/README.md) |
| `contracts/` | `schema.sql`（与 `backend/migrations/sql/0001_initial.sql` 逐字一致）、`openapi.json`（由代码生成）、`domain.schema.json` |

质量门：后端 `ruff`、`mypy`、`bandit`、`pytest`（真实 PostgreSQL）；前端 `npm run check`（格式、lint、类型、测试、构建）。契约文件由 `backend/tools/export_contracts.py` 生成，测试校验它们与代码一致。

相关仓库：`tender-docs`（产品、研究与技术文档）、`tender-design`（设计稿）、`tender-research`（规则解析、评分预测实验）、`tender-datasets`（评测数据集）。


## 团队运行反馈与配置边界

[正式排障说明](https://github.com/zys743551828-art/tender-docs/blob/dev/05-技术与设计/团队运行故障排查.md)对照了旧 backend 与当前 workbench。根 deploy/Compose 是历史系统，不要混用 PG16/PG17 或 BIDWB_STORAGE/OBJECT_STORE 配置。根 Settings 不自动读取 .env；由已有启动器明确注入。virtual S3 兼容端点不能含桶名前缀；当前同源上传不要求开放桶 CORS。SDK仅必要 checksum、Worker安全阶段日志和严格规则失败分类由离线回归覆盖，未实际连接团队 OSS 或调用模型。不要提交或记录秘密及完整签名 URL。
