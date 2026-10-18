# 隔离 Word 转换队列

本契约约束外部 DOCX 到 PDF 的独立转换基础设施。业务上传、PDF 采用、快照与逐文件补交见 [Word 材料契约](word-materials.md)；队列输出通过租约保护的业务事务登记，不直接替代当前材料。

## 身份与消息

业务端写入 `/word-input`，转换器只读输入、写入 `/word-output`；业务端只能读取输出。每次请求生成新的 32 位小写十六进制操作 ID。先写 `<id>.docx`，再原子发布 `<id>.request.json`。请求不超过 8192 字节：

```json
{
  "filename": "外部改稿.docx",
  "source_sha256": "原件字节的64位小写SHA256",
  "source_bytes": 12345,
  "renderer_fingerprint": "已核对转换器的64位小写指纹"
}
```

原件最多 100 MiB；原件大小、摘要或转换器指纹不符时不执行转换。服务发布 `<id>.pdf` 后才原子发布 `<id>.json`；失败只发布 JSON。身份来自操作 ID、原件摘要和转换方法指纹，不来自文件名。业务端收件时必须再次验证这三项及 PDF 的大小和摘要。

输出保留原件摘要、方法指纹、`operation_id`、容器隔离事实、`conversion_attempted` 与状态；DOCX 核验通过后附带 `inspection`。不保存完整段落；文字不对应时最多返回 5 个、各 120 字符的核实片段，按业务资料保护。

| 状态 | 含义 |
| --- | --- |
| `converted` | 已生成可打开且有内容的 PDF，文字对应、字体覆盖／替换与有限布局检查未发现缺口 |
| `needs_review` | 已生成 PDF，但存在文字、字体、复杂布局或可见内容缺口，须核对 PDF |
| `failed` | 未生成可采用 PDF；`conversion_attempted=false` 表示在执行转换前拒绝 |

以上状态均不表示 Word 原件已通过评审、与用户补交 PDF 内容一致或正式提交文件合格。表格、图形、页眉页脚、修订等复杂版式始终要求核对。旧 `.doc` 不在自动转换范围内。

## 隔离及上限

转换器无网络、无业务凭据、无 Docker socket、非 root、只读根目录、移除全部 capabilities。每个原生转换／PDF 校验子进程均在 Landlock ABI 6 以上的独立任务域内，仅能读取固定系统程序、字体和当前任务目录，不能读取队列、其他任务或向父进程发信号。能力不足即拒绝启动。

公共 `/tmp` 与 `/var/tmp` 不可写，LibreOffice 直接执行固定 `soffice.bin`，通信、临时文件和配置位于私有 `/work/word-*`。新配置请求重启时最多重启一次；两次合计 45 秒。PDF 校验另限 20 秒；至多 1000 页、50 MiB，每边不超过 4000 pt、总采样像素不超过 6400 万。容器内存 1 GiB、1 CPU、128 进程；任务临时盘 256 MiB。

DOCX 不解压到文件系统、不跟随关系；分别限制 ZIP 大小、条目数、展开大小及 XML 大小／节点／深度。拒绝 DTD、外部关系、宏、嵌入对象、altChunk 和动态域（含页码及目录域），不通过放宽执行能力重试。

服务逐个处理请求。业务端结束等待后删除自己创建的请求及原件；服务仅在请求已不存在且输出超过 120 秒时回收对应输出。原件、采用决定和历史输入的正式保存须由业务层完成，共享卷不承担档案存储。

产品队列客户端 `bidwb.word_conversion.convert_word` 接受已核对的固定方法指纹，不将队列自报的方法自动登记为可信。发布前核对方法、隔离状态和心跳，等待期间与收件后调用任务租约检查。接收时再次验证操作、原件、方法、状态、页面范围、缺口一致性及 PDF 字节摘要；失败回执只交付原因。取消或超时只清理本操作输入，输出由只读挂载保护。清理为尽力执行；进程崩溃后的输入回收尚未验收，业务回执由处理器在租约保护事务中追加，不应把临时队列当永久档案。

任务运行器支持 `HandlerFailure.finalize`：在 `tasks.commit_result` 锁定任务并核对当前租约、尝试及输入后，在同一数据库事务内执行失败凭据追加。凭据写入出错时任务失败状态与事件一并回滚；过期、取消、重新领取或重复完成的旧尝试不执行追加。失败不登记成功产物或解析证据；Word 处理器据此保存转换失败回执。

官方依据：[LibreOffice 启动参数](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html)、[7.4 分支通信路径实现](https://github.com/LibreOffice/core/blob/libreoffice-7-4/sal/osl/unx/pipe.cxx)、[Landlock 内核文档](https://docs.kernel.org/userspace-api/landlock.html)。边界依据实现与实测共同核对，文字对应不能证明完整视觉一致。
