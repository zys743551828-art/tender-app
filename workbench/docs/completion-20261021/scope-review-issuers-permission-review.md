# 独立审核主体与核验读取权限

可选 SQL 只在全新独立 Compose 检查库初始化，不加入 BASE 或正常业务库。新增 `tender_scope_review_issuer` 和 `tender_scope_review_verify` 两个 NOLOGIN 组，各有独立非 owner LOGIN；审核主体只有 attest RPC，核验读取者只有 read RPC，无直接表／列／序列、业务、官方成绩或其他用途角色权限。发行主体不能读取核验入口，也不能改自己的配置或任务授权。

配置及准确任务由初始化 owner 提供：不可变 profile 固定真实 LOGIN、主体 UUID、来源种类／模式、权限政策摘要、报告方法、数据库身份及有效期；可撤销 head 指向当前 profile。不可变 case 固定 profile、已登记材料 ID／摘要、准确 context／清单及有效期，另有可撤销 head。没有请求字段可以选择主体、模式或授予资格。生产审核主体尚未配置，测试全部使用 synthetic_mechanism。

权限与实际方法在 Python 端及原生 SQL 双层核对。SQL 策略 helper 无 PUBLIC／运行角色 EXECUTE，只有受控函数内部使用；递归有效成员必须恰好属于本用途组，无 CREATE、直接表／序列权限或其他 SECURITY DEFINER 入口。三个原生函数的正文、语言、执行模式、search_path、UTC 设置及 owner 必须与源码和受保护配置表／schema owner 相符，运行时不修复权限。

先将准确报告引用与命令保存到私有 CAS，再由实际审核 LOGIN 出具不可变原生声明回执。原生时间、主体、任务、材料引用均来自数据库。相同命令完整重放，写结果不确定时独立读取者可按固定命令及引用摘要查回；撤销配置改变当前观察，不改写旧回执。当前来源、内容真值、实际人工阅读与正向输入仍未由该身份端口核验，必要范围／输入／执行位固定 false。

检查使用合成材料和独立 test LOGIN，owner 只做新库初始化、任务配置及受控权限反例；所有声明由实际独立 LOGIN 写读。结束清理检查库、LOGIN、六类核验组并停止检查服务，保留正常预览和 Word。真实主体配置、生产权限安装、外部平台签名验证及正式评分不在本次执行范围内。
