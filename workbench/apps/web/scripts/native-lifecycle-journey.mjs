/* global document */
// Real App controls. Direct HTTP is used only for reads and a competing update.
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

const panel = (page) => page.locator(".project-lifecycle-panel");
const open = async (page, origin, bid) => {
  await page.goto(`${origin}/bids/${bid}/settings`);
  await panel(page)
    .getByRole("heading", { name: "项目阶段与归档", exact: true })
    .waitFor();
};
const read = async (context, origin, bid) =>
  context.request.get(`${origin}/api/v1/bids/${bid}/lifecycle`);
async function compete(context, origin, bid, action, reason) {
  const session = await (
    await context.request.get(origin + "/api/v1/auth/session")
  ).json();
  const current = await read(context, origin, bid);
  const response = await context.request.post(
    `${origin}/api/v1/bids/${bid}/lifecycle`,
    {
      headers: {
        Origin: origin,
        "X-CSRF-Token": session.csrf_token,
        "Idempotency-Key": randomUUID(),
        "If-Match": current.headers().etag,
      },
      data: { action, reason },
    },
  );
  assert.equal(response.status(), 200, await response.text());
  return session;
}
async function change(page, action, reason, { double = false } = {}) {
  const view = panel(page);
  await view.getByRole("button", { name: action, exact: true }).click();
  await view.getByLabel("本次状态变更原因").fill(reason);
  const response = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/lifecycle"),
  );
  if (double)
    await view.locator("form").evaluate((form) => {
      form.requestSubmit();
      form.requestSubmit();
    });
  else
    await view
      .getByRole("button", { name: "确认" + action, exact: true })
      .click();
  const result = await response;
  assert.equal(result.status(), 200, await result.text());
  await view.getByText(/状态变更已记录/).waitFor();
  return result;
}
export async function lifecycleUi({
  page,
  context,
  origin,
  browser,
  bid,
  template,
  submitted,
  workBid,
}) {
  await open(page, origin, workBid);
  await change(
    page,
    "终止本轮工作",
    "在途取消尚未终态时明确终止，不暗中取消其它工作",
  );
  await panel(page)
    .getByText(/仍有后台任务/)
    .waitFor();
  assert.equal(
    await panel(page)
      .getByRole("button", { name: "归档项目", exact: true })
      .count(),
    0,
  );
  await change(page, "重新打开项目", "保留在途取消请求和原资料");
  await open(page, origin, bid);
  let writes = 0;
  const count = (request) => {
    if (
      request.method() === "POST" &&
      request.url().endsWith(`/bids/${bid}/lifecycle`)
    )
      writes++;
  };
  page.on("request", count);
  try {
    await panel(page)
      .getByRole("button", { name: "终止本轮工作", exact: true })
      .click();
    assert.equal(
      await panel(page)
        .getByRole("button", { name: "确认终止本轮工作", exact: true })
        .isDisabled(),
      true,
    );
    await panel(page).getByLabel("本次状态变更原因").fill("取消尚未提交的确认");
    await panel(page)
      .getByRole("button", { name: "取消此次变更", exact: true })
      .click();
    assert.equal(writes, 0);
    assert.equal(
      (await (await read(context, origin, bid)).json()).phase,
      "preparation",
    );
    await change(page, "开始本轮工作", "隔离实际表单开始", { double: true });
    assert.equal(writes, 1, "double submit is one request");
    await panel(page).getByText("工作中", { exact: true }).waitFor();
    await page
      .getByRole("button", { name: "返回项目列表", exact: true })
      .click();
    await page.waitForURL(/\/projects$/);
    await page.goBack();
    await panel(page).getByText("工作中", { exact: true }).waitFor();
    await page.reload();
    await panel(page)
      .getByRole("button", { name: "终止本轮工作", exact: true })
      .click();
    await panel(page).getByLabel("本次状态变更原因").fill("冲突时保留此原因");
    await compete(context, origin, bid, "terminate", "隔离并发另一次变更");
    const conflict = page.waitForResponse(
      (r) => r.request().method() === "POST" && r.url().endsWith("/lifecycle"),
    );
    await panel(page)
      .getByRole("button", { name: "确认终止本轮工作", exact: true })
      .click();
    assert.equal((await conflict).status(), 412);
    await panel(page)
      .getByText(/项目状态已变化/)
      .waitFor();
    assert.equal(
      await panel(page).getByLabel("本次状态变更原因").inputValue(),
      "冲突时保留此原因",
    );
    assert.equal(
      await panel(page)
        .getByRole("button", { name: "确认终止本轮工作", exact: true })
        .isDisabled(),
      true,
    );
    await panel(page)
      .getByRole("button", { name: "重新读取项目状态", exact: true })
      .click();
    await panel(page)
      .getByRole("button", { name: "归档项目", exact: true })
      .waitFor();
    await change(page, "归档项目", "隔离表单明确归档");
    assert.ok((await (await read(context, origin, bid)).json()).archived_at);
    await page.reload();
    await panel(page)
      .getByText(/已归档，只读历史/)
      .waitFor();
    assert.equal(
      (
        await context.request.get(`${origin}/api/v1/bids/${bid}/pricing-plans`)
      ).status(),
      200,
    );
    const session = await (
      await context.request.get(origin + "/api/v1/auth/session")
    ).json();
    const blocked = await context.request.post(
      `${origin}/api/v1/bids/${bid}/task-definitions`,
      {
        headers: {
          Origin: origin,
          "X-CSRF-Token": session.csrf_token,
          "Idempotency-Key": randomUUID(),
          "If-Match": (await read(context, origin, bid)).headers().etag,
        },
        data: template,
      },
    );
    assert.equal(blocked.status(), 409);
    assert.equal((await blocked.json()).code, "PROJECT_WORK_CLOSED");
    await change(page, "重新打开项目", "隔离同轮恢复，历史不变");
    await page.reload();
    await panel(page).getByText("工作中", { exact: true }).waitFor();
    assert.equal(
      (await (await read(context, origin, bid)).json()).archived_at,
      null,
    );
    // Submitted is an explicitly seeded isolated state, not a real submission claim.
    await open(page, origin, submitted);
    await change(page, "结束本轮工作", "隔离已提交状态的结束表单机制");
    await page.reload();
    await panel(page).getByText("已结项", { exact: true }).waitFor();
    const anonymous = await browser.newContext();
    assert.equal((await read(anonymous, origin, bid)).status(), 401);
    await anonymous.close();
    return {
      lifecycle_ui: true,
      active_work_blocks_archive_ui: true,
      cancel_no_write: true,
      double_submit_once: true,
      conflict_requires_reconfirmation: true,
      archive_blocks_new_task: true,
      return_reload_consistent: true,
      end_from_synthetic_submitted_state: true,
    };
  } finally {
    page.off("request", count);
  }
}
export async function lifecycleAck({ page, context, origin, bid }) {
  await open(page, origin, bid);
  const requests = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/lifecycle"))
      requests.push({
        key: request.headers()["idempotency-key"],
        etag: request.headers()["if-match"],
        body: request.postData(),
      });
  });
  await panel(page)
    .getByRole("button", { name: "开始本轮工作", exact: true })
    .click();
  await panel(page)
    .getByLabel("本次状态变更原因")
    .fill("服务端提交后断开一次ACK");
  await panel(page)
    .getByRole("button", { name: "确认开始本轮工作", exact: true })
    .click();
  await panel(page)
    .getByRole("button", { name: "恢复原状态变更回执", exact: true })
    .waitFor();
  await page.waitForFunction(() =>
    Array.from(
      document.querySelectorAll(".project-lifecycle-panel button"),
    ).some(
      (button) =>
        button.textContent?.trim() === "恢复原状态变更回执" && !button.disabled,
    ),
  );
  assert.equal(
    (await (await read(context, origin, bid)).json()).phase,
    "working",
  );
  await compete(context, origin, bid, "terminate", "丢ACK后另一次真实变更");
  const expected = await (await read(context, origin, bid)).json();
  await page.reload();
  await panel(page).getByText("已终止", { exact: true }).waitFor();
  const replay = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/lifecycle"),
  );
  await panel(page)
    .getByRole("button", { name: "恢复原状态变更回执", exact: true })
    .click();
  const ack = await replay;
  assert.equal(ack.status(), 200);
  assert.equal(ack.headers()["idempotent-replayed"], "true");
  await panel(page)
    .getByText(/状态变更已记录/)
    .waitFor();
  await panel(page).getByText("已终止", { exact: true }).waitFor();
  assert.equal(
    (await (await read(context, origin, bid)).json()).revision,
    expected.revision,
  );
  assert.equal(requests.length, 2);
  assert.deepEqual(requests[1], requests[0]);
  return {
    lost_ack_recovered: true,
    exact_key_body_etag: true,
    current_state_after_historical_ack: true,
    bid,
  };
}
export async function lifecycleMember({
  page,
  context,
  origin,
  bid,
  inactive = false,
}) {
  if (inactive) {
    await page.goto(`${origin}/bids/${bid}/settings`);
    await page
      .getByRole("button", { name: "登录工作区", exact: true })
      .waitFor();
    assert.equal(await panel(page).count(), 0);
    assert.equal((await read(context, origin, bid)).status(), 401);
    return { inactive_member_denied: true };
  }
  await open(page, origin, bid);
  await change(page, "终止本轮工作", "另一有效成员按既有共享权限操作");
  await change(page, "重新打开项目", "另一有效成员同轮恢复");
  return { shared_active_member_allowed: true };
}
