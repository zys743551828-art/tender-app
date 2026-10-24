# 私有材料归档

`packages/storage/private_cas.py` 只处理私有本地文件及内容摘要；`package_material_archive.py` 处理完整材料上下文、页图引用和归档清单。两层均不加载业务配置、数据库、云凭据或模型适配器。公开 HTTP 与数据库契约不变。

`prepare` 通过完整 `/3` context 核验后拥有独立快照，返回上下文规范 JSON 及全部整页／裁片的内容对象。上下文保留确切文档、冻结解析、原依据、档位、条件、例外、排除及缺口。文件摘要相同只去重字节，不合并文档、解析、页码或资产身份。原 PDF 字节留在原件服务，不在归档中重复复制。

`save` 先完成全量核验，再逐一保存依赖，全部读回核对后最后发布清单。`load` 必须接收调用方独立固定的清单摘要和 context 摘要，无 latest 或按时间推算身份。返回的 `ArchivedMaterial` 只证明读取字节及引用一致，不构造 `MaterialContext`；后续执行仍须从原生端口重新核对当前来源、权限、必要范围、原件和解析，并独立完成登记及发送控制。

清单规范 JSON 的字段闭合为 `version=package-private-material-archive/1`、`archive_method_digest`、`context_digest`、`context_object={sha256,byte_size}`、`images=[{asset_id,sha256,byte_size}]`、`original_pdf_bytes_copied=false` 及四项 false：`native_binding_verified`、`input_authority_granted`、`execution_authorized`、`current_native_facts_rechecked`。图像引用按资产 ID 排序。存储对象、清单分别使用完整规范字节的 SHA-256 命名；context 摘要仍按 `/3` 规则排除自身 digest 字段计算。方法摘要固定归档和存储源码、context 方法及容量。读取旧清单核其固定内容摘要和方法字段形状，不把当前代码身份冒充历史执行证明。

容量为 384 个图像引用、context 12 MiB、单图 32 MiB、所有图像引用合计 64 MiB、完整归档 76 MiB、单内容对象 64 MiB、清单 256 KiB。超量拒绝，不能截断。布尔值不能冒充整数长度，false 不能用 0 替代；非规范 JSON、重复键及额外字段拒绝。

本地后端仅支持 POSIX，由宿主提前提供独立租户的 owner-only 0700 根目录，不在请求中接收路径。沿每层目录使用 no-follow 打开，固定根目录描述符；只使用固定 `objects`、`commits` 子目录和小写摘要文件名。根目录及子目录核实际属主和 0700；文件核普通文件、实际属主、0600、单链接。FIFO、软链接、额外硬链接及公开权限拒绝，目录锁最多等五秒。Windows 后端直接返回 POSIX_REQUIRED，不宣称 Unix mode 等同 Windows ACL。

所有协作写入者都使用该端口的目录锁；锁覆盖存在性检查、文件 fsync、原子改名和目录 fsync，既有对象核一致后复用，损坏对象拒绝覆盖。读取前后核设备、inode、属主、模式、链接数、长度及修改时间，另核完整摘要。该边界不能隔离同 UID 的恶意进程或管理员；读取校验也不能替代宿主安全与独立权限。

普通失败或进程退出可留下不可引用的 `.pending-` 文件或无清单的完整对象；不返回半份材料，不提供列举、删除或自动回收接口。发布后进程退出仍可按固定摘要读取完整对象。目录 fsync 失败时调用结果不确定，固定清单摘要可用于下次核对；不承诺未经验证的断电持久性。缺件、内容改变和清单篡改均拒绝恢复，错误只含固定代码，不携带私有路径或异常上下文。

范围外：云端 PUT、私有租户根目录的生产供应、总磁盘配额／回收、原生资格登记、必要范围证明、费用账本、Worker 自动重启恢复、模型真实调用、真实评分精度与浏览器视觉验收。
