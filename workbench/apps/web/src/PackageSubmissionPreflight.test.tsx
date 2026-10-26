import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { PackageSubmissionPreflight } from "./PackageSubmissionPreflight";
import { submissionPreflightFixture } from "./packageSubmissionPreflightFixtures.test-support";
import {
  submissionId as id,
  submissionScope,
} from "./packageSubmissionFixtures.test-support";
import { validateSubmissionPreflight } from "./packageSubmissionPreflightProtocol";
import { jsonDigest } from "./editorSchema";

const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
async function setup() {
  const fixture = await submissionPreflightFixture();
  const server = {
    fixture,
    requests: [] as { url: string; body: unknown; headers: Headers }[],
    next: null as (() => Promise<Response>) | null,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      expect(init.method).toBe("POST");
      expect(String(url)).toMatch(/\/submission-preflight$/);
      server.requests.push({
        url: String(url),
        body: JSON.parse(String(init.body)),
        headers: new Headers(init.headers),
      });
      return server.next ? server.next() : response(fixture.result);
    }),
  );
  return server;
}

it("requires an explicit action and binds the full preview request and current ETag", async () => {
  const s = await setup();
  render(
    <PackageSubmissionPreflight
      scope={submissionScope}
      preview={s.fixture.preview}
    />,
  );
  expect(s.requests).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "核验所选整包原件" }));
  expect(await screen.findByText("本次原件核验已完成")).toBeVisible();
  expect(screen.getByText(/已与原核查逐项匹配/)).toBeVisible();
  expect(screen.getByText(/标准登记仍未获准/)).toBeVisible();
  expect(s.requests).toHaveLength(1);
  expect(s.requests[0].headers.get("If-Match")).toBe(
    s.fixture.preview.bid_etag,
  );
  expect(s.requests[0].body).toEqual({
    selection: s.fixture.preview.selection_request,
    input_digest: s.fixture.preview.input_digest,
  });
});

it("clears the old receipt before a retry and never retains success after failure", async () => {
  const s = await setup();
  render(
    <PackageSubmissionPreflight
      scope={submissionScope}
      preview={s.fixture.preview}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "核验所选整包原件" }));
  await screen.findByText("本次原件核验已完成");
  let resolve: (value: Response) => void = () => {};
  s.next = () =>
    new Promise<Response>((done) => {
      resolve = done;
    });
  fireEvent.click(screen.getByRole("button", { name: "核验所选整包原件" }));
  expect(screen.queryByText("本次原件核验已完成")).not.toBeInTheDocument();
  await act(async () =>
    resolve(
      response(
        {
          code: "PACKAGE_SUBMISSION_PREFLIGHT_CONTEXT_CHANGED",
          message: "来源在读取期间已撤回",
        },
        409,
      ),
    ),
  );
  expect(await screen.findByText("来源在读取期间已撤回")).toBeVisible();
  expect(screen.queryByText("本次原件核验已完成")).not.toBeInTheDocument();
});

it.each(["member", "project", "new-preview"])(
  "discards an old late reply after %s changes",
  async (change) => {
    const s = await setup();
    let resolve: (value: Response) => void = () => {};
    s.next = () =>
      new Promise<Response>((done) => {
        resolve = done;
      });
    const v = render(
      <PackageSubmissionPreflight
        scope={submissionScope}
        preview={s.fixture.preview}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "核验所选整包原件" }));
    const preview = structuredClone(s.fixture.preview),
      scope = { ...submissionScope };
    if (change === "member") scope.memberId = id(901);
    else if (change === "project") scope.bidId = id(902);
    else {
      preview.gate.manifest.checked_at = "2026-10-26T03:01:00Z";
      preview.gate.digest = await jsonDigest(preview.gate.manifest);
    }
    v.rerender(<PackageSubmissionPreflight scope={scope} preview={preview} />);
    await act(async () => resolve(response(s.fixture.result)));
    expect(screen.queryByText("本次原件核验已完成")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/原件复核回执与当前项目/),
    ).not.toBeInTheDocument();
  },
);

it("clears success on session expiry and ignores a pending late reply", async () => {
  const s = await setup();
  render(
    <PackageSubmissionPreflight
      scope={submissionScope}
      preview={s.fixture.preview}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "核验所选整包原件" }));
  await screen.findByText("本次原件核验已完成");
  let resolve: (value: Response) => void = () => {};
  s.next = () =>
    new Promise<Response>((done) => {
      resolve = done;
    });
  fireEvent.click(screen.getByRole("button", { name: "核验所选整包原件" }));
  act(() => window.dispatchEvent(new Event("session-expired")));
  await act(async () => resolve(response(s.fixture.result)));
  expect(screen.getByText(/登录状态已变化/)).toBeVisible();
  expect(screen.queryByText("本次原件核验已完成")).not.toBeInTheDocument();
});

