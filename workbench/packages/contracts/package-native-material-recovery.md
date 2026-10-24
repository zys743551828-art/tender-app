# 原生材料恢复

恢复控制器 `package_material_recovery.py` 在[私有归档](package-private-material-archive.md)之上保存独立恢复封套，不改归档、原材料、解析、模型请求及特征方法。封套及恢复回执均不授原生登记、必要范围、输入、执行或历史资格。

`save` 先验证完整 `/3` context，再保存其归档与原取得观察记录，最后发布封套。闭合字段为 `version=package-native-material-recovery/1`、`method_digest`、`context_digest`、`material_commit_digest`、`observation_object={sha256,byte_size}`，及 false 的 `native_binding_verified`、`input_authority_granted`、`execution_authorized`。原观察规范 JSON 最多 2 MiB，内容对象摘要包含其自身 digest 字段；记录内部观察摘要按原规则排除该字段。原观察对象不包含私有定位或原件字节。

方法摘要固定恢复源码、归档、context、当前材料、准确解析、scope、原件集合与定位方法及容量。恢复时必须使用相同受控方法；代码变化不回填旧封套，须明确重新核验和保存。调用方必须独立固定恢复清单摘要、context 摘要及项目／scope 身份，不接受 latest、推算解析身份、任意原件集合或来源资格布尔。

`restore` 使用三个独立非 owner 连接，分别执行既有 scope、原件定位、准确解析目的端口及其原生权限审计；无新增 SQL、LOGIN 权限或直接业务表读取。先核封套、原观察与归档摘要，再核当前完整两包／清单／规则／身份、准确冻结解析和完整来源图。随后重新完整 GET 全部当前原件，读完再核解析、scope 与每份定位。每次 GET 期间全部连接 idle；取消、撤回、项目关闭、内容／图变化或缺件整批拒绝，不返回部分 context。

冻结解析页由数据库不可变保护。读取投影故障单独注入验证，不能为了测试绕过该保护。相同原件若有多个文档身份，仍保留各自绑定，不能用文件摘要合并身份。

通过后以原观察元数据、归档 context 与页图、重新读得的原件重建原 `CurrentMaterial`，调用完整 context 验证器，确保恢复出的 context 规范字节及其摘要完全一致。原 `input_as_of`、冻结观察时点及解析 ID 不更新。当前原生事实另存 `package-native-material-recovery-observation/1` 回执，包含新旧观察摘要、固定封套／context 摘要、实际新观察时间及明确的资格边界。

归档页图不重新渲染，完整 PNG、manifest、原件摘要／长度与原生页几何仍逐项核验。新回执只证明本次重新观察与字节一致，不能代表两次查询之间原子有效、持续授权、发送租约、可读性核验或可信渲染隔离记录。相同完整 context 可形成完全相同的 `/3` 请求字节；演示用 binding 引用仍是合成引用，不升级为原生登记。

范围外：自动 Worker 重启／恢复调度、必要范围证明、独立输入登记、发送前 CAS／lease、token／价格与费用账本、真实模型调用、真实评分精度及浏览器视觉。原生恢复可由后续受控 Worker 调用，但当前没有向 API 或 Worker 暴露开关。
