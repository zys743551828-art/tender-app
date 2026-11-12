import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { Project } from "./Project";
import { fileSha256 } from "./api";
import type { UploadView } from "./contracts";
import { transferUpload } from "./uploadTransport";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  fileSha256: vi.fn(async () => "a".repeat(64)),
}));
vi.mock("./uploadTransport", async (original) => ({
  ...(await original<typeof import("./uploadTransport")>()),
  transferUpload: vi.fn(),
}));

function json(data: unknown, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), { status, headers });
}
let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;
let received: UploadView[];
let committed: boolean;
let roles: string[];
const operation = { id: "op-1", state: "succeeded", kind: "materials.commit" };
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  received = [];
  committed = false;
  roles = [];
  fetchMock = vi.fn<typeof fetch>(async (url, options) => {
    if (url === "/api/v1/bids/bid-1")
      return json(
        {
          id: "bid-1",
          title: "用途确认测试",
          revision: 1,
          material_revision: 1,
        },
        200,
        { ETag: '"bid-1:r1"' },
      );
    if (String(url).endsWith("/materials"))
      return json({ documents: [], conflicts: [] });
    if (url === "/api/v1/bids/bid-1/uploads") {
      const request = JSON.parse(options?.body as string);
      roles.push(request.role);
      const id = `upload-${roles.length}`;
      received.push({
        id,
        bid_id: "bid-1",
        batch_id: "batch-1",
        filename: request.filename,
        state: "verified",
        binding_id: `binding-${roles.length}`,
      } as UploadView);
      return json({ upload_id: id });
    }
    if (String(url).endsWith("/commit")) {
      committed = true;
      return json({ operation, resource_id: "material-1" }, 202);
    }
    return json({
      id: "batch-1",
      bid_id: "bid-1",
      state: committed ? "committed" : "open",
      uploads: received,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.mocked(transferUpload).mockResolvedValue({
    operation,
    resource_id: "material-1",
  } as Awaited<ReturnType<typeof transferUpload>>);
});

async function selectTwoBodies() {
  render(<Project id="bid-1" onBack={vi.fn()} />);
  await screen.findByRole("heading", { name: "用途确认测试" });
  await userEvent.upload(
    document.querySelector<HTMLInputElement>("#project-files")!,
    [
      new File(["first"], "资审.pdf", { type: "application/pdf" }),
      new File(["second"], "招标文件.pdf", { type: "application/pdf" }),
    ],
  );
  await userEvent.selectOptions(
    screen.getByLabelText("资审.pdf的资料用途"),
    "body",
  );
  await userEvent.selectOptions(
    screen.getByLabelText("招标文件.pdf的资料用途"),
    "body",
  );
}

it("同批多个正文在授权前拦截，保留用途选择而不按文件名改写", async () => {
  await selectTwoBodies();
  await userEvent.click(screen.getByRole("button", { name: "上传并核验原件" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "同一批次只能选择一份投标正文",
  );
  expect(screen.getByLabelText("资审.pdf的资料用途")).toHaveValue("body");
  expect(screen.getByLabelText("招标文件.pdf的资料用途")).toHaveValue("body");
  expect(
    fetchMock.mock.calls.filter(([, options]) => options?.method === "POST"),
  ).toHaveLength(0);
  expect(fileSha256).not.toHaveBeenCalled();
  expect(transferUpload).not.toHaveBeenCalled();
});

it("人工改为正文与招标用途后可上传并确认两份入库", async () => {
  await selectTwoBodies();
  await userEvent.click(screen.getByRole("button", { name: "上传并核验原件" }));
  await screen.findByRole("alert");
  await userEvent.selectOptions(
    screen.getByLabelText("招标文件.pdf的资料用途"),
    "tender",
  );
  await userEvent.click(screen.getByRole("button", { name: "上传并核验原件" }));
  await waitFor(() => expect(transferUpload).toHaveBeenCalledTimes(2));
  const commit = await screen.findByRole(
    "button",
    { name: "确认 2 份资料入库" },
    { timeout: 5000 },
  );
  await waitFor(() => expect(commit).toBeEnabled());
  await userEvent.click(commit);
  expect(
    await screen.findByRole("heading", { name: "本批资料已入库" }),
  ).toBeVisible();
  expect(roles).toEqual(["body", "tender"]);
  const calls = fetchMock.mock.calls.filter(([url]) =>
    String(url).endsWith("/commit"),
  );
  expect(calls).toHaveLength(1);
  expect(JSON.parse(calls[0][1]?.body as string)).toEqual({
    accepted_upload_ids: ["upload-1", "upload-2"],
    accepted_binding_ids: ["binding-1", "binding-2"],
    explicit_partial_acceptance: false,
  });
});
