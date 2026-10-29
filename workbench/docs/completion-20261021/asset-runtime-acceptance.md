# 固定Compose受限原页派生验收

## 运行边界

[受限运行契约](../../packages/contracts/package-page-asset-runtime.md)定义`tender-fusion`组内的固定`asset-renderer`，复用现有依赖镜像，显式assets profile，每份原件先重建、结束后按确切容器ID停止；默认预览仍三服务。宿主控制器不接文件路径、镜像名、Docker参数或凭据，不装配到产品API／业务Worker，不挂Docker socket。共享部署源码可读与实际控制能力分开，跨检出目录和并发控制器拒绝。

受限服务65532:65532、只读根、零能力、NoNewPrivs与默认seccomp、无网络／端口／secret，仅七份必要当前代码的只读挂载；不挂整个packages、历史、测试或业务配置。实际核cgroup v2的1GiB内存、禁交换、单核和32 PID，以及仅lo接口。额外限制core、FD、文件大小和CPU；固定python -I入口，无业务环境加载。缺所需内核限制时失败，不削弱隔离补过。

JSON头先限1MiB才解码，原件／PNG为最多32MiB原始bytes，4字节长度帧；没有巨型base64 JSON树。stdout有界，stderr不展示正文。40秒为渲染交换墙钟上限，启动／描述／停止独立计时；超时结束exec客户端后停止完整命名空间，停止未确认不返回结果。源码指纹前后核对，只是当前开发挂载证据，不是不可变镜像发布。

独立执行回执记录真实镜像、源码、容器、内核限制、起止／停止与原件／结果摘要。原资产manifest的资格标志不改写；容器边界观察不能证明内容正确、字体复现、可读性、必要范围、历史存在或正式输入／模型资格。独立原生核验与API／Worker的资产租约／持久化仍须接通。

## 验证

- 固定Compose `asset-runtime-pure`最终**126项通过、1.19秒、0跳过**：46控制器／帧／配置反例、50原资产、18原解析及12原Compose。主机46项0.77秒是Linux子集，不相加；3条旧PDFium警告保留。独立`desktop-pure` **193项11.99秒、0跳过**，包含重叠配置；不与126相加。完整桌面组仅配置回归，没有重新启动其运行组。
- [可复现原生入口](../../deploy/fusion_asset_acceptance.py)最终实际执行**10次同一命名Compose服务的全新会话**：描述、两页合成PDF整页、同像素裁片、无效PDF、方法错配、1ms墙钟拒绝、遗留子进程及下一会话、控制器直接退出及恢复。所有结束服务停止或旧实例已移除；无零散调试容器、持久数据卷或真实模型请求。
- 实际观察UID65532、内核限制、零有效／许可／边界／环境能力、seccomp和NoNewPrivs；native结果源与目标摘要匹配，两个独立新容器的全部原页字节相同。旧asset／input／vision／feature方法保持原值，新执行回执不回填旧manifest。
- 受控后台子进程先真实创建tmpfs标记，再停止整个环境；下一容器ID不同、标记不存在。独立宿主控制器实际`os._exit(17)`后确认旧服务仍运行，下次明确调用移除旧实例再处理新原件，tmpfs无残留；没有安装看门狗或后台接续。1ms测试只证明硬墙钟与回收，不断言已经进入原生PDF解析，不计作恶意PDF语料或生产负载验收。
- 实际查看两张PDFium整页和一张裁片，及两张独立Poppler整页，红色区域、文字、90度原页旋转均保留；最终导出与已查看PNG／PDF字节一致。Poppler字体映射警告保留，不能据合成图授实际标书可读性或字体复现。见[视觉记录](evidence/asset-runtime/visual-proof.json)。
- 七文件Ruff／format、四实现mypy／Bandit及Compose配置通过。初次Windows平台类型检查缺Linux专属属性声明已修；Bandit的两处assert改显式错误，私有容器tmpfs检查的B108记录为受审常量；没有关闭整类检查。无新HTTP／SQL／前端行为，不重跑1786或宣称本批视口通过。

实际镜像为已有`tender-fusion-checks:py312`，ID固定于[原生收据](evidence/asset-runtime/final-native/native-render-proof.json)，没有安装或拉取镜像。10修改输入与Git原字节相同；执行源码中的未改动`review_identity.py`保留当前CRLF，与Git的LF仅执行文本相同，原字节另存，未规范化旧来源消除摘要差异，不冒整树一致。全部原始输出、JUnit、实际故障及恢复、源码身份见[总回执](evidence/asset-runtime/receipt.json)。

5188当前1182运行输入／68生产资源匹配，三正常服务健康，实际登录／会话／退出与只读接口通过，业务项目／写入／付费调用0；37 BASE SQL／136表和可选研究503保持原边界。检查非系统数据库／临时LOGIN0；checks、检查PG与asset-renderer停止。正常业务Word保留，旧dev／Claude和完整组未启动。内置浏览器缺启动模块，PDF资产实际检查不能替代前端截图。

继续独立当前输入核验、原生权威记录和资产接线，然后token／价格上界、发送账本／预算／租约及正式Worker。真实配对暂无，后台接续关闭，仅当前对话推进。
