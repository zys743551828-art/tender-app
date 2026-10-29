# 当前原生材料与受限渲染联合观察

`deploy/fusion_material_derivation.py` 是可选可信宿主控制器，连接原生材料读取端口和既有 `FusionAssetRuntime`／`FusionMaterialPages`；不接到 API 或 Worker，不让服务取得 Docker socket，不从请求接受执行回执、Docker 参数、镜像或文件路径。调用者须提供已配置且固定镜像／源码摘要／硬超时的运行对象、独立 scope／original／parse 连接、准确项目／范围摘要及受控私有原件 URL 适配器。

控制器先核当前方法、三个独立空闲连接及受信运行对象，再取得一次真实受限运行描述。原生材料端口读取准确冻结解析、当前范围和全部原件，每份原件经独立新建的同名 Compose asset-renderer 服务渲染。全部渲染会话停止后，原生端口重新读取解析／来源图、当前范围和所有私有定位；网络 GET 与渲染不跨开放数据库事务。来源撤回、项目关闭或解析／定位变化导致整个结果拒绝，不能因部分页图成功就交付完整输入。

每份材料按原生顺序对应一份真实执行回执。控制器核全部文档均有且只有一份回执、准确原件及 manifest 摘要、固定镜像／源码／硬超时、不同容器身份、实际停止及PID为0、源前后保持、无OOM。底层运行器负责实际内核限制、网络隔离、固定挂载、墙钟和每份命名服务回收；结果 schema 固定这些限制。清单与回执交叉错配或重复容器身份拒绝，不能以重算摘要接受调用者自报证明。

返回 `DerivedMaterial(material, metadata)`，原 `CurrentMaterial` 及其 false 资格位保持不变。新观察分别保存材料摘要、运行描述、逐文档实际回执与整体摘要；`fresh_native_facts_checked_after_all_render_sessions`、`actual_render_boundaries_observed`、`renderer_receipts_match_all_documents` 仅描述本次受控执行。可读性、必要范围、原生binding、输入、执行及历史存在位仍false。结构摘要不是永久权威或执行租约，未来资格登记须再关联准确上下文和独立审核、检查当前来源；不能直接反序列化一份JSON便授信。

方法固定控制器与适配器源码、现有受限运行描述及原生材料方法；运行前后复核方法和运行参数，不改旧摘要或已归档记录。

`deploy/fusion_material_checks.py` 是固定的实际联合验证入口，复用现有 Python、Docker镜像和同一 tender-fusion 检查组。必须在 checks 空闲时运行，不能接任意 suite／命令参数。可选 `compose.fusion.host-checks.yaml` 仅给 checks-postgres 增加随机127.0.0.1端口和临时bridge；正常业务库无端口或权限变化。检查进程使用必要系统变量白名单，保留Windows PROGRAMFILES以发现既有Compose插件，显式禁止业务env自动加载；专用检查口令只在内存／子进程环境中，不出现在命令参数或日志。

结束核对独立库、LOGIN及六类组清零，恢复原Compose检查库定义以移除端口，停止检查／渲染组并删除已空的专项bridge，保持正常预览与Word。失败时也执行清理，不自动删除遗留业务对象或修复授权。所有用例均为合成材料；真实语义／视觉审核、正式输入／评分、费用和Worker仍独立验收。
