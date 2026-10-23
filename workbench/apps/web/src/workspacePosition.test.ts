import { beforeEach, expect, it, vi } from "vitest";
import {
  loadWorkspacePosition,
  saveWorkspacePosition,
  workspacePositionFromRoute,
} from "./workspacePosition";

const id = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const member = id(1),
  bid = id(2),
  key = `tender:workspace-position:${member}:${bid}`;

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

it("keeps one member's exact package selection separate from other members and projects", () => {
  const route = `/bids/${bid}/packages?package=${id(3)}&revision=${id(4)}&inventory=${id(5)}`;
  saveWorkspacePosition(member, bid, route);
  expect(loadWorkspacePosition(member, bid)?.packageTarget).toEqual({
    packageId: id(3),
    revisionId: id(4),
    inventoryId: id(5),
  });
  expect(loadWorkspacePosition(id(6), bid)).toBeNull();
  expect(loadWorkspacePosition(member, id(7))).toBeNull();
  saveWorkspacePosition(id(6), bid, `/bids/${bid}/materials`);
  expect(loadWorkspacePosition(member, bid)?.page).toBe("packages");
  expect(loadWorkspacePosition(id(6), bid)?.page).toBe("materials");
});

it("ignores legacy records which never established a member identity", () => {
  localStorage.setItem(
    `tender:position:${bid}`,
    JSON.stringify({ page: "review", reviewId: id(8) }),
  );
  expect(loadWorkspacePosition(member, bid)).toBeNull();
});

it("retains an explicit draft or historical review instead of reducing it to the page", () => {
  saveWorkspacePosition(member, bid, `/bids/${bid}/authoring?draft=${id(9)}`);
  expect(loadWorkspacePosition(member, bid)).toMatchObject({
    page: "authoring",
    draftId: id(9),
    reviewId: null,
    packageTarget: null,
  });
  saveWorkspacePosition(member, bid, `/bids/${bid}/matrix?review=${id(10)}`);
  expect(loadWorkspacePosition(member, bid)).toMatchObject({
    page: "matrix",
    draftId: null,
    reviewId: id(10),
  });
});

it.each([
  `/bids/${id(99)}/overview`,
  `/bids/${bid}/authoring?draft=${id(9)}&draft=${id(10)}`,
  `/bids/${bid}/review?review=latest`,
  `/bids/${bid}/review?review=${id(10)}&draft=${id(9)}`,
  `/bids/${bid}/overview?review=${id(10)}`,
  `/bids/${bid}/packages?package=${id(3)}`,
  `/bids/${bid}/packages?package=${id(3)}&revision=${id(4)}&current=true`,
  `/bids/${bid}/packages?package=${id(3)}&revision=${id(4)}#other`,
  `/bids/${bid}/authoring/other`,
])("does not persist an ambiguous or foreign route: %s", (route) => {
  saveWorkspacePosition(member, bid, `/bids/${bid}/materials`);
  const previous = localStorage.getItem(key);
  expect(workspacePositionFromRoute(member, bid, route)).toBeNull();
  saveWorkspacePosition(member, bid, route);
  expect(localStorage.getItem(key)).toBe(previous);
});

it.each([
  { memberId: id(99) },
  { bidId: id(99) },
  { draftId: id(9) },
  { current: true },
  {
    packageTarget: {
      packageId: id(3),
      revisionId: "latest",
      inventoryId: null,
    },
  },
  {
    packageTarget: {
      packageId: id(3),
      revisionId: id(4),
      inventoryId: null,
      current: true,
    },
  },
])("rejects corrupted or relabelled persisted identity: %s", (changes) => {
  const saved = workspacePositionFromRoute(
    member,
    bid,
    `/bids/${bid}/packages?package=${id(3)}&revision=${id(4)}`,
  );
  localStorage.setItem(key, JSON.stringify({ ...saved, ...changes }));
  expect(loadWorkspacePosition(member, bid)).toBeNull();
});

it("does not share an anonymous preference and tolerates unavailable browser storage", () => {
  saveWorkspacePosition("", bid, `/bids/${bid}/materials`);
  expect(localStorage.length).toBe(0);
  expect(loadWorkspacePosition("", bid)).toBeNull();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("storage unavailable");
  });
  expect(() =>
    saveWorkspacePosition(member, bid, `/bids/${bid}/materials`),
  ).not.toThrow();
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("storage unavailable");
  });
  expect(loadWorkspacePosition(member, bid)).toBeNull();
});

it("restores the stage and complete selection fingerprint within one member and project", () => {
  const route = `/bids/${bid}/work-context?stage=build&id=${id(40)}&selection=${"a".repeat(64)}`;
  saveWorkspacePosition(member, bid, route);
  expect(loadWorkspacePosition(member, bid)?.workContext).toEqual({
    stage: "build",
    selected: { kind: "build", id: id(40), selectionDigest: "a".repeat(64) },
  });
  expect(loadWorkspacePosition(id(6), bid)).toBeNull();
  saveWorkspacePosition(
    member,
    bid,
    `/bids/${bid}/work-context?stage=package_review_run`,
  );
  expect(loadWorkspacePosition(member, bid)?.workContext).toEqual({
    stage: "package_review_run",
    selected: null,
  });
});

it.each([
  {
    stage: "build",
    selected: {
      kind: "build",
      id: id(40),
      selectionDigest: "a".repeat(64),
      current: true,
    },
  },
  {
    stage: "draft_snapshot",
    selected: { kind: "build", id: id(40), selectionDigest: "a".repeat(64) },
  },
  {
    stage: "build",
    selected: { kind: "build", id: "latest", selectionDigest: "a".repeat(64) },
  },
  { stage: "build", selected: null, foreignMember: id(6) },
])("rejects ambiguous persisted work-context identity: %s", (workContext) => {
  const saved = workspacePositionFromRoute(
    member,
    bid,
    `/bids/${bid}/work-context?stage=build`,
  );
  localStorage.setItem(key, JSON.stringify({ ...saved, workContext }));
  expect(loadWorkspacePosition(member, bid)).toBeNull();
});
