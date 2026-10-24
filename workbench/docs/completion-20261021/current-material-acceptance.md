# 准确解析与完整当前材料验收

[完整材料契约](../../packages/contracts/package-current-material.md)由独立准确解析读取器、完整材料控制器和可选宿主Compose适配器分工实现。解析读取器复用已有独立来源角色，重算实际返回的原生页／块摘要并核parser／config身份；控制器从原生scope取得完整材料，绑定全部原件GET、准确解析与整页资产，末尾复核范围／来源／定位。旧方法与历史记录保持，无新增SQL／ACL／HTTP。

原生冻结页质量／gaps、每块文字／摘要／bbox／structure逐项比较；原页文档／原件／长度／页数／宽高／旋转核对，不能用页数相同替代准确绑定。保留完整两包／清单／scope、所有成员与原生页块、四条规则、一条排除、三份依据、两个档位、条件与例外，不从多来源中选首条或省略未选材料。正文／原件／PNG均在私有字段，公开metadata只有观察摘要、计数与来源图，repr不暴露正文。

Linux **77项，49.32秒**：17材料原生PG、37既有来源原生回归、11导入隔离、12编排；Windows **11项，8.95秒**（重叠）。六文件ruff／格式、四实现mypy／bandit通过。原生测试完整走过scope→准确解析／来源→两次真实回环GET→进程内合成渲染→完整投影→末尾核验；解析ID／parser／config／证据错配、冻结文字替换、无准确／多义解析、越权、借用事务、渲染中撤回／关闭、方法／文字／资产超限及几何错配均拒绝。合成解析记录不证明实际OCR正确性，真实标书与真实评分效果未验证。

宿主适配器另对原生正向用例导出的**相同合成文档ID、原件摘要及长度**进行固定`tender-fusion`渲染：一次描述加两次逐件渲染，共3次新命名会话，全部PID归零并确认停止，2原件／4页与原生解析页几何一致，实际查看两页PNG。原生检查库在这次宿主渲染前已清理，故明确`database_rechecked_after_container_render=false`；这是分层机制验证，不声称同次存活PG与容器渲染后的最终核查。容器边界回执独立保存，材料观察的`renderer_boundary_verified=false`保持。

第一轮夹具误将三条依据写为两条，第二轮追加清单遗漏当前ETag，两次均在测试准备阶段拒绝；按真实数据及API条件修正后77项通过。保留失败日志／JUnit。8修改输入逐字节对照Git索引，18份证据及散列见[回执](evidence/current-material/receipt.json)，[原生材料](evidence/current-material/current-material-native-proof.json)和[独立Compose渲染](evidence/current-material/isolated-render-proof.json)分开记录。

5188为1202运行输入／68生产资源逐字节匹配，登录／会话／退出和既有同源入口回归正常，业务项目／写入／付费0。正常库核验角色／定位schema0、BASE37／design136保持；独立检查库、临时LOGIN及来源／范围／定位三能力组0，检查与渲染停止，API／Web／PG健康，正常Word保留。运行仍是开发只读挂载启动观察；本批无前端变更，浏览器视觉缺口保留。

`native_parse_and_original_material_observed/complete_frozen_declarations_retained=true`只证明观察和保留。必要范围、可读性、输入权威、执行及历史资格false，没有正式binding。当前`/2`模型规则字段只有单一来源引文，不能完整表达这里的多来源及结构化档位；本材料投影不直接送模型。下一项须以独立完整材料模型协议接线，保留原始依据与条款语义，再做独立必要范围／原生binding、CAS／lease、token／费用及Worker执行；真实配对仍暂无。
