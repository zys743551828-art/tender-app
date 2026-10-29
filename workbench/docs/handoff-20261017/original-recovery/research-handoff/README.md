# 调研与网络设置交接

官网访问在HTTPS代理CONNECT阶段被403拒绝。环境配置工具报告草稿基线过期，保存未确认；重复读取并原样提交不能修复，运行策略未改变。

请从当前环境设置创建新的设置会话，先读取当前草稿，将network-proposal.json的域名与新草稿已有自定义域名合并。仅更新network.allowed_domains；保留预设、仓库、安装脚本、启动说明与所有凭据要求，不提交密钥。旧草稿读到的自定义域名为claude.ai。新草稿可能有其他配置，禁止盲目覆盖。

官网需补查GovDash、AutogenAI、Trunk Tools、Document Crunch、Glean及云厂商客户技术案例。若进入Glean文档，需要另外按实际地址申请docs.glean.com；本提案完整保留已尝试保存的域名，不声称其已生效。

本包包含两份研究报告、固定来源清单、复核工具、70份公开来源缓存和辅助脚本，不包含真实投标原件或密钥。不要假定新会话能收到旧工作区。

sources/orchestration与sources/products分别对应两个专项清单。使用scripts/fetch_official_sources.py的--manifest和--cache参数核验或取回清单原文。该脚本沿用代理和TLS校验，不执行下载内容。check_design_assets.py依赖完整文档仓库，应在仓库目录内使用。

historical-helper中的脚本只为保留调研过程中的本地文件，不作为重现入口；其硬编码路径与初始下载集合不适合新会话。以正式清单和scripts/fetch_official_sources.py为准。

当前结论：业务事实、AI流程与后台运行分层；首版优先比较成熟队列和可替换AI模块；Temporal和Agent Server依实际恢复、许可及维护成本选择。行业闭源产品内部架构尚未核实，不据此冻结执行器。
