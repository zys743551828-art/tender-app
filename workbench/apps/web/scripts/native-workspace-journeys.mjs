/* global console */
// Actual App and actual native HTTP. No route interception, fetch stubs or model I/O.
import assert from "node:assert/strict";
import {
  lifecycleUi,
  lifecycleAck,
  lifecycleMember,
} from "./native-lifecycle-journey.mjs";

export async function journeys({ browser, origin, config }) {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1000 },
  });
  await context.addCookies([
    {
      name: "session",
      value: config.cookie,
      url: origin,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const bid = `/bids/${config.bid}`;
  const goto = async (area) => {
    await page.goto(origin + bid + "/" + area);
  };
  const body = async () => page.locator("body").innerText();
  try {
    if (config.journeys.phase === "lifecycle_ack")
      return await lifecycleAck({
        page,
        context,
        origin,
        bid: config.journeys.lifecycle_bid,
      });
    if (
      config.journeys.phase === "lifecycle_member" ||
      config.journeys.phase === "lifecycle_inactive"
    )
      return await lifecycleMember({
        page,
        context,
        origin,
        bid: config.journeys.lifecycle_bid,
        inactive: config.journeys.phase === "lifecycle_inactive",
      });
    if (config.journeys.phase === "recover") {
      await goto("tasks");
      await page.getByRole("button", { name: "运行通知", exact: true }).click();
      await page.locator(".notification-row").first().waitFor();
      assert.equal(await page.locator(".notification-row").count(), 2);
      await page
        .locator(".notification-row")
        .filter({ hasText: "已记录处理结果" })
        .getByRole("button", { name: "打开这次真实运行", exact: true })
        .click();
      await page.waitForURL(/run=/);
      assert.ok(page.url().includes(config.journeys.run_id));
      await page.reload();
      await page
        .getByRole("heading", { name: "可复用任务", exact: true })
        .waitFor();
      assert.ok(page.url().includes(config.journeys.run_id));
      assert.deepEqual(errors, []);
      return {
        notification_count: 2,
        run_id: config.journeys.run_id,
        real_http: true,
        fresh_api: true,
      };
    }
    await goto("pricing");
    await page
      .getByLabel(/^本次投标包/)
      .selectOption(
        `${config.binding.package_id}:${config.binding.revision_id}`,
      );
    await page
      .getByLabel(/^本次招标与补遗包/)
      .selectOption(
        `${config.binding.authority_package_id}:${config.binding.authority_revision_id}`,
      );
    assert.equal(
      await page.getByLabel(/^本次投标包/).inputValue(),
      `${config.binding.package_id}:${config.binding.revision_id}`,
    );
    assert.equal(
      await page.getByLabel(/^本次招标与补遗包/).inputValue(),
      `${config.binding.authority_package_id}:${config.binding.authority_revision_id}`,
    );
    await page.getByRole("button", { name: "使用这两份修订继续报价" }).click();
    await page.getByRole("button", { name: "重新选择报价包修订" }).waitFor();
    await page.getByLabel("选择已确认公式").selectOption({ index: 1 });
    await page.getByLabel(/^本方候选报价/).fill("120");
    await page.getByLabel(/^对手报价假设/).fill("100\n100");
    await page
      .getByRole("button", { name: "试算当前情景", exact: true })
      .click();
    await page
      .getByLabel("保存此情景的理由")
      .fill("隔离浏览器实际保存，无模型调用");
    const saved = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" && r.url().endsWith("/pricing-plans"),
    );
    await page
      .getByRole("button", { name: "保存当前情景方案", exact: true })
      .click();
    const savedResponse = await saved;
    assert.equal(savedResponse.status(), 201);
    const plan = await savedResponse.json();
    await page.reload();
    await page.locator(".pricing-plan-summary").waitFor();
    assert.equal(await page.locator(".pricing-plan-summary").count(), 1);
    assert.ok((await body()).includes(plan.id.slice(0, 8)));
    await page
      .getByRole("button", { name: "返回项目列表", exact: true })
      .click();
    await page.waitForURL(/\/projects$/);
    await page.goBack();
    await page.locator(".pricing-plan-summary").waitFor();
    await page.getByRole("button", { name: "回看此固定情景方案" }).click();
    assert.ok((await body()).includes("25.00"));

    await goto("facts");
    await page.getByRole("button", { name: "补充有据事实" }).click();
    await page.getByRole("button", { name: "收起", exact: true }).click();
    assert.equal(await page.locator(".fact-card").count(), 0);
    await page
      .getByRole("button", { name: "补充有据事实", exact: true })
      .click();
    await page.getByLabel("事实主体", { exact: true }).fill("隔离工程");
    await page
      .getByLabel("适用范围", { exact: true })
      .fill("仅合成工程机制测试");
    await page.getByLabel("事实名称", { exact: true }).fill("合成人工核对事实");
    await page
      .getByLabel("事实取值", { exact: true })
      .fill("不代表真实工程材料");
    await page.getByLabel("选择来源文件").selectOption({ index: 1 });
    await page.locator(".evidence-select-item input").first().check();
    await page
      .getByLabel("依据与变更原因", { exact: true })
      .fill("隔离夹具引用，仅检查人工决定持久化");
    await page
      .getByRole("button", { name: "保存并确认事实", exact: true })
      .click();
    await page.locator(".fact-card").waitFor();
    await page.reload();
    await page.locator(".fact-card").waitFor();
    await page.getByRole("button", { name: "处理本条", exact: true }).click();
    await page.getByLabel("处理方式").selectOption("rejected");
    await page
      .getByLabel("依据与原因", { exact: true })
      .fill("显式驳回以验证决定版本，不授予真实事实效力");
    await page
      .getByRole("button", { name: "驳回此项事实", exact: true })
      .click();
    await page
      .locator(".fact-card")
      .getByText("已驳回", { exact: true })
      .waitFor();

    await page
      .getByRole("button", { name: "撤回当前事实", exact: true })
      .click();
    await page
      .getByLabel("撤回依据", { exact: true })
      .fill("隔离撤回，保留人工决定历史");
    await page
      .getByRole("button", { name: "确认撤回此事实", exact: true })
      .click();
    await page.locator(".fact-card").waitFor({ state: "hidden" });
    await page.goto(origin + "/knowledge");
    await page
      .getByRole("button", { name: "建立知识候选", exact: true })
      .click();
    await page.getByLabel("候选标题").fill("合成浏览器知识候选");
    await page
      .getByLabel("知识正文", { exact: true })
      .fill("仅验证候选保存，不表示已发布、训练资格或模型效果。");
    await page.getByLabel("拟适用范围说明").fill("隔离原生浏览器机制测试");
    await page.getByLabel("候选来源项目").selectOption(config.bid);
    await page
      .locator(".knowledge-candidate input[type=checkbox]")
      .first()
      .check();
    await page
      .getByRole("button", { name: "收起候选表单", exact: true })
      .click();
    await page
      .getByRole("button", { name: "建立知识候选", exact: true })
      .click();
    assert.equal(
      await page.getByLabel("候选标题").inputValue(),
      "合成浏览器知识候选",
    );
    const candidate = page.waitForResponse(
      (r) => r.request().method() === "POST" && r.url().endsWith("/knowledge"),
    );
    await page
      .getByRole("button", { name: "保存待完善候选", exact: true })
      .click();
    const candidateResponse = await candidate;
    assert.equal(candidateResponse.status(), 201);
    const knowledge = await candidateResponse.json();
    assert.equal(knowledge.workflow, "candidate");
    await page.reload();
    await page
      .getByRole("heading", { name: "企业知识", exact: true })
      .waitFor();

    await page.goto(origin + "/knowledge?item=" + config.journeys.knowledge_id);
    await page
      .getByLabel("维护依据与原因")
      .fill("隔离合成原件范围核对，仅验证发布状态机");
    await page
      .getByRole("button", { name: "完善后送明确发布", exact: true })
      .click();
    await page
      .getByRole("button", { name: "明确发布此版本", exact: true })
      .waitFor();
    await page
      .getByLabel("维护依据与原因")
      .fill("隔离合成知识明确发布，非真实验收");
    await page
      .getByRole("button", { name: "明确发布此版本", exact: true })
      .click();
    await page
      .getByRole("button", { name: "停用当前发布版本", exact: true })
      .waitFor();
    await page.reload();
    await page.getByLabel("维护依据与原因").fill("隔离撤回，原版不得继续新用");
    await page
      .getByRole("button", { name: "停用当前发布版本", exact: true })
      .click();
    await page
      .getByText("停用已记录，旧报告与原件继续留存。", { exact: true })
      .waitFor();
    const withdrawn = await (
      await context.request.get(
        origin + "/api/v1/knowledge/" + config.journeys.knowledge_id,
      )
    ).json();
    assert.equal(withdrawn.workflow, "withdrawn");
    assert.equal(withdrawn.published_workflow, "withdrawn");
    assert.equal(withdrawn.state, "withdrawn");
    const directory = await (
      await context.request.get(
        origin + "/api/v1/knowledge?state=published&purpose=assist",
      )
    ).json();
    assert.ok(
      !directory.items.some((item) => item.id === config.journeys.knowledge_id),
    );

    await goto("settings");
    const predictionSwitch = page.getByRole("switch", {
      name: /^显示预测数值/,
    });
    await predictionSwitch.waitFor();
    const originalVisibility = await predictionSwitch.isChecked();
    await predictionSwitch.setChecked(!originalVisibility);
    const configured = page.waitForResponse(
      (r) => r.request().method() === "PATCH" && r.url().endsWith("/settings"),
    );
    await page
      .getByRole("button", { name: "保存当前项目设置", exact: true })
      .click();
    assert.equal((await configured).status(), 200);
    await page.reload();
    await predictionSwitch.waitFor();
    assert.equal(await predictionSwitch.isChecked(), !originalVisibility);
    await predictionSwitch.setChecked(originalVisibility);
    const restored = page.waitForResponse(
      (r) => r.request().method() === "PATCH" && r.url().endsWith("/settings"),
    );
    await page
      .getByRole("button", { name: "保存当前项目设置", exact: true })
      .click();
    assert.equal((await restored).status(), 200);

    await goto("tasks");
    await page
      .getByRole("button", { name: "新建任务模板", exact: true })
      .click();
    await page
      .getByLabel("模板名称", { exact: true })
      .fill("合成原生本地补遗核对");
    await page
      .getByLabel("任务类型", { exact: true })
      .selectOption("supplement_impact");
    await page
      .getByLabel("任务说明", { exact: true })
      .fill("仅核对已登记效力关系，不调用模型");
    await page
      .getByRole("button", { name: "保存任务模板，不运行", exact: true })
      .click();
    await page.locator(".task-template-card").waitFor();
    await page.reload();
    await page
      .getByRole("button", { name: "暂停后续触发", exact: true })
      .click();
    await page
      .getByRole("button", { name: "恢复后续触发", exact: true })
      .click();
    const started = page.waitForResponse(
      (r) => r.request().method() === "POST" && r.url().endsWith("/runs"),
    );
    await page
      .getByRole("button", { name: "手动运行当前版本", exact: true })
      .click();
    const startedResponse = await started;
    assert.equal(startedResponse.status(), 202);
    const run = await startedResponse.json();
    assert.equal(run.state, "succeeded");
    assert.equal(run.frozen_manifest.task_kind, "supplement_impact");
    await goto("tasks");
    const repeated = page.waitForResponse(
      (r) => r.request().method() === "POST" && r.url().endsWith("/runs"),
    );
    await page
      .getByRole("button", { name: "手动运行当前版本", exact: true })
      .click();
    const repeatedResponse = await repeated;
    assert.equal(repeatedResponse.status(), 202);
    assert.equal((await repeatedResponse.json()).id, run.id);
    assert.equal(repeatedResponse.headers()["task-run-reused"], "true");
    await page
      .getByRole("button", { name: "新建任务模板", exact: true })
      .click();
    await page.getByLabel("模板名称", { exact: true }).fill("合成只排队再取消");
    await page
      .getByLabel("任务类型", { exact: true })
      .selectOption("denial_check");
    await page
      .getByLabel("任务说明", { exact: true })
      .fill("不执行模型，在队列阶段明确取消");
    await page
      .getByRole("button", { name: "收起表单，保留输入", exact: true })
      .click();
    await page
      .getByRole("button", { name: "新建任务模板", exact: true })
      .click();
    assert.equal(
      await page.getByLabel("模板名称", { exact: true }).inputValue(),
      "合成只排队再取消",
    );
    await page
      .getByRole("button", { name: "保存任务模板，不运行", exact: true })
      .click();
    const cancelCard = page
      .locator(".task-template-card")
      .filter({ hasText: "合成只排队再取消" });
    const queued = page.waitForResponse(
      (r) => r.request().method() === "POST" && r.url().endsWith("/runs"),
    );
    await cancelCard
      .getByRole("button", { name: "手动运行当前版本", exact: true })
      .click();
    const queuedResponse = await queued;
    assert.equal(queuedResponse.status(), 202);
    const cancellingRun = await queuedResponse.json();
    assert.equal(cancellingRun.state, "queued");
    await page
      .getByRole("button", { name: "取消本次在途处理", exact: true })
      .click();
    await page
      .getByLabel("取消原因", { exact: true })
      .fill("隔离验证取消恢复，不进行模型调用");
    const cancellation = page.waitForResponse(
      (r) => r.request().method() === "POST" && r.url().endsWith("/cancel"),
    );
    await page
      .getByRole("button", { name: "请求取消当前处理", exact: true })
      .click();
    const cancellationResponse = await cancellation;
    assert.equal(cancellationResponse.status(), 200);
    assert.equal((await cancellationResponse.json()).state, "cancel_requested");
    await page.reload();
    await page
      .getByText("取消请求已收到，尚未记录取消终态；在途调用可能已产生费用。", {
        exact: true,
      })
      .waitFor();
    const lifecycle = await lifecycleUi({
      page,
      context,
      origin,
      browser,
      bid: config.journeys.lifecycle_bid,
      template: run.frozen_manifest.configuration,
      submitted: config.journeys.submitted_bid,
      workBid: config.bid,
    });
    assert.deepEqual(errors, []);
    return {
      run_id: run.id,
      cancel_run_id: cancellingRun.id,
      plan_id: plan.id,
      knowledge_id: knowledge.id,
      pricing_ui_saved: true,
      human_decision_ui: true,
      settings_toggle_persisted: true,
      knowledge_candidate_saved: true,
      knowledge_published_then_withdrawn: true,
      task_duplicate_reused: true,
      task_cancel_requested: true,
      archive_blocks_new_task: true,
      task_ui_local_success: true,
      ...lifecycle,
      anonymous_denied: true,
      model_calls: 0,
    };
  } catch (error) {
    console.error(
      JSON.stringify({
        url: page.url(),
        body: (await body()).slice(-5000),
        select_values: await page
          .locator("select")
          .evaluateAll((nodes) => nodes.map((node) => node.value)),
        errors,
      }),
    );
    throw error;
  } finally {
    await context.close();
  }
}
