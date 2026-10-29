# 前端11：长会话续谈最小整改

只整改独立用户 U10-01。首次进入/刷新真实主会话后，定位并聚焦当前输入；“回到最新／继续提问”常驻可达，键盘可激活。用户上翻、触摸或移焦阅读旧记录后停止跟随，轮询与迟到内容不能强抢滚动/焦点。只有仍在当前输入中继续编辑时，内容尺寸变化才保持输入可见。明确 `?action=` 链接保留原卡位置，仍可主动续谈。全局说明改为“这段讨论仅你可见。选择项目或资料作为上下文。”

费用未知仍暂停发送，不清账、不解锁、不补发。现有项目/全局草稿隔离、操作收据、来源与历史保留。未加入 Word/A2 或“发送新问题”后续功能。

- 候选：[frontend-candidate.json](/workspace/tender-workbench/apps/web/qa-previews/assistant-continuation-11/frontend-candidate.json)，SHA `af1a992ec7539c465b873abd04bcc87e4bbc89901962f2f6c283e395ef8629e5`。130 源、215 资产，源改动 7 文件，复制 8,435,615 bytes，无 node_modules 复制。
- 运行：原生 `http://127.0.0.1:5184` 固定11 `frozen-inputs` Vite preview，代理既有固定05 API8816，task05 与04实际契约同 SHA `4af4b5d611539485be74aeed8b98f07d95fb4bc4e9c16572a781f219e5877ae2`。依赖复用原项目 node_modules，锁文件摘要与10相同。其余旧端口未改，10源/资产逐一核验保留。
- 开发浏览器：[development-browser-result.json](/workspace/tender-workbench/apps/web/qa-previews/assistant-continuation-11/development-browser-result.json)，明确仅11资产 overlay，API仍真实8816，不作为原生部署结论。
- 冷启动浏览器：[native-browser-result.json](/workspace/tender-workbench/apps/web/qa-previews/assistant-continuation-11/native-browser-result.json)，最终新增抽屉 Tab 焦点循环与同会话全屏。
- 最终运行绑定：[cold-runtime-binding.json](/workspace/tender-workbench/apps/web/qa-previews/assistant-continuation-11/cold-runtime-binding.json)，记录源/资产前后校验、实载 JS/CSS摘要、进程与后端契约同对象。

格式、lint、typecheck、实际契约重生比对均通过；只运行受影响 16 项测试（7 条定位反例 + 9 条既有助手行为），全过。10此前122项不宣称本次重跑。构建首轮 ENOSPC 原日志 `build-development.log` 保留，PM串行空间窗口后既有依赖重试成功，日志 `build-development-retry.log`；未安装依赖、删旧资产或无限重试。初次浏览器命令选错不含 Playwright 的 `.venv/bin/python` 未执行页面，改用现成系统 Playwright Python，未安装包。

只读浏览器使用现有显式合成成员/长会话：1440×1000、390×844 首次/刷新输入在可视区，上翻至旧消息等待真实轮询仍保持位置，Tab/Shift-Tab/Enter续谈聚焦输入。未发送本地草稿验证范围切换与浏览器返回；抽屉/Escape/Tab循环/同会话全屏；固定已执行Action原卡和费用未知继续暂停。浏览器拦截任何非认证业务写入，实际0业务写、0turn、0control改变、0任务运行、0模型费用；无新通知或任务夹具。此为开发受影响自查，待独立用户/QA delta，不外推模型质量或整FR通过。

独立用户建议复核：长全局会话冷进入/刷新，主动上翻后等一轮状态更新，再键盘续谈；390抽屉→全屏→返回；已有费用未知不可发送；原卡深链不被自动跳过。后续新正向显式Mock由PM单独交接控制窗口，不能从本小片无费读路径推为发送链已验。
