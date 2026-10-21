import { afterEach, expect, it } from "vitest";
import { clearRecordedCommands } from "./recordedCommandStorage";

afterEach(() => sessionStorage.clear());

it("clears retrospective inputs and pending commands for the departing account only", () => {
  const scopes = [
    "command-record:package-retrospective",
    "command-record:package-retrospective-knowledge",
    "retrospective-draft",
    "retrospective-selection",
    "retrospective-handoff",
  ];
  for (const scope of scopes)
    for (const member of ["active", "departed"])
      sessionStorage.setItem(
        `tender:${scope}:${member}:bid:submission`,
        "retained",
      );
  sessionStorage.setItem("unrelated", "preserved");
  clearRecordedCommands("active");
  for (const scope of scopes) {
    expect(
      sessionStorage.getItem(`tender:${scope}:active:bid:submission`),
    ).toBe("retained");
    expect(
      sessionStorage.getItem(`tender:${scope}:departed:bid:submission`),
    ).toBeNull();
  }
  clearRecordedCommands();
  expect(Object.keys(sessionStorage)).toEqual(["unrelated"]);
});
