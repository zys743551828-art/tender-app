# 原生证据独立审核回执

两个独立purpose LOGIN分别调用scope_review_issuer.attest_native与read_native。初始化者配置主体profile及准确登记的case，运行时不得建权限、切角色或自配身份。profile固定主体、来源、方法、库OID／名称、有效期；case固定原生登记ID／摘要、context及完整审核清单，当前启用状态与修订号分开观察。

回执引用版本package-native-evidence-attestation-reference/2闭合为context、review、findings及其方法、native store方法、storage record ID／摘要／packet、registration ID／摘要／方法。SQL对照准确v2登记、真实存储记录与完整报告原生对象；不接受旧findings_commit_digest。Python先完整复验当前恢复的context／报告与同一存储，允许当前恢复观察时间不同，但不改登记保存的原观察。

服务器生成package-native-evidence-attestation/2的回执UUID、时间和实际session_user，写入不可变表。调用方须事先持久固定逻辑command；同命令准确重放返回原事实，其他case／内容／主体冲突。独立读取者可按bid／command／引用摘要查回未知结果，再观察当前profile／case有效性、修订与精确不可变事实。撤销／替换不改原事实，重放不表示当前可用；新签署在失效时拒绝。

配置身份不等内容真值、必要范围、输入资格或执行；回执和观察全部资格false，原生读取不查当前业务来源。人工、程序和外部回执的身份形式保留配置含义，合成配置不得冒实际审核。后续资格必须另核当前来源、可信处理程序、完整声明及政策，发送还需原生费用和lease。新增SQL仅全新独立检查库可选安装，旧文件CAS回执、方法、SQL和记录保持。
