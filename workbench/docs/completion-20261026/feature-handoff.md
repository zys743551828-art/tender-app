# 私有三槽特征冻结交接

## 最小交付与边界

从已推送的 `529afd4` 开始，远端独立分支、fusion 目标仍分别为 `529afd4`／`462ec226`。复核发现 `/2` 非数值投影计算与 `/3` 完整材料三槽计算均已存在；现有历史 CPU 原生协议仍是无特征 mean／median 基线，未接特征登记。没有重复实现特征计算，也没有把任意 JSON 当原生输入权威。

本阶段在**既有 `deploy/package_history_worker.py` 研究命令行**增加 `feature-method`、`feature-freeze`、`feature-read`。完成的是 **`/2` 研究投影 → 既有三槽计算 → 私有文件原子持久化 → 独立身份重读／重算 → 研究消费者取得冻结数据副本** 的闭环，不是数据库登记、历史模型拟合或正式评分。`/3` 完整材料不能静默降级成 `/2`，也未声称完成其持久化装配。

选择本地研究入口的原因：现有数据库训练包不接受特征，正式评分仅开放隔离机制；新增登记 RPC／授权或把特征塞入旧基线协议都会跨越本轮限制。没有新增 SQL、角色、GRANT、凭据或 HTTP 入口。界面没有虚构“已正式校准”的操作。

## 冻结和恢复

- 调用方必须提供独立保留的 projection、完整 binding、feature method、handoff method 四个预期摘要，以及固定 UUID command、明确来源（`synthetic_mechanism` 或 `unqualified_research`）。重读另需原 ACK 的 artifact 摘要；不能仅对收到的包自算摘要就授予资格。预期值只证明本次显式绑定，不代表服务器原生登记或当前在线资格。
- 复用 `package_technical_features.build_features` 的封闭 `/2` 协议、完整来源身份、三槽／重试／调用响应唯一性、证据闭包。缺槽或 unknown 导致 partial 时，交接层拒绝发布，不补零、不插值、不输出精度。源包里的官方标签、额外资格字段或旧版本继续拒绝。
- 新封套 `package-history-feature-handoff/1` 包含完整投影、既有非数值特征、方法与来源摘要。训练／metrics／正式预测资格恒 false，模型调用与费用恒 0。`load` 仅返回复验后的独立研究数据副本，不把特征包传入旧 CPU trainer。
- 用户预先选择已有、当前 UID 所有的 0700 目录；源文件和交接文件要求 UID 一致、0600、普通有界文件。不修改已有权限、不追随最终路径符号链接，FIFO 立即拒绝。通过 directory fd 固定目标，文件名只来自 UUID。
- 写入唯一临时文件并 fsync 后，以无覆盖的原子 link 发布 `command-id.json`；同命令同字节返回同一摘要，冲突拒绝，多个并发调用只产生一个正式文件。发布后 fsync 目录。发布前失败不出现半份正式包，发布成功但 ACK 丢失可用原命令重试恢复。
- 重读校验文件摘要、来源／范围绑定、两种当前方法身份，再从冻结投影重新计算特征并逐字节比较封套。篡改特征后重新计算外层哈希、陈旧范围、方法改变、伪造训练资格均拒绝；保留原件供审查，不自动迁移。进程被强制终止可能留下 `.pending-*`，这些从不作为正式交接读取，也不自动删除其他进程文件。
- 命令行在清空业务环境的独立 Python 子进程中运行，不接受 DSN profile、原生验证参数或训练 job。输出只有回执和计数，没有原文、判断理由、证据或特征明细；私有明细只在指定交接文件中。直接调用内部 child 且携带额外环境变量也拒绝。

## 使用方式

先查询当前软件方法身份：

```sh
.venv/bin/python deploy/package_history_worker.py --purpose feature-method
```

在调用方独立保留投影及 binding 摘要之后，使用下面的参数接口（占位符须替换，不能由任意收到的文件自授原生资格）：

```text
--purpose feature-freeze
--artifact-dir <已有0700私有目录>
--projection <0600投影JSON>
--command-id <固定UUID>
--origin synthetic_mechanism|unqualified_research
--expected-projection-digest <独立预期摘要>
--expected-binding-digest <完整binding的独立预期摘要>
--expected-feature-method-digest <已核对方法摘要>
--expected-handoff-method-digest <已核对交接方法摘要>
```

重读保持相同身份参数，将 purpose 改为 `feature-read`，移除 `--projection`，增加 `--expected-artifact-digest <原回执摘要>`。ACK 丢失时重复原 freeze 请求；不能换 command 或覆盖原文件来猜测结果。Python 研究消费者通过 `package_feature_handoff.load` 使用同样预期身份获得复验数据；没有正式训练资格就不能送入正式训练器。

## 验证与剩余项

专项使用明确合成投影，真实执行现有命令行、私有文件落盘和重读；覆盖并发同命令、冲突、丢 ACK、发布前中断、陈旧范围、方法漂移、重算外层哈希的篡改、权限／符号链接／FIFO、缺槽、unknown、重复调用、额外标签以及日志脱敏。早期 1 项测试误把结构化错误码当异常消息匹配，已改为断言 `.code`；产品冲突拒绝本身正常。

后续复验发现真实并发缺陷：发布者清理临时硬链接会使 inode 的 ctime 改变，其他同命令读取因此误报 FILE_CHANGED。修正为仅允许保持大小／mtime／UID／权限不变的 2→1 链接清理；读取后的独立摘要或确切字节比较仍必须通过。新增确定性清理时序反例和读取中权限变更反例，确保不靠并发偶然通过。此前相关组 1 失败／187 通过的日志保留，不能算作通过。

修复后的最终相关回归 190 通过、44 跳过（包含新增 41 项；与全量重叠）。ruff、format（1087 文件）、mypy（678 源文件）及 bandit 通过。首轮完整默认后端 3978 通过、0 失败／错误、2399 跳过；补充空参数拒绝及并发修复后的最终完整回归为 3982 通过、0 失败／错误、2399 跳过，185.55 秒；5 条已有依赖警告。跳过项精确原因保留在 summary.json，不能计作原生验收通过。本阶段无前端代码改动，未重复跑前端回归／构建。

协议说明见 [私有交接契约](../../packages/contracts/package-feature-handoff.md)。可审查样例在 `/workspace/scratch/tender-feature-handoff-validation/`，包含显式 synthetic projection、真实 CLI 生成的私有包及 freeze／丢 ACK replay／read 回执。没有运行原生数据库、真实模型或付费调用；没有将合成投影称为业务实测样本。

仍需：`/3` 完整材料及原始响应的版本化持久化交接、独立原生登记与当前范围权威、真实三槽运行／费用回执装配、带分组防泄漏的历史特征拟合／校准和发布权限。当前交接包明确不进入原有 native train／evaluate 流程；真实评分效果与精度仍没有证据。
