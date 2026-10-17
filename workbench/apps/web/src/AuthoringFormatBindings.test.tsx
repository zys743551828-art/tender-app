import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { it, expect, vi } from "vitest";
import { AuthoringFormatBindings } from "./AuthoringFormatBindings";
it("格式绑定只选已确认要求，用可信原页投影；来源不可新用时不构造ref", async () => {
  const changed = vi.fn();
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      requests.push(url);
      if (url.endsWith("/rules"))
        return new Response(
          JSON.stringify({
            rules: [
              {
                id: "confirmed",
                statement: "已确认字体要求",
                confirmation: "confirmed",
                provenance_status: "effective",
                evidence_ids: ["evidence"],
              },
              {
                id: "pending",
                statement: "未确认字号要求",
                confirmation: "pending",
                provenance_status: "effective",
                evidence_ids: [],
              },
            ],
          }),
        );
      if (url.endsWith("/authoring-reference"))
        return new Response(
          JSON.stringify({
            bid_id: "bid",
            evidence_id: "evidence",
            authoring_reference: null,
            reasons: ["来源已撤回"],
          }),
        );
      throw new Error("unexpected");
    }),
  );
  render(
    <AuthoringFormatBindings
      bidId="bid"
      bindings={[]}
      disabled={false}
      onChange={changed}
    />,
  );
  await userEvent.click(screen.getByText("项目格式要求优先绑定 · 0个字段"));
  await screen.findByRole("option", { name: "已确认字体要求" });
  expect(
    screen.queryByRole("option", { name: "未确认字号要求" }),
  ).not.toBeInTheDocument();
  await userEvent.selectOptions(
    screen.getByLabelText("已确认的项目要求"),
    "confirmed",
  );
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.selectOptions(
    screen.getByLabelText("字段值"),
    "Noto Sans CJK SC",
  );
  await userEvent.type(
    screen.getByLabelText("原文如何支持此字段"),
    "原页明确字体，仅人工解释此字段",
  );
  await userEvent.click(screen.getByRole("button", { name: "加入格式预览" }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "格式依据当前不可用于编写",
    ),
  );
  expect(changed).not.toHaveBeenCalled();
  expect(requests).toContain("/api/v1/evidence/evidence/authoring-reference");
});
