# Windows 完整 Compose 运行与验收

本入口复用已安装的 PowerShell 7、Docker Desktop、工作台 Python 和依赖镜像。私有身份保存在 Docker Linux 命名卷中；主机目录只保存公开请求、计划和清单。完整环境单独归入 `tender-fusion-full-<实例前缀>`，默认回环端口 5189。5188 仍是 API 预览环境。

## 全新检出的前置步骤

在workbench目录使用Python3.12创建专用环境，并在所有完整候选prepare之前构建当前前端。不能直接复用旧dist或把解析依赖覆盖到API环境：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-fusion-checks.txt
.venv/Scripts/python.exe -m pip check
Push-Location apps/web
npm ci
npm run build
Pop-Location
```

缺少dist/index.html时，up的Linux私有配置阶段以FULL_FRONTEND_BUILD_REQUIRED拒绝；prepare只生成公开请求与Compose。Windows宿主负责编排；私有配置和初始化在Docker Linux卷执行，手工POSIX私有文件启动命令不直接用于Windows共享目录。

## 创建新候选

在 `workbench/` 中执行；下面 Python／Web digest 为本轮已有镜像，不应替换成浮动标签。基础设施镜像由源码固定，须先取得这些准确镜像。不得用不匹配的旧镜像冒充通过。

```powershell
.venv/Scripts/python.exe -X utf8 -m deploy.fusion_desktop prepare `
  --directory .local/full-desktop/candidate1 --name full_candidate1 `
  --origin http://127.0.0.1:5189 `
  --python-image tender-fusion-checks@sha256:f21edf5853b0c337de05a4b6af7ee16787b5520d8e4101b34fea6ee2a70b25be `
  --web-image bidwb-web@sha256:f59162088fb1ddaa18d29e155b60e3b89fec071d7e34b4a0fbb549e73d247f24
.venv/Scripts/python.exe -X utf8 -m deploy.fusion_desktop up --directory .local/full-desktop/candidate1
.venv/Scripts/python.exe -X utf8 -m deploy.fusion_desktop status --directory .local/full-desktop/candidate1
```

`prepare` 不启动容器、不覆盖目录。`up` 冻结当前输入，先生成 Linux 私有配置，再启动基础设施、全新初始化、逐角色画像发布和业务服务。默认不启动付费模型或自动调度。强随机验收管理员口令只保留在私有卷内，不输出、不写公共描述；5188 原有账号不受影响。此入口首先用于独立交付验收，不是将现有预览项目迁入新库。

## 人工登录的交付条件

此完整组的admin随机口令保留在私有卷，现有verify自动读取专用validation-login完成HTTP验收。当前CLI没有面向业务人员的安全凭据交接命令；不应通过打印私有卷或把verify账号复制到公开日志来补齐。因而自动验收通过不表示新成员已完成完整组人工试用。首次人工界面演示使用正式运行页的5188预览及操作者自设口令；完整组人工签收须先明确受控凭据交接方式，不能沿用5188口令。

## 实际文件链路验收

```powershell
.venv/Scripts/python.exe -X utf8 -m deploy.fusion_desktop verify --directory .local/full-desktop/candidate1
```

显式启用同组 checks profile 的无特权验收服务。它要求项目库为空，创建一个有合成标记的项目，通过真实 nginx HTTP 登录、同源上传、Kafka relay／Worker、两页 PDF 独立解析和鉴权下载；并检查旧票据、匿名访问、跨会话、错误对象密钥和其他桶写入被拒绝。结果只输出身份摘要、布尔检查和合成项目 ID，不输出票据／凭据。解析覆盖为 partial，不证明复杂图文或真实业务评分质量。

验收后保留合成项目和原件，便于复核；同一个候选不能反复冒充全新验收。源码、部署策略、SQL、前端或依赖变化后，应停止旧候选并创建新目录／实例，不修改冻结原件以迎合新代码。

## 停止与故障定位

```powershell
.venv/Scripts/python.exe -X utf8 -m deploy.fusion_desktop stop --directory .local/full-desktop/candidate1
```

停止操作不删除卷。保存的清单和实例绑定仍须匹配，但源码变动不阻碍停止旧环境。仅完成 bootstrap 的失败候选同样可停止。初始化失败只显示脱敏错误码、异常类型和可用 SQLSTATE；不得把完整日志、连接环境或私有画像直接贴到对话或 Git。

纯回归继续使用固定 `tender-fusion` 检查组：`pwsh -File deploy/fusion.ps1 -Action checks -Suite desktop-pure`。结束后停止 checks 与 checks-postgres。各阶段实际结果和未验范围另见本轮验收记录，不从命令示例推断已经通过。
