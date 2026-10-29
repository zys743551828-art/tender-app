import { render, screen } from "@testing-library/react";
import { it, expect } from "vitest";
import { DocumentRelationNotice } from "./DocumentRelationNotice";
import type { DocumentView } from "./contracts";
it("声明补PDF只用实际Word祖先链接，不称受控或继承检查", () => {
  const document: Pick<DocumentView, "bid_id" | "source_relation"> = {
    bid_id: "bid",
    source_relation: {
      source_document_version_id: "actual-word-version",
      kind: "user_declared_same_draft",
      verification: "unverified",
      evidence_ids: [],
    },
  };
  render(<DocumentRelationNotice document={document} />);
  expect(screen.getByText(/对应关系尚未核验/)).toBeVisible();
  expect(
    screen.getByRole("link", { name: "查看对应Word原件与转换状态" }),
  ).toHaveAttribute(
    "href",
    "/bids/bid/materials#word-original-actual-word-version",
  );
  expect(screen.queryByText(/受控转换/)).not.toBeInTheDocument();
});
