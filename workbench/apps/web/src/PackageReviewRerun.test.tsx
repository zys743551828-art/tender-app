import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Execution from "./PackageExecutionInputWorkspace";
import type {
  PackageExecutionInputView,
  PackageReviewEligibilityObservation,
  SavePackageExecutionInput,
} from "./contracts";
import { packageReviewFixture } from "../qa-previews/frozen-inputs/packageReview";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import { frozenManifestDigest } from "./packageFrozenInput";
import { executionScope, executionStorageKey } from "./executionInputRecovery";
vi.mock("./PackageReviewWorkspace", () => ({
  default: ({
    prepared,
    onRequestRerun,
  }: {
    prepared: PackageExecutionInputView;
    onRequestRerun: () => void;
  }) => (
    <section aria-label="核查入口接线">
      <p>{prepared.manifest.identity.rerun?.reason ?? "首次准备"}</p>
      <button onClick={onRequestRerun}>准备复检</button>
    </section>
  ),
}));
let fixture: Awaited<ReturnType<typeof packageReviewFixture>>;
let candidate: PackageReviewEligibilityObservation;
const fetchMock = vi.fn();
const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    status: 201,
    headers: { "Content-Type": "application/json" },
  });
async function response(body: SavePackageExecutionInput) {
  const result = structuredClone(fixture.props.prepared);
  result.manifest.id = body.rerun
    ? id(202)
    : fixture.props.prepared.manifest.id;
  result.manifest.identity.rerun = body.rerun;
  result.manifest.identity.execution_digest = await frozenManifestDigest({
    version: "package-review-execution/1",
    content_digest: result.manifest.identity.content_digest,
    rerun: body.rerun,
  });
  result.digest = await frozenManifestDigest(result.manifest);
  return result;
}
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", fetchMock);
  sessionStorage.clear();
  fetchMock.mockReset();
  fixture = await packageReviewFixture();
  const { frozen } = fixture.props;
  candidate = {
    kind: "eligibility_observation",
    frozen_input_id: frozen.manifest.id,
    frozen_digest: frozen.digest,
    input_digest: frozen.manifest.input_digest,
    checked_at: frozen.manifest.execution_context.as_of,
    current_context: frozen.manifest.execution_context,
    parse_evidence_status: "matched",
    original_verification: "not_performed",
    review_ready: false,
    launch_available: false,
    publication_authorized: false,
    blockers: [
      "PACKAGE_REVIEW_EXECUTOR_NOT_READY",
      "PACKAGE_REVIEW_FACTS_UNPROVEN",
    ],
  };
  fetchMock.mockImplementation(async (_url, options: RequestInit) =>
    json(await response(JSON.parse(String(options.body)))),
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const show = (
  current: PackageReviewEligibilityObservation | null = candidate,
) =>
  render(
    <Execution
      scope={fixture.props.scope}
      frozen={fixture.props.frozen}
      candidate={current}
    />,
  );
async function prepareRerun() {
  await userEvent.click(
    screen.getByRole("button", { name: "保存当前执行准备输入" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "准备复检" }),
  );
  expect(fetchMock).toHaveBeenCalledTimes(1);
  await userEvent.type(
    screen.getByLabelText("本次复检理由"),
    "合成测试：修订技术方案后复检",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "保存带理由的复检准备" }),
  );
}
it("creates a new execution identity only after an explicit rerun reason, without launching from the preparation form", async () => {
  show();
  await prepareRerun();
  await screen.findByText("合成测试：修订技术方案后复检");
  expect(fetchMock).toHaveBeenCalledTimes(2);
  const first = JSON.parse(String(fetchMock.mock.calls[0][1].body)),
    next = JSON.parse(String(fetchMock.mock.calls[1][1].body));
  expect(first.rerun).toBeNull();
  expect(next.rerun.reason).toBe("合成测试：修订技术方案后复检");
  expect(next.rerun.nonce).toMatch(/^[a-f0-9-]{36}$/);
  expect(
    fetchMock.mock.calls.every(([url]) => url.endsWith("/execution-inputs")),
  ).toBe(true);
  const stored = JSON.parse(
    sessionStorage.getItem(
      executionStorageKey(
        executionScope(fixture.props.scope, fixture.props.frozen),
      ),
    )!,
  );
  expect(stored.lastId).toBe(id(202));
  expect(stored.pending).toBeNull();
});
it("retains the original rerun nonce and reason through a lost acknowledgement and restores without a current candidate", async () => {
  fetchMock
    .mockImplementationOnce(async (_url, options: RequestInit) =>
      json(await response(JSON.parse(String(options.body)))),
    )
    .mockRejectedValueOnce(new TypeError("synthetic lost rerun ACK"));
  const view = show();
  await prepareRerun();
  await screen.findByRole("button", { name: "恢复原执行准备请求" });
  const original = fetchMock.mock.calls[1][1] as RequestInit;
  view.unmount();
  show(null);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(screen.getByLabelText("本次复检理由")).toHaveValue(
    "合成测试：修订技术方案后复检",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "恢复原执行准备请求" }),
  );
  await screen.findByText("合成测试：修订技术方案后复检");
  const retry = fetchMock.mock.calls[2][1] as RequestInit;
  expect(retry.body).toBe(original.body);
  expect(new Headers(retry.headers).get("Idempotency-Key")).toBe(
    new Headers(original.headers).get("Idempotency-Key"),
  );
});
