/** Presentation only: switching auxiliary views never authorizes or saves work. */
export type WorkspaceAuxiliary = "assistant" | "directory" | "sources";
const eventName = "tender:workspace-auxiliary-open";

export function announceWorkspaceAuxiliary(
  bidId: string,
  kind: WorkspaceAuxiliary,
) {
  window.dispatchEvent(new CustomEvent(eventName, { detail: { bidId, kind } }));
}

export function listenWorkspaceAuxiliary(
  bidId: string,
  kind: WorkspaceAuxiliary,
  onOther: () => void,
) {
  function receive(event: Event) {
    const detail = (event as CustomEvent<unknown>).detail;
    if (
      detail &&
      typeof detail === "object" &&
      "bidId" in detail &&
      "kind" in detail &&
      detail.bidId === bidId &&
      ["assistant", "directory", "sources"].includes(String(detail.kind)) &&
      detail.kind !== kind
    )
      onOther();
  }
  window.addEventListener(eventName, receive);
  return () => window.removeEventListener(eventName, receive);
}
