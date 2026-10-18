# 独立 DOCX 转换器

用途及队列消息见 [转换契约](../../contracts/word-conversion.md)。这是独立运行的基础设施；产品接入使用上级 `compose.word.yml`，材料身份与采用见 [Word 材料契约](../../contracts/word-materials.md)。队列字节须先登记为业务档案并通过采用校验。

在本目录执行 `docker compose build`，然后 `docker compose up -d`。默认创建本项目的输入、输出卷；不会启动或修改业务服务。输入目录所有者为业务 worker 的 UID 10001，输出为转换器 UID 65534。首次建卷后核实权限，再给业务端挂载输入可写、输出只读。不要挂载业务密钥、宿主 Docker socket 或真实资料根目录。

启动时核对网络、权限、只读根、公共临时目录和 Landlock 能力；未满足则退出。`renderer.json` 暴露构建时固定的程序、包版本及字体指纹；健康检查读取心跳，单次完整转换允许占用 65 秒，心跳超时为 120 秒。没有开放端口。

镜像固定 LibreOffice Writer 7.4.7 Debian 安全更新及字体包版本，使用系统已有 Docker；构建不在 Windows 安装 Office。若固定包不再可用，构建应失败，由维护者核验更新并产生新方法指纹。原生库、程序、字体或选项改变均重新构建；不要复用旧方法的回执。

专项校验（在仓库根目录）：

```powershell
backend/.venv/Scripts/ruff check deploy/word --select E,F,I,B,UP --ignore E501
backend/.venv/Scripts/ruff format --check deploy/word
backend/.venv/Scripts/bandit -r deploy/word -ll
backend/.venv/Scripts/pytest backend/tests/test_word_inspection.py -q
docker compose -f deploy/word/compose.yml config -q
```

真实无网络容器回归和跨任务隔离证明由研究仓库 `scripts/word_converter_check.py` 执行，测试资料只用脚本生成的合成文件。它创建自己命名的容器和卷，结束时停止并清理这些资源；不访问业务数据库或模型，不使用业务凭据。结果须保存到新的输出目录。
