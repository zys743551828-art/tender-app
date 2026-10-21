export type TextChange = { kind: "equal" | "removed" | "added"; text: string };
export type TextDifference = {
  changes: TextChange[];
  blockComparison: boolean;
};

const MAX_COMPARISON_CELLS = 250_000;
const MAX_GRAPHEMES = 100_000;

function units(text: string): string[] {
  if (text.length > MAX_GRAPHEMES || typeof Intl.Segmenter !== "function")
    return Array.from(text);
  const segmenter = new Intl.Segmenter("zh", { granularity: "grapheme" });
  return Array.from(segmenter.segment(text), (part) => part.segment);
}

/** A bounded visual comparison. Every input character remains on its original side. */
export function textDifference(before: string, after: string): TextDifference {
  if (before === after)
    return {
      changes: before ? [{ kind: "equal", text: before }] : [],
      blockComparison: false,
    };
  const left = units(before),
    right = units(after);
  let prefix = 0,
    suffix = 0;
  while (
    prefix < left.length &&
    prefix < right.length &&
    left[prefix] === right[prefix]
  )
    prefix++;
  while (
    suffix < left.length - prefix &&
    suffix < right.length - prefix &&
    left[left.length - suffix - 1] === right[right.length - suffix - 1]
  )
    suffix++;
  const a = left.slice(prefix, left.length - suffix),
    b = right.slice(prefix, right.length - suffix);
  const changes: TextChange[] = [];
  function append(kind: TextChange["kind"], text: string) {
    if (!text) return;
    const previous = changes.at(-1);
    if (previous?.kind === kind) previous.text += text;
    else changes.push({ kind, text });
  }
  append("equal", left.slice(0, prefix).join(""));
  const cells = (a.length + 1) * (b.length + 1);
  const blockComparison = cells > MAX_COMPARISON_CELLS;
  if (blockComparison || !a.length || !b.length) {
    append("removed", a.join(""));
    append("added", b.join(""));
  } else {
    const width = b.length + 1;
    const lengths = new Uint32Array(cells);
    for (let i = a.length - 1; i >= 0; i--) {
      for (let j = b.length - 1; j >= 0; j--)
        lengths[i * width + j] =
          a[i] === b[j]
            ? lengths[(i + 1) * width + j + 1] + 1
            : Math.max(
                lengths[(i + 1) * width + j],
                lengths[i * width + j + 1],
              );
    }
    let i = 0,
      j = 0;
    while (i < a.length || j < b.length) {
      if (i < a.length && j < b.length && a[i] === b[j]) {
        append("equal", a[i++]);
        j++;
      } else if (
        i < a.length &&
        (j === b.length ||
          lengths[(i + 1) * width + j] >= lengths[i * width + j + 1])
      )
        append("removed", a[i++]);
      else append("added", b[j++]);
    }
  }
  append("equal", suffix ? left.slice(left.length - suffix).join("") : "");
  return { changes, blockComparison };
}
