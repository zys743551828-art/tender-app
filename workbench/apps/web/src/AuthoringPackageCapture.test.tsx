import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthoringPackageCapture } from "./AuthoringPackageCapture";
import { captureFixture } from "./authoringCaptureFixtures.test-support";
import {
  captureIdentityLabels,
  captureIdentityNames,
} from "./authoringInputCatalogProtocol";
import { captureCommandKey } from "./authoringCaptureCommandProtocol";
import { knowledgeStorageKey } from "./knowledgeStorage";
import { setAuth } from "./api";
import { jsonDigest } from "./editorSchema";
import type { PackageAuthoringInputRequest } from "./contracts";

const f = captureFixture();
const props = { memberId: f.memberId, bidId: f.bidId };
function reply(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function transport(mode: "ok" | "lost" | "wrong" = "ok") {
  const writes: {
    path: string;
    body: PackageAuthoringInputRequest;
    key: string | null;
  }[] = [];
  const unexpected: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      const url = new URL(input, window.location.href);
      if (init.method === "POST") {
        const body = JSON.parse(
          init.body as string,
        ) as PackageAuthoringInputRequest;
        writes.push({
          path: url.pathname,
          body,
          key: new Headers(init.headers).get("Idempotency-Key"),
        });
        if (mode === "lost" && writes.length === 1)
          throw new TypeError("Synthetic lost ACK");
        // UI service simulation: preserve the native response shape while echoing
        // this explicit request's identity order. Raw native fixtures are separate.
        const value = structuredClone(f.saved);
        value.manifest.selection = body;
        if (mode === "wrong") value.manifest.actor_id = crypto.randomUUID();
        value.digest = await jsonDigest(value.manifest);
        return reply(value, 201);
      }
      const row = f.bundle.responses.find(
        (row) =>
          row.name !== "saved" &&
          row.path === url.pathname &&
          Object.entries(row.query).every(
            ([key, value]) => url.searchParams.get(key) === String(value),
          ),
      );
      if (row) return reply(row.body, row.status);
      unexpected.push(url.pathname + url.search);
      return reply(
        { code: "UNEXPECTED_READ", message: "Synthetic unexpected route" },
        404,
      );
    }),
  );
  return { writes, unexpected };
}
beforeEach(() => {
  sessionStorage.clear();
  setAuth({
    member: { id: f.memberId, active: true, display_name: "合成采集验收" },
    csrf_token: "synthetic",
    expires_at: "2099-01-01T00:00:00Z",
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function restoreDraft() {
  sessionStorage.setItem(
    knowledgeStorageKey(f.memberId, f.bidId) +
      "authoring-package-capture:draft",
    JSON.stringify(f.draft),
  );
}

it("requires explicit package, revision, snapshot, node, identity facts and purpose before saving", async () => {
  const calls = transport(),
    onSaved = vi.fn(),
    user = userEvent.setup();
  render(<AuthoringPackageCapture {...props} onSaved={onSaved} />);
  const save = screen.getByRole("button", { name: "保存这份固定编写输入" });
  expect(save).toBeDisabled();
  for (const [label, ref] of [
    ["目标投标包", f.request.package_context.target],
    ["招标与补遗依据包", f.request.package_context.authority],
  ] as const) {
    await waitFor(() =>
      expect(
        within(screen.getByRole("group", { name: label })).getAllByRole(
          "option",
        ),
      ).toHaveLength(2),
    );
    await user.selectOptions(
      screen.getByLabelText(label + "目录"),
      ref.package_id,
    );
    const revision = await within(
      screen.getByRole("group", { name: label }),
    ).findByRole("button", { name: /选择第 1 版/ });
    await user.click(revision);
  }
  await waitFor(() => expect(screen.getByLabelText("需求清单")).toBeEnabled());
  await user.selectOptions(
    screen.getByLabelText("需求清单"),
    f.request.package_context.inventory.id,
  );
  await user.selectOptions(
    screen.getByLabelText("正文快照"),
    f.request.target_section.snapshot_id,
  );
  await user.selectOptions(
    await screen.findByLabelText("快照中的章节"),
    f.request.target_section.section_id,
  );
  await user.selectOptions(
    await screen.findByLabelText("稳定文字节点"),
    f.request.target_section.node_id,
  );
  await user.selectOptions(
    screen.getByLabelText("事实集"),
    f.request.facts.fact_set_id,
  );
  for (const name of captureIdentityNames) {
    await user.selectOptions(
      await screen.findByLabelText(captureIdentityLabels[name]),
      f.draft.identities[name],
    );
  }
  const used = f.facts.items.find(
    (item) => item.fact_id === f.request.facts.uses[0].fact_id,
  )!;
  const factLabel = used.identity_name
    ? captureIdentityLabels[used.identity_name]
    : used.name;
  await user.click(
    screen.getByRole("checkbox", {
      name: new RegExp("将“" + factLabel + "”用于本次编写"),
    }),
  );
  await user.selectOptions(
    screen.getByLabelText("作用对象"),
    f.request.facts.uses[0].subject.kind,
  );
  await user.type(
    screen.getByLabelText("本次用途与理由"),
    f.request.facts.uses[0].reason,
  );
  await waitFor(() => expect(save).toBeEnabled());
  expect(calls.writes).toHaveLength(0);
  await user.click(save);
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
  expect(calls.writes).toHaveLength(1);
  expect(calls.writes[0].body.package_context).toEqual(
    f.request.package_context,
  );
  expect(calls.writes[0].body.target_section).toEqual(f.request.target_section);
  expect(calls.writes[0].body.facts.uses).toEqual(f.request.facts.uses);
  expect(calls.unexpected).toEqual([]);
});

it("restores the exact original request and key after a lost save response and remount", async () => {
  restoreDraft();
  const calls = transport("lost"),
    onSaved = vi.fn(),
    user = userEvent.setup();
  const view = render(<AuthoringPackageCapture {...props} onSaved={onSaved} />);
  const save = screen.getByRole("button", { name: "保存这份固定编写输入" });
  await waitFor(() => expect(save).toBeEnabled());
  await user.click(save);
  await screen.findByRole("button", { name: "恢复原保存请求" });
  expect(onSaved).not.toHaveBeenCalled();
  view.unmount();
  render(<AuthoringPackageCapture {...props} onSaved={onSaved} />);
  const retry = await screen.findByRole("button", { name: "恢复原保存请求" });
  await user.click(retry);
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
  expect(calls.writes).toHaveLength(2);
  expect(calls.writes[1]).toEqual(calls.writes[0]);
  expect(sessionStorage.getItem(captureCommandKey(props))).toBeNull();
});

it("preserves recovery and local input when the ACK belongs to a different actor", async () => {
  restoreDraft();
  const calls = transport("wrong"),
    onSaved = vi.fn(),
    user = userEvent.setup();
  render(<AuthoringPackageCapture {...props} onSaved={onSaved} />);
  const save = screen.getByRole("button", { name: "保存这份固定编写输入" });
  await waitFor(() => expect(save).toBeEnabled());
  await user.click(save);
  await screen.findByRole("button", { name: "恢复原保存请求" });
  expect(onSaved).not.toHaveBeenCalled();
  expect(calls.writes).toHaveLength(1);
  expect(sessionStorage.getItem(captureCommandKey(props))).not.toBeNull();
  expect(screen.getByLabelText("本次用途与理由")).toHaveValue(
    f.draft.uses[0].reason,
  );
});
