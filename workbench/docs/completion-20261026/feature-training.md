# 版本化特征感知研究训练

基于远端 `1526a4c`，核对独立分支/fusion 无并行变化。实现六维明确数值档位/三槽票数投影、fit-only 项目加权变换与岭回归、固定 development 选择、独立组 calibration；在现有本地 CLI/CAS 和原生训练运行器/结果库中实际消费，不只增加交接函数。新候选与旧常数基线并存且独立标识，旧方法源码/摘要未修改。

[完整协议和命令参数](../../packages/contracts/package-feature-training.md)说明精确特征、固定 alpha、最低组数和不可用行为。CLI/UI 均明确候选状态；不足条件不输出模型或区间。模型参数确实由特征拟合，但正式预测、模型/样本/指标资格保持不可用。

本阶段 **未接 final-test 特征消费**。现有最终评价仍是原常数基线，界面已明确区分；不能拿它宣称新候选经过独立评价。未执行生产/付费模型、SQL 部署、权限变更、PR 或合并。

最终默认后端回归 **4106 passed / 0 failed / 0 errors / 2402 skipped**，340.36 秒，5 个既有依赖警告；新增 27 项 Python 机制测试均包含其中。此前 focused 25 项通过，新增权重反例另通过 1 项，最终回归包含全部后续变化。前端全量 **1884 passed（186 文件）**，新增 11 项；format/lint/typecheck/build 全通过，仅既有大分块提示。后端 Ruff、format（1100 文件）、mypy（685 文件）、Bandit 和 diff check 全通过。初轮未使用 import 和测试格式问题已修复，无最终失败项。

2402 项 skip 为未验证覆盖，不计通过；未启用原生 PG17/S3，native finish_job 路径本轮为明确通道模拟。真实模型效果、真实独立配对数据与候选 final-test 未验证。没有为此调用模型、访问生产库或更改权限。

可审查补丁 `/workspace/scratch/tender-feature-training.patch`；完整 JUnit/summary、逐项跳过原因、前后端日志与方法摘要在 `/workspace/scratch/tender-feature-training-validation/`。

新增机制测试包括：完整 `/3` CAS→CLI 数值拟合→持久化→重读重算、原生通道模拟到原 finish_job、规则最大分权重、声明尺度不支持、组数不足、仅 fit 统计、development 不重拟合、calibration 不影响模型/选择、跨项目/组与 final 标签拒绝、重复输入、方法/向量漂移及封闭 UI 反例。合成文档、标签及组声明不是实际统计独立性或效果证据，未据此选择或宣传模型效果。

剩余实际代码：原生候选方法/模型登记的版本化协议；final-only 特征导出及封存预测后的一次性标签评价；自动调度引用和方法固定；已有部署安全迁移。原生环境和真实效果验收另列为未完成，不能用它们解释上述代码尚未实现。
