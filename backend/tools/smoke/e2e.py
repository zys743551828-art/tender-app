"""浏览器端到端冒烟：登录 → 项目总览 → 评审报告 → 处理否决风险 → 全部按原文确认规则 → 按招标文件填好的报价试算与保存 → 功能开关 → 导出 → 度量。

用法：先 `python tools/smoke/smoke_server.py`（打印 READY project <id>，评审已在进程内自动跑完），
再起前端（npm run build && API_TARGET=http://127.0.0.1:8000 npx vite preview --port 4173），
然后 `python tools/smoke/e2e.py <project_id>`。需要 playwright 与 Chromium（CHROMIUM 环境变量可指定可执行文件）。
截图写到 E2E_SHOTS 目录（缺省为当前目录）。
"""

import os
import re
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

PID, BASE = sys.argv[1], os.environ.get("E2E_BASE", "http://127.0.0.1:4173")
SHOTS = Path(os.environ.get("E2E_SHOTS", "."))
errors: list[str] = []


def shot(page, name: str) -> None:
    page.screenshot(path=str(SHOTS / f"e2e-{name}.png"), full_page=True)


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
    page = browser.new_context(viewport={"width": 1360, "height": 1000}, accept_downloads=True, locale="zh-CN").new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on(
        "response",
        lambda r: errors.append(f"HTTP {r.status} {r.request.method} {r.url}") if r.status >= 400 and "/me" not in r.url else None,
    )
    page.goto(BASE + "/login")
    page.get_by_label("账号").fill("demo")
    page.get_by_label("密码").fill("correct-horse-battery")
    page.get_by_role("button", name=re.compile("登录")).click()
    page.wait_for_url(re.compile("/projects"))

    # 项目总览：每行给出否决风险、预计技术分与下一步
    row = page.get_by_role("list", name="项目清单").get_by_role("listitem").first
    expect(row.get_by_text("1 个未处理")).to_be_visible(timeout=20000)
    expect(row.get_by_role("link", name="处理否决／强制风险")).to_be_visible()
    shot(page, "projects")

    # 报告：结论、下一步、逐条响应、技术分预测（未校准、覆盖程度）
    page.goto(f"{BASE}/projects/{PID}")
    expect(page.get_by_role("heading", name="评审报告")).to_be_visible(timeout=20000)
    expect(page.get_by_text(re.compile("可能导致否决或不满足强制要求的问题还没处理"))).to_be_visible()
    expect(page.get_by_text("只覆盖 8 / 60 分").first).to_be_visible()
    expect(page.get_by_role("heading", name="下一步")).to_be_visible()
    shot(page, "report")

    with page.expect_download() as dl:
        page.get_by_role("link", name="导出 Word 报告").click()
    assert dl.value.suggested_filename.endswith(".docx"), dl.value.suggested_filename

    # 下一步 → 否决风险分类；招标要求与正文写法并排，确认问题
    page.get_by_role("link", name="处理否决／强制风险").first.click()
    expect(page.get_by_role("heading", name="施组正文写法")).to_be_visible(timeout=10000)
    page.get_by_label("理由").first.fill("确认超期，需要改进度计划")
    page.get_by_role("button", name="确认问题").click()
    expect(page.get_by_text("已记录：确认问题")).to_be_visible(timeout=10000)
    shot(page, "finding")

    # 依据：一次确认全部待核对的规则
    page.goto(f"{BASE}/projects/{PID}/basis")
    page.get_by_role("button", name=re.compile("全部按原文确认")).click()
    expect(page.get_by_text(re.compile(r"已确认 \d+ 条规则"))).to_be_visible(timeout=10000)

    # 报价：评标价规则已按招标文件填好，只填报价
    page.goto(f"{BASE}/projects/{PID}/price")
    expect(page.get_by_text("已按招标文件填好评标价规则，请核对：")).to_be_visible(timeout=10000)
    expect(page.get_by_label("价格分满分")).to_have_value("30")
    page.get_by_label(re.compile("竞争对手报价估计")).fill("9800\n10000\n10200")
    page.get_by_label(re.compile("候选报价")).fill("9900\n10300")
    expect(page.get_by_role("table", name="候选报价的价格分")).to_be_visible(timeout=10000)
    page.get_by_role("button", name="保存方案").click()
    expect(page.get_by_text(re.compile("上次保存于"))).to_be_visible(timeout=10000)
    shot(page, "price")

    # 功能开关：关闭报价模块后导航里不再出现“报价”
    page.goto(f"{BASE}/projects/{PID}/settings")
    page.get_by_role("checkbox", name=re.compile("报价模块")).uncheck()
    page.get_by_role("button", name="保存开关").click()
    expect(page.get_by_text("开关没有改动。")).to_be_visible(timeout=10000)
    expect(page.get_by_role("navigation", name="项目导航").get_by_role("link", name="报价")).to_have_count(0)

    page.goto(f"{BASE}/metrics")
    expect(page.get_by_role("heading", name="度量")).to_be_visible(timeout=10000)
    shot(page, "metrics")

    # 窄屏：逐条响应变成卡片，没有横向滚动
    mobile = browser.new_context(viewport={"width": 390, "height": 844}, locale="zh-CN", storage_state=page.context.storage_state()).new_page()
    mobile.goto(f"{BASE}/projects/{PID}")
    expect(mobile.get_by_role("heading", name="评审报告")).to_be_visible(timeout=20000)
    assert mobile.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "窄屏出现横向滚动"
    shot(mobile, "report-mobile")
    browser.close()

if errors:
    print("ERRORS:\n" + "\n".join(errors))
    sys.exit(1)
print("E2E OK")
