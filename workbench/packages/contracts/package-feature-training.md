# 完整材料特征研究候选 /1

此版本实际拟合可复现的特征模型，但只形成研究候选，不进入正式模型/样本登记或评分路由。保留 `/3` 输入/特征和旧 constant baseline 协议，未改已有 statistics/CPU 方法源码及其摘要。

## 标签不可达的投影

`package_feature_training.project(CompleteResearchInput)` 不接受标签参数；重做原三槽聚合并核对保留特征。每条 included rule 必须有正的明确 max_points，以及至少两个数值不同、介于 0 和 max_points 之间的显式 band.points。文字区间、未知档位分值、单档或缺最大值均不可投影，不按顺序猜分、不借官方标签决定映射。

固定六维 `package-complete-numeric-features/1`：

1. 三槽声明档位 points 的平均值除以该规则 maximum。
2. 最大档位票数 / 3。
3. specificity supported 票数 / 3。
4. validity supported 票数 / 3。
5. consistency supported 票数 / 3。
6. 三种维度合计 uncertain 票数 / 9。

各规则按冻结 maximum 加权汇总；所有维度属于 [0,1]。这是原设计的受限具体化：优先使用声明的明确数值档位，**不**以任意 band 序号代表分值。返回原 input/features/method 摘要及投影摘要；任一 included rule 不支持时整份候选不可用，不删除失败成员。

## 固定拟合、选择与校准

`package-complete-feature-training/1` 固定岭回归候选 alpha 为 `10, 1, 0.1`，误差相同按此顺序选择较强正则化。没有根据合成测试结果搜索新模型或调参。复用原 `statistics.weighted_mean/solve` 与 `evaluation.project_mean`；不向旧四维 trainer 补零，不修改旧模型 schema。

仅 fit 项目计算加权均值、标准差、截距和系数，同一项目多记录共享总权重 1；近常数维度使用尺度 1。development 仅用项目等权 MAE 选择已冻结候选，不重新拟合。calibration 仅计算独立组最大绝对残差的 80%/90% split conformal 半径。预测统一截断到 [0,100]。

预设最少独立组数为 fit=3、development=2、calibration=9；9 是 90% 有限样本秩可获得半径的最低组数，不是质量充分性证明。项目不能跨分区或被拆成多个独立组；同一输入不能重复。沿用既有标签时间/提交分界检查。任何 final 标签、分母变化、未知来源或方法漂移均拒绝。没有有效变化、尺度不支持或组数不足时 status=unavailable，model/model_digest/selection/intervals 均 null；不保留一个看似可用的拟合结果。

成功时 status=research_candidate，保存模型参数、模型摘要、development 选择和校准区间；方法摘要绑定新投影/算法/消费源码、固定候选及已有方法。`features_used_for_fit=true` 只描述该研究候选。原件和 handoff 的资格 flags 仍 false，不据此授予正式训练样本、指标或预测资格。合成组声明仅证明机制；不能证明真实独立性或精度。

## 实际消费入口与旧版兼容

读取新方法：

```sh
python deploy/package_history_worker.py --purpose feature-training-method
```

在既有 `complete-calibration-freeze/read` 参数上增加：

```sh
--expected-feature-training-method-digest RETAINED_NEW_METHOD_SHA
```

仍需独立固定原选择/标签/旧装配方法摘要；重读需原 artifact_digest。新模式使用原私有 CAS 和原命令索引，结果同一个对象中包含旧 baseline 与独立 `complete_feature_training`。命令索引版本为新 training/1，同一旧命令 ID 不得覆盖。无此参数的旧模式不改变行为或方法摘要。回执的 `feature_candidate_status` 明确区分可用研究候选和不足条件；不会在 stdout 输出私有标签。

原生 train CLI 在既有完整材料引用参数上增加同一参数。运行器先执行上一阶段真实目的隔离读取/材料匹配，再从同一固定引用构建投影，使用 DB 导出的训练侧标签；用原 finish_job 存储基线和候选。候选 source_digest 必须对应原生引用摘要。材料文件不能提供 verified/current、标签或项目分组来替代数据库权威。已完成任务不能借新参数重训；读取旧 job_view 核对结果，新的研究只能遵守原生 cohort/曝光限制。

HTTP 旧 training-result/1 增加独立版本化可选候选字段；旧 baseline 的 model/model_digest/training_export_digest 不变。UI 分开显示候选状态、方法和原基线，核对模型摘要、来源/成员分母/项目组数量、选择和校准秩，拒绝资格升格或额外字段。原 native SQL 的模型字段仍只承认常数模型；新候选不是伪装成 constant 的替代模型。

## 未完成的 final-test 与自动化

`final_test_consumption=not_implemented` 是强制字段。现有 native start_job/open_final/read_final/evaluate 仍评价旧常数基线，UI 明示其不评价特征候选。新候选 **没有** final `/3` 预测冻结、一次性独立评估、发布或正式效果资格。

下一阶段需版本化原生特征候选协议/结果校验，提供仅 final 特征的受控导出、逐成员预测/失败状态与完整分母的冻结写入，再在不可逆曝光提交后复用独立标签读取与评价；禁止回传标签重选 alpha。自动 dispatcher 的引用/方法固定接线、已有部署迁移也尚未完成。本阶段未新增 SQL、权限或部署操作。
