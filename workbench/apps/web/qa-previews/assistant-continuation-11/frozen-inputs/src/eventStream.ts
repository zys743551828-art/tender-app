/** Transport framing only: business objects are always fetched from their APIs. */
export type EventFrame = { event: string; id: string; data: string };
export function eventDecoder(emit: (frame: EventFrame) => void) {
  let buffer = "";
  let event = "message";
  let id = "";
  let lines: string[] = [];
  function line(value: string) {
    if (!value) {
      if (lines.length) emit({ event, id, data: lines.join("\n") });
      event = "message";
      id = "";
      lines = [];
      return;
    }
    if (value.startsWith(":")) return;
    const separator = value.indexOf(":");
    const field = separator < 0 ? value : value.slice(0, separator);
    const content =
      separator < 0 ? "" : value.slice(separator + 1).replace(/^ /, "");
    if (field === "event") event = content;
    if (field === "id" && !content.includes("\0")) id = content;
    if (field === "data") lines.push(content);
  }
  return (chunk: string) => {
    buffer += chunk;
    let boundary: number;
    while ((boundary = buffer.indexOf("\n")) >= 0) {
      line(buffer.slice(0, boundary).replace(/\r$/, ""));
      buffer = buffer.slice(boundary + 1);
    }
  };
}

export function changeSequence(
  frame: EventFrame,
  streamId: string,
  bidId: string,
  previous: number,
) {
  if (frame.event !== "change") return null;
  try {
    const value: unknown = JSON.parse(frame.data);
    if (!value || typeof value !== "object") return null;
    const entry = value as Record<string, unknown>;
    const ref = entry.object_ref;
    if (!ref || typeof ref !== "object") return null;
    const objectRef = ref as Record<string, unknown>;
    if (
      entry.stream_id !== streamId ||
      typeof entry.seq !== "number" ||
      !Number.isSafeInteger(entry.seq) ||
      entry.seq <= previous ||
      typeof entry.event_type !== "string" ||
      objectRef.kind !== "bid" ||
      objectRef.id !== bidId ||
      !(
        entry.revision === null ||
        (typeof entry.revision === "number" &&
          Number.isSafeInteger(entry.revision) &&
          entry.revision > 0)
      ) ||
      frame.id !== `${streamId}:${entry.seq}`
    )
      return null;
    return entry.seq;
  } catch {
    return null;
  }
}
