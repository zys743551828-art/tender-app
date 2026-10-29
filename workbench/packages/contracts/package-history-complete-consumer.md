# 原生历史训练消费完整材料 /1

这是原生历史 **常数基线** 的可选材料消费路径，不是正式评分或 `/3` 特征感知模型。复用现有 admission/proof、cohort、purpose LOGIN、租约、训练/评价导出和 results；没有第二套原生资格表或结果库。

## 信任入口与持久化

`package_history_runtime.run('train', ..., complete_material=config)` 只通过既有隔离 `connection('train')` 调用数据库 `read_training`。文件不提供训练标签、项目分组、verified/current 标记。可选数据库导出 `package-history-complete-training-export/2` 保留原 `/1` training_export，另附训练侧 admission/proof、工程项目、精确 scope/manifest、原件身份及官方标签文件身份。数据库先执行现有 `assert_role`、`assert_lease`、`current_cohort`，后者复核 proof、来源和跨通道曝光。最终侧/排除样本不在此材料导出中。

适配器对每个 admission 执行原有 handoff.load 完整 `/3` 复验；要求 DB 工程项目及提交时点、bid/scope/摘要/manifest、全部原件 ID/字节数/SHA 一致。禁止同一输入、调用或响应复用、项目/组跨用途、任何所选样本的官方标签文件 ID 或字节 SHA 混入预测材料。原生 origin 与交接 origin 显式映射：synthetic→synthetic_mechanism，external_evidence→unqualified_research。后者仍不是 handoff 自授资格；资格事实来自受限 DB 读取。独立 Python 函数不是网络导入端点，伪造一个相同形状的 dict 不构成数据库权威。

材料匹配完才调用既有 `package_history_cpu.train`，保持原 training_export_digest、模型和协议身份；追加 `complete_material_consumer` 回执后仍用原 `finish_job` 存储完整 JSON。finish 再核验租约和当前 cohort，变更/撤回不能凭旧内存材料发布。引用文件写入已有私有 CAS，并由 DB 结果中的摘要绑定；丢租约可能留下无资格的未引用 CAS 对象。没有新的本地结果索引。

原结果 `/1` 上只增加可选、独立 version 的 `complete_material_consumer` 回执，封闭 HTTP schema 和前端读取已同步；旧结果无需该字段。前端要求回执 admission/proof 与训练侧 cohort 完整一致，展示引用摘要供完成任务恢复核对。

所有 handoff 权威/正式资格 flags 保持 false，`features_used_for_fit=false`，`formal_prediction=null`。这匹配当前 constant baseline：`/3` 只作为实际材料消费和核对门槛，不会把票数补零成旧正文向量。DB 权威并不认证模型输出质量或原始文字绝无间接标签提示。

## 可运行入口

先用 `python deploy/package_history_worker.py --purpose native-feature-method` 读取方法摘要。引用文件 0600、上限 256 KiB、至多 64 条，严格字段：

- `version=package-history-complete-consumer/1, method_digest, cohort_id, membership_digest, rows`。
- rows 每项只有 `admission_id, reference`；reference 沿用完整 handoff 的 source_commit、command_id、origin 和五个 expected 身份摘要，不接受任何标签/准入声明。

训练调用：

```sh
python deploy/package_history_worker.py --purpose train \
  --profile PRIVATE_TRAIN_PROFILE --job-id JOB_UUID --generation 1 \
  --complete-references PRIVATE_REFERENCE_JSON \
  --complete-material-store PRIVATE_CAS --complete-artifact-dir PRIVATE_FEATURE_INDEX \
  --expected-complete-reference-digest RETAINED_FILE_SHA \
  --expected-complete-method-digest RETAINED_METHOD_SHA
```

完整材料消费是显式 CLI 选项；现有 dispatcher 的无参数基线行为不变，不会自动选择引用。仅 train 接受这组参数。launcher 启动 `-I` 子进程，只传单用途 DSN 与固定 locale/TZ；不读取 `.env`。既有无材料参数的基线训练兼容原 `/1` 及可选 `/2` 包装；未安装扩展时携带完整材料参数的训练拒绝，不自动降级。

若同一任务已 succeeded，完整材料模式返回 `PACKAGE_HISTORY_COMPLETE_RESULT_ALREADY_FINISHED`，要求用现有授权 job_view 核对保存结果及 reference_digest；不会宣称本次不同引用已验证，也不会重复训练。运行中进程故障仍沿用原租约过期/恢复/fence 机制。

## SQL 版本化和权限边界

`deploy/sql/package-history-complete-material.sql` 是**未执行的可选全新库安装输入**，不在 BASE 自动安装列表。顺序：既有 admission/research → 此扩展 → exposure-bridge → 其他既有可选入口。扩展检查原函数体哈希、owner、语言、SECURITY DEFINER 和 search_path；拒绝已存在 cohort 或曝光保护的库。

只 `CREATE OR REPLACE` 已有 read_training 同签名函数，保留 OID/owner/ACL；无 GRANT、角色、凭据或新表。返回协议增加该任务的材料绑定数据，旧 `/1` 标签导出内容不变。曝光保护在随后安装时冻结新定义；不得修改或重新封存已安装 guard 来迁移。本阶段没有执行 SQL、部署、连接生产或授予权限。已有部署如何迁移是独立版本化工作，不能用此 fresh-only 脚本原地覆盖。
