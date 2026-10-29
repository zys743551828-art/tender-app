import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import InputDetails from "./PackageReviewInputDetails";
import { packageReviewFixture } from "../qa-previews/frozen-inputs/packageReview";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import { scopeReply } from "../qa-previews/frozen-inputs/factScope";
import { frozenManifestDigest } from "./packageFrozenInput";
import { packageReviewPath } from "./packageReviewProtocol";
import { dependencyPlanPath } from "./dependencyPlanProtocol";
let f: Awaited<ReturnType<typeof packageReviewFixture>>;
const json = (data: unknown) =>
  new Response(JSON.stringify(data), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  f = await packageReviewFixture();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function openInput() {
  await userEvent.click(screen.getByText("执行依据与原事实声明"));
  await userEvent.click(
    screen.getByRole("button", { name: "读取本次执行依据" }),
  );
}
it("reads only the exact input and original plan after explicit clicks and never writes or adopts a plan", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(json(f.input))
    .mockResolvedValueOnce(json(f.plan));
  vi.stubGlobal("fetch", fetcher);
  render(<InputDetails {...f.props} run={f.run} />);
  expect(fetcher).not.toHaveBeenCalled();
  await openInput();
  await userEvent.click(
    await screen.findByRole("button", { name: "查看本次采用的原计划" }),
  );
  expect(await screen.findByText(f.plan.manifest.reason)).toBeInTheDocument();
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
    `/api/v1${packageReviewPath(f.props)}/${f.run.id}/input`,
    `/api/v1${dependencyPlanPath(f.props)}/${f.plan.manifest.id}`,
  ]);
  expect(
    fetcher.mock.calls.every(([, options]) => options.method === "GET"),
  ).toBe(true);
  expect(
    screen.queryByRole("button", { name: /选择这份计划/ }),
  ).not.toBeInTheDocument();
});
it("keeps a different correctly hashed plan out of the historical input panel", async () => {
  const plan = structuredClone(f.plan);
  plan.manifest.id = id(998);
  plan.digest = await frozenManifestDigest(plan.manifest);
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(json(f.input))
      .mockResolvedValueOnce(json(plan)),
  );
  render(<InputDetails {...f.props} run={f.run} />);
  await openInput();
  await userEvent.click(
    await screen.findByRole("button", { name: "查看本次采用的原计划" }),
  );
  expect(
    await screen.findByText(/原计划与本次实际执行依据不符/),
  ).toBeInTheDocument();
  expect(screen.queryByText(plan.manifest.reason)).not.toBeInTheDocument();
});
it.each([false, true])(
  "reads a fact declaration by its original identity and rejects substitution=%s",
  async (substitute) => {
    const record = await scopeReply(
      f.props.prepared,
      {
        execution_input_digest: f.props.prepared.digest,
        fact_id: id(80),
        action: "bind",
        subject: { kind: "lot", id: id(61) },
        reason: "合成原声明：适用于本标段",
        previous_digest: null,
      },
      f.props.scope.memberId,
      id(96),
    );
    f.input.manifest.fact_admission.fact_declarations = [
      {
        fact_id: id(80),
        declaration_id: record.manifest.id,
        declaration_digest: record.digest,
      },
    ];
    f.input.digest = await frozenManifestDigest(f.input.manifest);
    f.run.input_digest = f.input.digest;
    const reply = structuredClone(record);
    if (substitute) {
      reply.manifest.id = id(97);
      reply.digest = await frozenManifestDigest(reply.manifest);
    }
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(json(f.input))
      .mockResolvedValueOnce(json(reply));
    vi.stubGlobal("fetch", fetcher);
    render(<InputDetails {...f.props} run={f.run} />);
    await openInput();
    await userEvent.click(
      await screen.findByRole("button", { name: "查看原适用声明" }),
    );
    if (substitute) {
      expect(
        await screen.findByText(/事实声明与本次实际执行依据不符/),
      ).toBeInTheDocument();
      expect(screen.queryByText(reply.manifest.reason)).not.toBeInTheDocument();
    } else {
      expect(
        await screen.findByText(reply.manifest.reason),
      ).toBeInTheDocument();
      expect(screen.getByText(/当前是否仍适用须重新核对/)).toBeInTheDocument();
    }
    expect(fetcher.mock.calls[1][0]).toBe(
      `/api/v1${packageReviewPath(f.props).replace(/\/review-runs$/, "/fact-scope-declarations")}/${record.manifest.id}`,
    );
  },
);
it("ignores a delayed input response after switching the run", async () => {
  let resolve!: (value: Response) => void;
  const fetcher = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    )
    .mockResolvedValueOnce(json(f.input));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<InputDetails {...f.props} run={f.run} />);
  await openInput();
  view.rerender(<InputDetails {...f.props} run={{ ...f.run, id: id(999) }} />);
  resolve(json(f.input));
  await waitFor(() =>
    expect(screen.queryByText(/原方法：/)).not.toBeInTheDocument(),
  );
  await openInput();
  expect(await screen.findByText(/原方法：/)).toBeInTheDocument();
  expect(fetcher.mock.calls[1][0]).toContain(`/${id(999)}/input`);
});
it("exports the validated retained input including its digest", async () => {
  let exported: Blob | null = null;
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = vi.fn((blob: Blob) => {
        exported = blob;
        return "blob:synthetic-input";
      });
      static revokeObjectURL = vi.fn();
    },
  );
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(f.input)));
  render(<InputDetails {...f.props} run={f.run} />);
  await openInput();
  await userEvent.click(
    await screen.findByRole("button", { name: "导出执行依据 JSON" }),
  );
  const text = await new Promise<string>((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(exported!);
  });
  expect(JSON.parse(text)).toEqual(f.input);
});
