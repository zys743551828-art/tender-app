import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { TextChangePreview } from "./TextChangePreview";

it("shows full original and proposal and keeps mobile switching separate from applying", async () => {
  const user = userEvent.setup();
  const { container, rerender } = render(
    <TextChangePreview before={"工期30天\n原文"} after={"工期45天\n原文"} />,
  );
  expect(screen.getByLabelText("修改前全文").textContent).toBe(
    "工期30天\n原文",
  );
  expect(screen.getByLabelText("拟修改后全文").textContent).toBe(
    "工期45天\n原文",
  );
  expect(screen.getByRole("button", { name: "拟修改后" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await user.click(screen.getByRole("button", { name: "修改前" }));
  expect(container.firstChild).toHaveAttribute("data-side", "before");
  expect(screen.getByRole("button", { name: "修改前" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  rerender(
    <TextChangePreview before={"工期30天\n原文"} after={"工期50天\n新尾段"} />,
  );
  expect(screen.getByLabelText("拟修改后全文").textContent).toBe(
    "工期50天\n新尾段",
  );
  expect(screen.queryByRole("button", { name: /应用|采纳/ })).toBeNull();
});
