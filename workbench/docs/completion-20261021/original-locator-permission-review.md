# 原件定位核验的权限审批范围

状态：用户已明确允许以下独立检查库范围。实现与验证见[受限原件定位验收](current-original-acceptance.md)；权限不安装到正常业务库。

## 允许执行的具体范围

只在现有`tender-fusion` Compose检查组的全新独立检查库实现、验证并提交以下可选扩展；默认BASE、正常业务库、API／模型Worker账号、旧dev／Claude环境和main均不调整。合成数据验证后清理检查库、临时LOGIN及本批能力组，停止检查服务。生产安装或对正常业务库授权不在本次申请范围。

| 对象 | 拟议权限与边界 |
| --- | --- |
| `tender_current_original_verify` | 新的NOLOGIN能力组，继承已有`tender_current_scope_verify`，不获得业务表直接读取／写入／CREATE或管理角色权限 |
| `fusion_current_original_verify` | 仅用于独立检查库的临时非owner LOGIN，继承上述两个能力组；凭据只在私有测试配置／内存，结束删除 |
| `current_technical_original.locate` | 新增单一SECURITY DEFINER只读RPC，固定项目／scope ID／scope摘要／文档ID／原件摘要参数及search_path；PUBLIC不可执行，仅新能力组可执行 |
| 继承的`current_technical_scope.observe` | 重用已验当前项目身份、两包／清单head、规则和阶段检查；运行角色不能拥有或通过继承拥有任一RPC |
| 私有返回值 | 只有确切原件的对象key、摘要、长度及必要元数据；key只交受控读取控制器，不能进入模型、界面、日志或Git证据，证据只保留定位摘要 |

原生入口必须先核对当前范围，再核对全部冻结来源的真实kind／用途／项目／摘要／head修订／有效期及完整祖先闭包。撤回、过期、额外祖先、来源变化、闭包超限、跨项目或不在原scope冻结文件清单中均拒绝。原件大小最多32MiB，定位信息最多4096字节；真实字节仍须后续完整GET逐字节校验长度和SHA-256，旧“登记时核验”不代替当前读取。

独立LOGIN通过共用只读权限审计，只能执行两个明确窄接口；其他表列、额外definer、继承管理角色及直接／继承RPC所有权都拒绝。没有运行时补权或角色切换。

## 风险及保留边界

这个扩展使一个新的独立核验身份能够取得受限的私有原件定位信息，属于实际访问边界扩大；不能仅以“只读函数”说明没有风险。SECURITY DEFINER内部使用初始化owner权限，必须逐项验证参数、完整闭包、搜索路径、正文和执行者权限，禁止任意SQL／表名／对象key参数。

本次申请只验证原生权限和合成定位／读取机制，不接真实OSS凭据或真实标书，不证明必要范围、原件历史存在性或正式评分资格，也不生成正式核验binding。已有GET传输继续保持`native_permission_verified=false`，不以本方案或调用方JSON代替许可。
