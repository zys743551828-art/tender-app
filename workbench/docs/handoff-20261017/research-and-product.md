# 产品、研究与既有模块的补充交接（PM汇总）

产品Owner与研究Owner早于本次六个活跃角色完成各自批次；此文件来自PM已收集的结果，不能冒充本次重新独立执行。完整原报告与源码均保留在文档仓库。

## 产品责任与剩余范围

产品Owner负责方案、40FR差距及交付排序；架构/开发/测试/用户均可评审但不替代Owner维护主规格。PM组织开发、测试及跨角色最终复核。最新版产品排期在 `04-验证与测试/a1-delivery-plan/current-implementation-review/`：

- `产品交付评审与排期.md`、`remaining-fr.json`：保留40FR，已纠正原FR4/5/20已有实现的重复排期，不能整体自动关闭。
- `A2完整成稿交接.md`：M1人工完整稿先于M2 AI；M1必须覆盖A2-FULL-01至07及09，M2补08。源码有按钮/独立8页PAGE不能替代整个成稿任务。
- `助手未知费用下独立新问题协议.md`：显式new_question不是独立性凭据；规范化正文/真实规范项目+业务对象+目的推导防重，nonce/context/source version/profile变化不能洗旧unknown；三桶最坏hold与缺可信价格/硬上限即pause。
- `design-remediation-checks/application-acceptance.json`：原13应用/用户任务仍以实际最终组合逐项执行。历史模块UI结果可按原范围引用，不直接把这里pending改为通过。
- `prd-checks/spec-followups.json`及PM产品变更链：前四条原样保留后追加score增量；静态54需求/128场景/75链接通过，不授软件整体通过。

## 研究固定候选

| 范围 | 候选SHA | 已知结果/下一步 |
| --- | --- | --- |
| HistoricalInput01 | `3d917c3190eca381e43d647bbf7a29422faebb1653605a45784a0a76e10fba45` | 19独立真实PG/ASGI/CPU机制；历史新入库不能倒造企业当年已知时间；当前普通评审与历史资格分开 |
| StageA | `3929d000…`（以原candidate全文为准） | 20源/26参考，49fresh受限用途隔离CPU训练/评测机制；显式合成样本，不是真实精度 |
| ModelRelease01 | `f4306991dafab46f6e1c9364132c0617ecfaeda16692bf2f02828df6da76e865` | 注册/shadow/suspend/rollback；正式资格必须另外cert，不由release存在授予 |
| ScoreExecution01 | `32893b6df6fe1d6f0b5485bb3191aa8b4987fee8d690d4062b842d206ba3f9e7` | 12独立PG/ASGI+单用途hardMock，完整范围三判断、unknown防补、重用6绑定、迟到usage/取消/历史；未真实provider |
| TechnicalScale01 | `9ad9becd41065d334ff03246026da4f9a79f90db89a5aa0696b3a0ada01c6f62` | QA10，真Word→受限DockerPDF→CPUparse全祖先权威/撤回；没有接分母/正式数值资格 |
| Denominator preflight01 | `74836e565e8071e1162989993e4fc8d18cadc4a353f6e0050aad70311f99063d` | 11源/9操作/28纯+B新库5PG，不是最终完整应用候选 |

原证据入口：`research-backend-checks/historical-input/`、`fr029-development-checks/`、`score-execution/`、`technical-scale/`、`score-denominator/`；对应独立检查分别在`historical-input-independent-checks`、`score-execution-independent-checks`、`technical-scale-independent-checks`等目录。原SQL A/B等被审阻塞稿与首失败都保留。

## 分母A/B/C精确历史

- A `21a41e3937a81dd2c8967360e7ef86b3ba1bf8dcffba4dbf0ecb164bf0811e96`：架构SB01发现header早建而决定晚确认可洗严格时点，A未执行。
- B `c3f3b86260e7c967e4e14ab63865955ad6c71df74bb43791743d435c9388bab2`：补decision.created_at≤实际提交，已在`score_denominator01`全新20SQL/7roles库执行并有5实际PG/API。原ScoreF maxNULL/旧结果/缺资格保持不变。
- C `e771ab52c25cbd19ac0e48f5732de051c2f8f5ecc7b6599a0f7064826b169195`：只修strict method应取cohort→research_run→experiments.method_digest，不能取普通review_inputs.method_digest。架构C已过，**未执行**。
- 已准备`integration-runtime-checks/create_score_denominator02.py`，新20SQL/C库，不能在B旧库执行增量补修。脚本SHA`5b2cca2f93c8e6d2b8a2b8aabc16551fef56acab69ec4fd46e1011b993e4aca1`，执行前逐字核验。

C之后需要真实clock顺序的合成验证：先当前权威max确认→真实提交→后来官方label→CPU训练/封存评测。不要回填2019时间来冒严格事前资格。当前label.maximum仍缺独立label scale权威，未完成前不得声称原始分/加权分可等价。

`deploy/sql/retrospective-research.sql`约43KB为未审WIP，**不得加进initializer**。回溯四时点有纯规则起点，group/label权威、sealed purpose exports、CPUrunner和官方labelscale仍待；回溯重建与真实未来预测必须分开，旧研究不可继承到新资格。

## 外部业务资料与费用

真实授权完整正文/官方技术成绩不足；CASE001既有两个内容寻址OSS对象观察404，不能把数据集README历史“可用”当本次已重新取得。原研究仓库保留历史方法/结果，资料清单仓库保留来源和校验，实际原件需另安全提供。真实精度/中标效果/复杂真实Word保真均未授通过。

原付费审批卡点仍在；一次322B OSS恢复授权不涉及任何模型调用。不得启动真实研究/评分/助手消费者补验。软件其余部分可以继续，最终交付须同时明确软件验收、模型质量与资料缺口。
