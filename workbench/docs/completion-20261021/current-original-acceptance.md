# 受限原件定位与实际字节读取验收

用户已按[具体权限范围](original-locator-permission-review.md)允许在现有Compose检查组的全新独立库实现可选定位角色和窄接口。实现契约见[当前原件观察](../../packages/contracts/package-current-original.md)。正常业务库未安装该schema或角色，BASE仍37份SQL、design仍136表；正常API／模型Worker权限保持。

原生`current_technical_original.locate`复用当前包／scope核验，只返回原scope准确文件的私有locator和绑定元数据。全部原件与确切解析来源根、完整祖先闭包和每个来源的原生用途／项目／摘要／head修订／发布状态／有效期逐项重核。闭包采用有界局部遍历，拒绝循环、超过64层、20000节点／边／闭包行，不截断。原件最多32MiB，locator最多4096 UTF-8字节。

独立LOGIN只能继承两种固定能力组、执行两项明确RPC，无业务表直接访问；实际PUBLIC、继承、表列和definer权限接受共用审计。调用前核对两项RPC的完整正文和安全属性，拒绝直接及继承owner。定位只保存在不参与repr的私有字段，公开回执只有定位SHA-256，数据库异常不携带私有原生上下文；实现不加载业务配置或发现凭据。

最终Linux **104项，102.98秒**：28原件原生验证、21已有范围原生／API回归、35字节读取、8导入隔离及12编排；Windows **43项，2.96秒**（与Linux重叠）。四文件ruff检查／格式、两实现mypy／bandit通过。原件验证覆盖准确身份、整个scope其他文件的撤回／过期／未来／修订／缺失、额外祖先、真实65层深链、表列越权／PUBLIC／额外组／definer、两项正文替换／继承所有权、阶段、借用事务和异常隐私。

实际合成链在独立非owner LOGIN下取得locator，再通过真实回环TCP进行一次GET，identity原始响应完整长度和SHA-256匹配。原件合成内容61字节；未验证真实PDF质量、真实OSS／S3或真实效果。定位回执只有`native_current_original_locator_checked=true`，传输回执只有`complete_requested_bytes_verified=true`；传输的native_permission及双方必要范围／输入权威／执行／历史存在性均false，没有正式binding。

初次因冻结解析字段路径使用顶层而非实际嵌套`parse`导致拒绝，修正后完整回归通过；保留合成失败日志和JUnit。所有既有来源／范围／原页／GET／输入／图文／特征方法及旧记录保持原值。7修改输入逐字节对照Git索引，14份脱敏证据及完整散列见[验收回执](evidence/current-original/receipt.json)。

5188预览1196运行输入／68生产资源逐字节匹配，登录／会话／退出及既有摘要和同源动作拒绝行为正常，业务项目／写入／付费调用0。独立检查库、临时LOGIN、本批原件及范围能力组均0；checks／检查PG／asset-renderer停止，API／Web／PG健康，正常Word服务保留。运行是开发只读挂载的启动观察，不宣称整树不可变发布。没有公开HTTP或前端变更，浏览器缺服务模块及视觉验收缺口保留。

继续完整当前材料投影、必要范围权威与独立原生binding，再接发送前CAS／lease、token／费用上界、持久化／Worker及正式执行；真实配对仍暂无，不能据本批机制数字关闭F06或声明精度。
