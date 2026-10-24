# 核验程序任务命令权限审查

仅在全新独立检查库安装material_verification配置／case／不可变命令，新增tender_material_verification_commands NOLOGIN组。实际请求LOGIN只有begin_command／read_command两个窄RPC，无直接表／列／序列、CREATE、其他schema USAGE或额外definer执行，不能创建配置、修改命令或自授核验资格。

初始化者固定获准请求者及其原生角色OID、目标程序LOGIN及OID、控制器方法／政策／来源／数据库身份／有效期与准确登记／独立审核回执。原生函数核当前配置／审核及项目未提交状态；请求者与目标程序分开，后者仅为声明的待验证目标，尚无程序认证或执行权限。同名重建账号OID不匹配，不继承旧任务配置；命令记录实际请求者OID，重放和读取也核同一OID。

写RC／RW、读RR／RO，SQL与Python分别核实际session_user、精确用途成员和有效权限、正文／owner／search_path／UTC，结果校验在提交前，5秒语句超时。准确命令重放优先，读限本实际LOGIN与准确case／command／case摘要，当前配置状态和head修订不改旧事实。运行时无角色切换／权限修复。

任务状态仅pending_controlled_verification，程序认证／执行、必要范围、binding／输入／执行全部false。正常业务库、BASE、公开HTTP与前端无变化；结束清理独立库、临时LOGIN和十二类组、宿主端口及临时bridge，停止检查／渲染，保留预览与Word。后续目标程序消费和完成资格须以独立purpose及原生约束另验，不能拿登记状态代替已核验。
