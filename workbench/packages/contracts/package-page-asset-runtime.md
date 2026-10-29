# 固定Compose原页派生运行边界

受限原页服务是`tender-fusion`组内的固定`asset-renderer`，属于显式`assets` profile；默认预览仍仅API、Web、PG三个正常服务。它复用已有依赖镜像，不安装软件、不创建零散调试容器或持久数据卷。每份原件开始前重建该命名服务，结束时按确切容器ID停止并观察PID为0，再核对和返回结果；下份任务不会继承上一份tmpfs或进程。组的stop／status／logs／config包含该profile，普通up不自动启动它。

可信宿主控制器位于`deploy/fusion_asset_runtime.py`，只由宿主入口显式调用，不装配到API／业务Worker，也不向它们挂Docker socket；共享部署源码可读不代表已有Docker执行能力。调用者从独立已批准配置取得镜像ID、源码指纹与渲染／裁片方法摘要；原件请求只传bytes、文档ID、原SHA／字节数和明确区域，不传路径、镜像名、Docker参数或凭据。控制器先核当前项目API的Compose归属及工作目录，跨检出目录拒绝；OS文件锁串行占用固定服务。

服务使用65532:65532、只读根、cap_drop ALL、no-new-privileges、Docker默认seccomp、无网络、无端口／secret／数据库／对象凭据；只有七份必要当前代码文件的只读挂载，没有整包源码、历史研究、测试或业务配置挂载。唯一可写应用目录是64MiB私有tmpfs。内存1GiB且禁交换、单核、32 PID；控制器检查实际Docker配置，Worker在送入PDF前读取cgroup v2和进程状态，核`memory.max`、`memory.swap.max`、`cpu.max`、`pids.max`、零能力集、NoNewPrivs和seccomp，以及只有lo接口。含义见[Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)与[进程状态说明](https://man7.org/linux/man-pages/man5/proc_pid_status.5.html)。缺少这些内核能力即失败，不放宽配置替代。

单次执行使用`python -I`及固定入口，禁止业务环境加载；另外限制core、文件大小、FD及35秒CPU。原件／PNG通过stdin／stdout的有界帧传递：4字节大端JSON头长度，最多1MiB头，再接最多32MiB原始bytes。头在JSON解码前先限制，拒绝重复键、浮点、非有限数和非法Unicode；块声明、总长度、唯一ID、PNG／原文摘要及裁片请求必须精确对应，无任意URL或文件路径。stdout总上限33MiB加4字节，stderr上限8KiB且不展示内容，避免把私有原文放入异常或日志。

渲染交换默认40秒墙钟上界，覆盖上传、原生处理和结果读取；启动／描述／停止有各自独立时限，不声称整次操作40秒内完成。超时或输出过大先结束exec客户端，再停止完整容器命名空间；停止未确认时不返回结果。控制器检查源码指纹前后一致，这是当前开发挂载观察，不是不变镜像发布证明。宿主机与Docker daemon属于可信控制面，本服务不提供公共HTTP、队列或正式核验权限。

返回原资产bundle及独立`package-page-render-execution/1`回执：实际镜像／源码／容器身份、内核限制、起止与停止观察、原件／结果摘要。普通资产manifest中的资格标志不改写；独立回执只记录本机容器边界，不能证明页面内容／字体复现／可读性、完整必要范围、历史存在或正式输入／模型资格。当前原生核验器和API／Worker装配仍须单独完成。

控制器崩溃时没有完成回执，不授成功；下一次明确调用先重建同服务，清理旧命名空间后才允许新原件。没有看门狗、开机任务或后台自动接续。独立宿主机、生产容量、恶意PDF语料和内核安全资格仍待目标环境验收。

纯回归入口为`./deploy/fusion.ps1 -Action checks -Suite asset-runtime-pure`。明确的本机原生验收入口是`python -m deploy.fusion_asset_acceptance --expected-image-id <已批准ID> --expected-source-digest <冻结源码摘要>`，仅生成合成PDF，并在同一命名服务中验证整页／裁片、错误方法、无效原件、墙钟超时、互斥、遗留子进程和控制器直接退出后的重建回收。原生验收工具不在受限挂载或产品入口中，故障注入不能由资料或HTTP请求触发；证据只写工作区`.local`内指定目录。
