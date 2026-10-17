import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, it, expect, vi } from "vitest";
import { AuthoringTemplateEditor } from "./AuthoringTemplateEditor";
import type { AuthoringTemplateVersionView } from "./contracts";
const template: AuthoringTemplateVersionView = {
  id: "outline1",
  family_id: "family",
  revision: 1,
  name: "合成目录",
  kind: "outline",
  config: {
    schema_version: 1,
    nodes: [
      {
        key: "root",
        parent_key: null,
        ordinal: 0,
        title: "主章",
        node_type: "chapter",
      },
      {
        key: "child",
        parent_key: "root",
        ordinal: 0,
        title: "子章",
        node_type: "chapter",
      },
    ],
  },
  config_digest: "a".repeat(64),
  schema_digest: "b".repeat(64),
  previous_version_id: null,
  created_by: "member",
  created_at: "2026-10-17T00:00:00Z",
  immutable: true,
  is_builtin: true,
};
beforeEach(() => {
  sessionStorage.clear();
});
it("编辑模板不写当前draft；内置只能另存，删除项包含子项，明确保存才一次创建", async () => {
  const writes: { url: string; init: RequestInit }[] = [];
  const saved = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      writes.push({ url, init });
      return new Response(
        JSON.stringify({ ...template, id: "copy", is_builtin: false }),
        { status: 201 },
      );
    }),
  );
  render(
    <AuthoringTemplateEditor
      template={template}
      etag='"family1"'
      memberId="member"
      disabled={false}
      onSaved={saved}
    />,
  );
  await userEvent.click(screen.getByText("另存模板或保存企业模板新版本"));
  expect(
    screen.queryByRole("button", { name: "保存此企业模板的新版本" }),
  ).not.toBeInTheDocument();
  await userEvent.click(
    screen.getAllByRole("button", { name: "移除此模板项及子项" })[0],
  );
  expect(screen.queryByDisplayValue("子章")).not.toBeInTheDocument();
  expect(writes).toHaveLength(0);
  await userEvent.click(
    screen.getByRole("button", { name: "另存为新的目录模板" }),
  );
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(writes[0].url).toBe("/api/v1/authoring/template-families");
  expect(JSON.parse(writes[0].init.body as string).config.nodes).toEqual([]);
});
it("企业模板追加使用所选版本family实tag，失响应不会改成另存家族", async () => {
  const requests: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      requests.push({ url, init });
      throw new TypeError("lost");
    }),
  );
  render(
    <AuthoringTemplateEditor
      template={{ ...template, is_builtin: false }}
      etag='"actual-family-revision1"'
      memberId="member"
      disabled={false}
      onSaved={vi.fn()}
    />,
  );
  await userEvent.click(screen.getByText("另存模板或保存企业模板新版本"));
  await userEvent.click(
    screen.getByRole("button", { name: "保存此企业模板的新版本" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "恢复原模板保存结果" }),
  );
  expect(requests.map((v) => v.url)).toEqual([
    "/api/v1/authoring/template-families/family/versions",
    "/api/v1/authoring/template-families/family/versions",
  ]);
  expect(requests[0].init.body).toBe(requests[1].init.body);
  expect(new Headers(requests[1].init.headers).get("If-Match")).toBe(
    '"actual-family-revision1"',
  );
  expect(new Headers(requests[0].init.headers).get("Idempotency-Key")).toBe(
    new Headers(requests[1].init.headers).get("Idempotency-Key"),
  );
});
