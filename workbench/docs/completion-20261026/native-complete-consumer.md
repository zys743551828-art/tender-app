# 原生历史权威与 /3 实际消费装配

基于远端 `c70f4dd`，fusion 仍 `462ec226`，独立分支无并行变化。沿用原生 proof/admission/cohort、数据库分组/标签、独立训练 LOGIN、租约和原 results。没有接收调用方自称 verified 的资格。

实际代码闭环：可选原生 read_training `/2` 导出 → 隔离 train CLI → 私有 `/3` 复验并匹配原生范围/全部原件/工程项目 → 已有 CPU 拟合与校准 → 原 finish_job 结果存储。引用文件进入原 CAS；结果包含可复查引用和材料摘要。已扩展封闭 HTTP 结果契约、生成的 OpenAPI/前端类型与结果展示；前端核对回执分母及 admission/proof 与所选 cohort 的一致性，拒绝资格升格或额外字段，并明确提示特征未参与拟合。新增 SQL **未执行**、不在 BASE、无 GRANT；仅支持保护封存前的全新库。详见 [消费协议与入口](../../packages/contracts/package-history-complete-consumer.md)。

完整材料路径由现有 train CLI 的显式引用参数启用；现有自动 dispatcher 不会自行选择或推断引用。自动冻结引用到调度任务的接线仍待编码。

本阶段仍为常数基线，特征不参与拟合。现有原生 constant baseline 的 final 预测冻结/open_final/read_final/evaluate 流程保留；没有新增最终侧 `/3` 特征消费或正式模型资格。完成任务重放要求查询原 job_view 核对已保存摘要，不把新引用误记为已验证。

最终完整默认回归：**4079 passed / 0 failed / 0 errors / 2402 skipped**，254.67 秒，5 个既有依赖警告；新增 Python 机制测试 26 项，新增原生测试 3 项跳过。较早相关回归 163 passed / 3 skipped，最终 focused 26 passed。前端全量 **1873 passed（186 文件）**，新增 7 项；format/lint/typecheck/build 均通过，只有既有大分块提示。后端 Ruff、format（1096 文件）、mypy（683 文件）、Bandit、diff check 通过。

交付复查发现旧封闭 UI 契约不接受新回执，已补齐 schema/展示并在构建后重新运行上述完整后端回归；没有以先前回归替代最终验证。初轮测试 import 排序问题已修复。没有最终失败测试。

合成测试使用真实 CAS/原件/原响应及既有 CPU，数据库通道模拟明确不等于 PG 权限/事务验收。2402 项跳过不是通过，其中本阶段 3 项需 `FUSION_PACKAGE_HISTORY_COMPLETE_PG=1` 的显式临时 PG17 环境。没有执行新 SQL、下载镜像或调整网络/权限。真实质量数据、Word03 和生产验证未运行。

可审查补丁 `/workspace/scratch/tender-native-complete-consumer.patch`；日志、JUnit、完整跳过原因、静态检查、前端构建及方法摘要在 `/workspace/scratch/tender-native-complete-consumer-validation/`。

## 特征感知训练与 final-test 的最小完整设计（待实现，非冻结协议）

1. **无标签特征定义。** 独立版本化 `/3` 数值 schema，明确每个输入列及缺失否决。可评审候选为声明 band 顺序的标准化位置、三槽最大一致率、specificity/validity/consistency 的 supported 率和 uncertain 率；规则聚合权重只能取冻结规则的明确 maximum。顺序特征不等于官方得分区间。单 band、无法比较的量尺、无明确 maximum 或不完整三槽拒绝，不猜计分。特征构建函数不接收标签对象。
2. **复用训练算法而保留方法身份。** 现有通用 statistics 固定旧四维 schema，不能直接调用或补零。增加明确 schema 分发与独立方法快照，复用项目加权、线性求解/候选选择和 group conformal 计算；原四维协议路径继续独立。fit 学参数、development 只选冻结候选、calibration 只定区间，所有预处理仅用 fit；完整样本分母和项目闭包来自原生 cohort。
3. **原生结果协议必须一起改。** 当前 finish_job/start_job 只接受 constant model 并据 constant 冻结 final predictions。特征模型需要版本化 protocol/result/prediction 校验与消费函数，不能只改 Python 输出或直接删除 SQL 限制。材料/特征/方法摘要必须与模型、独立 final 预测清单共同固定。
4. **final 特征与标签分开。** 在 open_final 前，受控入口只消费固定 final 成员的 `/3` 特征并保存逐成员预测/失败状态及分母；不读取官方 final 标签，不因失败移除成员。随后复用现有独立曝光事务、另连接 read_final、evaluate 和原结果库。重复、跨项目组、关联闭包、跨通道曝光、迟到材料与模型/范围漂移均保持否决。当前权限下尚无该 final `/3` 导出/预测写入路径；新增版本设计需审查，不在本阶段授予任何权限。
5. **恢复与验收。** 引用/模型/预测写入必须由原生命令幂等键和租约 fence 绑定，丢 ACK 读取原结果；合成测试证明路径和隔离，真实独立效果、发布认证另行验收。没有真实配对数据时正式输出仍 unavailable。

下一可实施代码：先按独立版本 schema 实现纯 `/3` 数值投影与标签不可达接口及反例，再复用既有算法完成特征模型研究消费；原生 final 导出/预测冻结与已有部署迁移另列为具体代码工作，不能归咎于 Word 镜像缺失。
