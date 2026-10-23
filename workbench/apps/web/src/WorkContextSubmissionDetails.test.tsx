import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WorkContextSubmissionDetails } from "./WorkContextSubmissionDetails";
import {
  submissionFixture,
  submissionReceipt,
  submissionScope,
  submissionId,
  submissionEtag,
} from "./packageSubmissionFixtures.test-support";
import type { PackageSubmissionView, WorkContextSelection } from "./contracts";

const fetchMock = vi.fn();
let record: PackageSubmissionView,
  selection: Extract<WorkContextSelection, { kind: "package_submission" }>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  const f = await submissionFixture(),
    receipt = await submissionReceipt(f, {
      key: submissionId(20),
      body: f.body,
      etag: submissionEtag(),
      supersedesId: null,
    });
  record = receipt.submission;
  const subject = record.package_binding.manifest.subject;
  selection = {
    kind: "package_submission",
    bid_id: submissionScope.bidId,
    package_id: subject.package_id,
    revision_id: subject.revision_id,
    package_digest: subject.package_digest,
    submission_id: record.id,
    package_binding_digest: record.package_binding.digest,
    inventory: null,
    review_run: null,
  };
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify(record), {
      headers: { "Content-Type": "application/json" },
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());
it("reads the original submission binding without a new registration or official label form", async () => {
  render(
    <WorkContextSubmissionDetails selection={selection} onClose={vi.fn()} />,
  );
  await screen.findByText(record.explanation);
  expect(
    fetchMock.mock.calls.every(
      ([, init]) => !init?.method || init.method === "GET",
    ),
  ).toBe(true);
  expect(
    screen.queryByRole("button", { name: /登记|保存成绩|核验成绩/ }),
  ).not.toBeInTheDocument();
});
it("rejects a different frozen binding even when the submission ID matches", async () => {
  render(
    <WorkContextSubmissionDetails
      selection={{ ...selection, package_binding_digest: "f".repeat(64) }}
      onClose={vi.fn()}
    />,
  );
  await screen.findByText(/实交原记录与所选固定包身份不一致/);
  expect(screen.queryByText(record.explanation)).not.toBeInTheDocument();
});
it("does not restore a late submission after its original panel closes", async () => {
  let done: ((v: Response) => void) | undefined;
  fetchMock.mockImplementation(
    () =>
      new Promise<Response>((resolve) => {
        done = resolve;
      }),
  );
  const view = render(
    <WorkContextSubmissionDetails selection={selection} onClose={vi.fn()} />,
  );
  view.unmount();
  await act(async () =>
    done!(
      new Response(JSON.stringify(record), {
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  expect(screen.queryByText(record.explanation)).not.toBeInTheDocument();
});
