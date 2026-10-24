# 完整多来源模型材料与三槽位特征

`package_technical_material`提供独立`/3`协议，消费受控进程取得的`CurrentMaterial`和两份独立预期摘要。它核对原生材料／scope／两包／清单摘要、确切解析记录、全部原件字节、页图与几何，再冻结独立私有快照。正文、原件、PNG不参与repr；外部原对象或中间对象改变不应污染已核验请求。

上下文完整保留原生材料、全部页／块／表结构、人工排除和覆盖缺口。每条规则保留整个frozen_rule及全部source_evidence，逐项绑定准确依据成员、文档、原件摘要、解析、物理页、证据摘要与全文；纳入项的依据集合必须完整。条件、例外、档位标签／描述／原始分值均不改写。档位用原顺序及内容摘要形成`band/{ordinal}/{digest}`身份，重名档位不合并，零值原文保留，不据此计算总分。

`MaterialContext`不含核验回执字段。`bind_input`只接受`package-technical-verification-binding/3`的独立ID／非零回执摘要／确切context及方法引用，并检查调用方另给的预期摘要；重新核对全部材料和资产后形成`MaterialInput`。它只检查引用形状与内容对应，不证明ID在原生登记库存在；双方`native_binding_verified/input_authority_granted/execution_authorized=false`。现有原生登记与必要范围尚未装配，不得将调用方JSON或自算摘要当资格，不能从context直接准备模型请求。

`package_technical_complete_vision.prepare_request`仅接`MaterialInput`，将全部原生材料、证据目录、所有规则声明、指定纳入规则的完整依据／档位及输出schema写入实际正文；每张整页及裁片附准确映射，PNG以data URL实际内嵌。排除／待分类项仍保留在材料中，但不能准备判断请求。每图32MiB、总64MiB、384图、48MiB实际请求；15图及以上最大边4096，否则8192。先估算base64后的准确字节数，编码后再核对，超限拒绝，不截断、缩小或远程引用。model token上界、可读性及执行资格仍未授予。

新单次端口使用固定profile／地址，凭据由受控进程显式提供，不加载环境。复用纯配置校验和既有响应codec，保留原始响应、usage、模型／响应ID及摘要；仅一次POST，无重试／重定向／环境代理，identity原始响应最多1MiB，总async限时由显式配置确定。同步入口不在处理“无运行事件循环”异常期间执行请求，超时／网络失败丢弃原异常上下文，费用保持unknown。普通API及Worker未接这个端口。

`check_judgment`从固定输入重建准确请求并核对正文及完整回执，再重解原始响应，拒绝解析后对象被改写。条款、档位、覆盖章节、文档／解析／物理页／页图、逐字引文及区域坐标均核对；不能只替换回执把另一条款的答案算进当前条款。判断语义仍是模型输出，不因程序通过而证明实际正确性。

`package_complete_features.aggregate_rule`只汇总一个纳入条款的三槽位记录，不调用供应商或决定重试。每槽最多5次、整条最多15次、原始响应合计8MiB；实际call ID、响应ID、请求及完整原始响应均须唯一或准确绑定。unknown后不得继续同槽尝试，成功槽不能再试；明确记录的语义失败保留原响应，并可由外部控制器提供后续独立尝试。响应ID先核验后去重，畸形ID或原始响应篡改不得变成可重试的普通语义失败。

只有三槽均有效才输出非数值档位投票及具体性／有效性／一致性分歧；缺槽、无法判断、未知均保留缺口，features为null，不补零或推算整条／整包分。相同答案内容来自不同调用不代表统计独立。raw_numeric_total及formal_prediction始终null，正式预测／训练／metrics资格均false。

旧`/2`输入、序列化、判断、特征方法和历史回执保持原值。本扩展无SQL／ACL／公开HTTP变更，正常业务库不安装新权限。机制验收只使用合成资料、合成binding引用和显式MockTransport；原生登记、独立必要范围、发送前CAS／lease、token／价格／费用账本及正式Worker执行仍须装配与验收。
