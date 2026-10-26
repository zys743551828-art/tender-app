# 完整材料 /3 与原始响应交接

## 本阶段实际闭环

从远端已核对的 `3f042fb` 开始，fusion 目标仍为 `462ec226`，无并行覆盖。

复用已有 `MaterialInput`、`CurrentMaterial`、`PageAssetBundle`、`PreparedCompleteVisionRequest`、`CompleteJudgmentAttempt` 和原三槽聚合器；复用 `PrivateContentStore` 与 `package_material_archive`。没有改写这些冻结协议，也没有把完整多来源 `/3` 转为单来源 `/2`。新增的 `/2` 交接封套版本只负责存储引用、幂等命令和消费入口，不另造模型、条款或来源身份。封套字段和消费边界见[协议说明](../../packages/contracts/package-complete-feature-handoff.md)。

受控生产端调用 `package_complete_handoff.save_source`，把现有 typed `/3` 输入和尝试记录写入已有私有 CAS；现有历史研究 CLI 用 `complete-feature-freeze` 发布命令记录，`complete-feature-read` 重读复验。Python 消费端 `load` 返回完整复验的 `MaterialInput`、原尝试记录和各规则 `/3` 非数值特征，后续研究装配可实际消费原件与回执，不只是查看摘要。

这不是原生数据库／真实模型运行端的自动接线：上游必须已有受控获取的 typed 输入和原响应，当前正式生产者仍未自动调用此入口。独立 binding 的原生存在性、最新范围／权限、原始模型调用真实性、标签准入和训练／评分资格仍未授予；所有相关标志明确为 false。

## 字节、身份与原子性

- 原材料归档 `/1` 原样保留上下文和页图；它的 `original_pdf_bytes_copied=false` 仍只描述原归档。新交接另存明确原件引用，包含完整原始 PDF 字节，而非把原归档的声明偷换为已复制。
- 保留原 acquisition observation、输入 metadata 和 binding；每张页图／裁片、每份原件、请求 body、原请求 receipt、原响应 body 与解析元数据均用现有 CAS 内容寻址。请求和响应原字节不重新编码。
- 保存前持有尝试列表、请求回执和解析 JSON 的独立副本；frozen dataclass 内部可变字段不能被上游在验证后改写并混入落盘。生成前与重读时均重建原 `/3` 上下文和输入，重用原有材料、图像、完整来源与模型请求校验。原响应用原 codec 重新解析，与完整解析元数据作 canonical 比较；模型名、request ID、response ID、usage、原响应摘要、内容及资格字段不允许漂移。
- 每个纳入规则必须有完整三槽；漏规则、缺槽、unknown、调用或响应身份复用、成功槽重复执行、错条款、错请求均不能发布完成交接。不补零、不截断、不提供数值预测或精度。
- 已有 `/3` 记录中 failed／unknown 且无 generation 的尝试只保留其原状态，不伪造响应。已返回且语义不合格的 generation 原字节也会保留。传输失败的独立错误正文／真实费用账本不在现有 typed 记录中，本阶段没有声称归档了未提供的数据或接通账本。
- 验证完成后先写 CAS 对象并读回，再发布 source commit；对象写入中断不产生完成 source commit，孤立对象不授资格且不自动清理。命令索引在私有目录锁下以临时文件／fsync／rename 发布，同命令相同记录幂等，不同来源或正文冲突；锁最多等 5 秒，未取得则安全失败。丢 ACK 用原命令恢复，不覆盖旧结果。
- 重读要求独立保留的 source commit、input、binding、feature method、handoff method 和命令记录摘要；重新生成整份源引用清单、特征及命令记录比较。即使攻击者给篡改封套重算外层哈希，原件／模型／范围／响应内部绑定仍必须通过。旧版本／方法保留但不冒用当前身份。

## 有界范围

继承已有材料限制（至多 32 份原件，每份 32 MiB、合计 64 MiB；至多 384 张页图／裁片、合计 64 MiB），交接另限制：最多 120 条尝试；单请求 48 MiB，唯一请求合计 96 MiB；单原响应 1 MiB，全部响应合计 32 MiB；接受的唯一对象合计 192 MiB；source commit 最多 256 KiB；最终特征对象最多 8 MiB。超限拒绝，不默默减少规则、响应或图片。CAS 单次对象读取仍受其原有 64 MiB 上限约束，读取后严格核对声明长度；这里不把接受字节预算当作进程峰值内存承诺。

CAS 复用既有当前 UID、0700 根目录／子目录、0600 单链接普通文件和逐层 NOFOLLOW；命令索引复用现有私有目录边界和最终路径 NOFOLLOW。没有修改 ACL、角色、网络或凭据。`/2` 与 `/3` CLI 参数相互拒绝，不允许隐式降级；native train/evaluate 仍不能导入这些无资格交接记录。

## 入口

```sh
.venv/bin/python deploy/package_history_worker.py --purpose complete-feature-method
```

冻结时提供：`--purpose complete-feature-freeze --material-store <已有私有CAS根> --artifact-dir <已有0700命令目录> --source-commit <生产端发布的固定commit> --command-id <固定UUID> --origin synthetic_mechanism|unqualified_research --expected-input-digest <独立输入摘要> --expected-binding-digest <独立binding摘要> --expected-feature-method-digest <已核对方法> --expected-handoff-method-digest <已核对方法>`。

重读使用相同身份参数，把 purpose 改为 `complete-feature-read`，增加 `--expected-artifact-digest <原ACK摘要>`。不接收原件任意路径、URL、pickle、DSN profile 或付费执行参数。CLI 输出只有回执；私有正文和响应留在 CAS，不进入日志。`save_source` 是上游 typed 生产端接口，不把任意上传 JSON 自认证成原生来源。

## 验证与下一项

明确合成的真实 PDF、页图和原响应通过实际 CAS、现有研究 CLI 和 Python 消费端往返，核对原件、请求／响应字节及特征完全一致；不是实际供应商执行或真实评分效果。新增反例覆盖错误独立摘要、原件／请求／响应／模型改写、伪造资格、重封装篡改、重复身份、预算、符号链接、并发冲突、中断和丢 ACK。

早期两个测试问题已修正：畸形响应实际抛出原 codec 的 `VisionProviderError`；丢 ACK 注入最初误伤 CAS 对象 rename，修正为只针对命令索引发布。其失败日志保留。相关最终回归 157 通过、0 失败／跳过（含新增 37 项，与全量重叠）；ruff／format（1090 文件）／mypy（680 源文件）／bandit 通过。首轮完整默认 4018 通过、2399 跳过；请求预算前移及调用方可变字段快照补齐后的最终完整默认回归为 **4019 通过、0 失败／错误、2399 跳过**，203.77 秒，5 条已有依赖警告。精确跳过原因随 summary.json 留存，原生数据库与真实供应商执行未运行，不能把跳过计作验收通过。本阶段无前端变更，未重复跑前端回归／构建。

下一项是把复验消费者接入受控历史研究材料选择与标签隔离，再推进分组、防泄漏的拟合／校准；原生登记和最新范围权威仍需现有用途接口装配及隔离原生验收。没有真实数据时只验证机制，不输出业务精度；不直接解除正式评分 blockers。

可复核本地样例及日志位于 `/workspace/scratch/tender-complete-feature-handoff-validation/`。`final-owned-synthetic-receipts.json` 指向最终源码方法的 source commit、命令和回执；此前样例保留为旧方法证据。私有 CAS 保存明确合成的 PDF／页图／请求／响应，CLI 与 typed 消费者均已实际往返核对。不得把这些合成字节或样例回执当作生产模型调用、真实评分效果或原生登记通过。
