# FR 有限清单与正式预测权威缺口核查

核查基线：`c2557642895bfd7a05bc2ad506c95ee1cfd8ca88`。参考本地 tender-docs《一期方案与验证计划》4.1/4.3/8.3 与 DEC-010/015/016；其 project 路径是历史规格，以下映射到当前 bid/package 实现。此表是源码范围核对，不是逐条用户验收签收，也不凭路由存在认定所有语义已通过。

| FR | 需求 | 当前源码证据 | 编码/验收结论 |
|---|---|---|---|
| 001 | 废标/否决检测与提交闸门 | `review_routes.py`、`bid_package_review_run_routes.py`、`bid_package_submission_routes.py` | 核心/整包评审及 preflight/提交代码已有；真实参考标注召回误报与整包正向提交未完整验收 |
| 002 | 评分预测 | `scoring_producer.py`、`package_scoring_producer.py`、`package_feature_training.py`、`package_feature_final.py`、`package_feature_evaluation.py`、`registry.py`、`review_views.py` | **不完整**：研究拟合/冻结/独立评价及获批材料调用已有；正式 certification 签发、业务消费者与 UI 正向路径尚缺，未校准合计也不能通过硬改 unavailable 获得 |
| 003 | 响应矩阵 | `review_routes.py` 的 `/reviews/{id}/matrix`、`review_views.py` | 有实现；真实正文与条款覆盖的用户验收未完成 |
| 004 | 前后矛盾检测 | review producer/checks、`review_routes.py` findings、问题复核 | 有检测/发现/复核链路；真实性与漏报误报未验收 |
| 005 | 范围残留检测 | 同上及 package scope review | 有范围核对链路；真实复杂材料未验收 |
| 006 | 报价模拟 | `pricing_routes.py`、`package_pricing_routes.py` | 有公式、模拟与保存入口；实际价格样例组合验收仍需执行 |
| 007 | 报告与导出 | `bid_package_report_routes.py`、`package_report_docx.py`、生成/渲染检查 | 有受限富内容闭环；Word03 真转换/目录页码/完整正向导出未验收；支持范围外明确拒绝 |
| 008 | 规则与事实 | `human_routes.py`、rule correction、fact scope/change routes | 有确认/更正/撤回/审计；完整用户组合验收未完成 |
| 009 | 结果登记与校准 | `research_routes.py`、`metrics_routes.py`、历史/feature 研究消费者 | 结果与研究代码已有；真实效果未验证，业务校准消费依赖 FR-002 |
| 010 | 问题复核与改稿 | `human_routes.py`、authoring exact revisions/rich、原子多节点修订 | 有可恢复修订/复核；真实用户验收未完成 |
| 011 | 度量 | `packages/metrics`、`metrics_routes.py`；契约 needed_pairs=20 | 有结果/配对/指标代码；真实预测配对入口依赖 FR-002，不能制造数字证明完整 |
| 012 | 项目/资料/自动评审流水线 | main/document parse/review coordinator、Worker、outbox、material runtime/host | 有持久任务与恢复代码；原生 PG/S3/Kafka、真实 sender 联合验收未运行 |
| 013 | 项目功能开关 | `settings_routes.py` 与 UI/隐藏投影 | 有设置及隐藏控制；新正式预测正向展示仍须随 FR-002 联合验证 |

NFR：证据身份、冻结/幂等、失败关闭、认证审计、数值/时间及窄屏/可访问性已有代码与历史测试；无真实环境组合验收，不能标全通过。未新增可选增强或升级迁移需求。

## FR-002 的确切阻塞证据

1. `deploy/sql/model-governance-release.sql` 15–17 行明确：当前没有 certification 签发函数，真实来源/独立验收/观察必须作为独立权威实现，不能由合成指标推断。certifications 只含 model/acceptance/scope/report/protocol 引用，没有有效期或撤销状态。
2. `packages/model_governance/RELEASE-DEVELOPMENT.md` 明确要求：正式认证额外绑定 final exposure 前冻结的业务门槛、真实用途来源、报告、观察与回退验收；训练协议不能替代。
3. `training.validate_protocol` 的封闭 `score-training-protocol/1` 是候选选择/拟合配置，不包含业务误差/增益/覆盖门槛。研究登记 API 将其 origin 固定为 synthetic。未找到已冻结的业务门槛协议或独立真实 certification 颁发者。
4. 原需求 8.3 要求“目标误差在最终测试前结合实际分差固定”，并未给出可以自行照抄的数值；20 组只是上线后在线监控门槛，不能用它批准模型。
5. 旧 registry artifact 使用 `complete-three-band-features/1`；新 `/3` 消费者使用 `package-complete-numeric-features/1` 和 `package-complete-ridge-model/1`。不得改 schema 标签或把新候选塞进旧 artifact，后续需显式版本化适配。
6. 当前受控 business route 只在已有 cert+accepted acceptance+real origin+scope 匹配时允许非空发布；score-execution 本身明确不签发 cert。直接写 design.model_acceptances/routes 不能替代受控 cert 链，也不能作为本任务的合成正例批准真实对象。

## 最小待决问题

请指定已有冻结业务准入协议的文件/版本；若不存在，是否采用“门槛值显式填写、无默认值，final 曝光前封存，绑定独立真实报告、影子观察、回退验收，记录有效期和撤销”的版本化协议？这只确定代码协议，不提供实际阈值、不批准模型、不启用调用。缺协议时不自行推定人工确认等于真实精度合格。

确认后有限实现顺序：版本化业务协议/认证生命周期 → 旧/新 artifact 的明确消费兼容边界 → 固定输入与受控 business route 的预测/幂等持久化 → review/API/UI/报告隐藏投影及 metrics 配对。沿用现有统计与冻结方法，不重新训练或根据合成效果选阈值。

## 本检查点产出与验证

本检查点仅做源码/需求核查及文档，不改执行代码，不铸造 cert，不绕过现有拒绝。已有上一阶段 4355 后端通过/2424 跳过、1944 前端通过不能称为 FR-002 正向路径验收。本次未重跑全量或原生测试；仅校验文档差异与引用文件存在。正式正向消费实现处于等待协议决策状态，未执行，不是工具拒绝或结果不确定。

## 2026-10-26 授权后的阶段更新

用户已批准上述无默认门槛方案，不再等待协议方向决策。[业务门槛冻结阶段](admission-protocol.md)已提供旧 registry cohort 的实际 API/持久化实现，尚未签发认证、适配 /3 或接通正式预测正向路径。原 FR 表编码/验收结论维持，FR-002 及其 FR-009/011/013 关联项仍未完整。