it("never starts when disabled and coalesces rapid clicks", async () => {
  const s = await setup();
  const v = render(
    <PackageSubmissionPreflight
      scope={submissionScope}
      preview={s.fixture.preview}
      disabled
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "核验所选整包原件" }));
  expect(s.requests).toHaveLength(0);
  v.rerender(
    <PackageSubmissionPreflight
      scope={submissionScope}
      preview={s.fixture.preview}
    />,
  );
  const button = screen.getByRole("button", { name: "核验所选整包原件" });
  fireEvent.click(button);
  fireEvent.click(button);
  await screen.findByText("本次原件核验已完成");
  expect(s.requests).toHaveLength(1);
});

it.each([
  "actor",
  "bid",
  "revision",
  "input",
  "selection",
  "etag",
  "bytes",
  "missing-original",
  "duplicate-original",
  "runtime",
  "grant",
  "risk",
  "private-key",
])("rejects a resealed but mismatched %s receipt", async (change) => {
  const { preview, result } = await submissionPreflightFixture();
  const m = result.manifest;
  if (change === "actor") m.actor_id = id(999);
  else if (change === "bid") m.subject.bid_id = id(999);
  else if (change === "revision") m.subject.revision_id = id(999);
  else if (change === "input") m.input_digest = "0".repeat(64);
  else if (change === "selection") m.selection_digest = "0".repeat(64);
  else if (change === "etag") m.bid_etag = '"wrong"';
  else if (change === "bytes") m.originals[0].digest = "0".repeat(64);
  else if (change === "missing-original") m.originals.pop();
  else if (change === "duplicate-original")
    m.originals.push(structuredClone(m.originals[0]));
  else if (change === "runtime")
    m.review_runtime.current_input_digest = "0".repeat(64);
  else if (change === "grant") (m as Record<string, unknown>).allowed = true;
  else if (change === "risk")
    m.gates.known_blocking_risks.history_complete =
      !m.gates.known_blocking_risks.history_complete;
  else
    (m.originals[0] as Record<string, unknown>).object_key = "private locator";
  m.gates.current_input.original_count = m.originals.length;
  m.gates.current_input.originals_digest = await jsonDigest(m.originals);
  result.digest = await jsonDigest(m);
  await expect(
    validateSubmissionPreflight(result, preview, submissionScope),
  ).rejects.toThrow();
});

it("keeps an unselected review unknown even after all original bytes are checked", async () => {
  const f = await submissionPreflightFixture(false);
  await expect(
    validateSubmissionPreflight(f.result, f.preview, submissionScope),
  ).resolves.toEqual(f.result);
  expect(f.result.manifest.gates.current_input.state).toBe("unknown");
});

it("removes a completed receipt immediately when its preview is replaced", async () => {
  const s = await setup();
  const v = render(
    <PackageSubmissionPreflight
      scope={submissionScope}
      preview={s.fixture.preview}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "核验所选整包原件" }));
  await screen.findByText("本次原件核验已完成");
  const next = structuredClone(s.fixture.preview);
  next.input_digest = "0".repeat(64);
  v.rerender(
    <PackageSubmissionPreflight scope={submissionScope} preview={next} />,
  );
  await waitFor(() =>
    expect(screen.queryByText("本次原件核验已完成")).not.toBeInTheDocument(),
  );
});

it.each(["drop-blocker", "downgrade-severity"])(
  "does not accept a resealed %s that erases the preview's existing metadata block",
  async (change) => {
    const { preview, result } = await submissionPreflightFixture();
    preview.gate.manifest.gates.current_input.state = "blocked";
    preview.gate.manifest.gates.current_input.codes.push(
      "CURRENT_IDENTITY_UNCONFIRMED",
    );
    preview.gate.manifest.state = "blocked";
    preview.gate.digest = await jsonDigest(preview.gate.manifest);
    if (change === "downgrade-severity") {
      result.manifest.gates.current_input.codes.push(
        "CURRENT_IDENTITY_UNCONFIRMED",
      );
      result.manifest.gates.current_input.state = "unknown";
    }
    result.digest = await jsonDigest(result.manifest);
    await expect(
      validateSubmissionPreflight(result, preview, submissionScope),
    ).rejects.toThrow();
  },
);
