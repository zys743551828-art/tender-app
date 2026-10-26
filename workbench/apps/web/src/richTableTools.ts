import type { AuthoringRichTable, AuthoringRichCell } from "./contracts";
import { validateEditableContent } from "./richEditorSchema";

type Origin = { row: number; column: number; cell: AuthoringRichCell };
function checked(table: AuthoringRichTable) {
  validateEditableContent({
    type: "doc",
    attrs: { title: "表格", ordinal: 0, rule_ids: [], source_refs: [] },
    content: [table],
  });
}
export function tableGrid(table: AuthoringRichTable) {
  checked(table);
  const grid: Origin[][] = Array.from(
    { length: table.content.length },
    () => [],
  );
  const origins: Origin[] = [];
  table.content.forEach((row, y) => {
    let x = 0;
    row.content.forEach((cell) => {
      while (grid[y][x]) x++;
      const origin = { row: y, column: x, cell };
      origins.push(origin);
      for (let yy = y; yy < y + cell.attrs.rowspan; yy++)
        for (let xx = x; xx < x + cell.attrs.colspan; xx++)
          grid[yy][xx] = origin;
      x += cell.attrs.colspan;
    });
  });
  return { grid, origins };
}
function emptyCell(header = false): AuthoringRichCell {
  return {
    type: "tableCell",
    attrs: { id: crypto.randomUUID(), colspan: 1, rowspan: 1, header },
    content: [
      { type: "paragraph", attrs: { id: crypto.randomUUID() }, content: [] },
    ],
  };
}
export function createTable(
  rows: number,
  columns: number,
  width: number,
  caption: string,
  header: boolean,
  repeatHeader = false,
): AuthoringRichTable {
  if (
    !Number.isSafeInteger(rows) ||
    !Number.isSafeInteger(columns) ||
    !Number.isSafeInteger(width) ||
    rows < 1 ||
    rows > 200 ||
    columns < 1 ||
    columns > 100 ||
    rows * columns > 10000 ||
    width < columns ||
    width > 20000
  )
    throw new Error(
      "表格须为1–200行、1–100列，总网格不超过10000；总宽须为有效正整数。",
    );
  const widths = Array.from(
    { length: columns },
    (_, i) => Math.floor(width / columns) + (i < width % columns ? 1 : 0),
  );
  const table: AuthoringRichTable = {
    type: "table",
    attrs: {
      id: crypto.randomUUID(),
      column_widths_twips: widths,
      caption,
      ...(repeatHeader
        ? {
            pagination: {
              protocol: "authoring-table-pagination/1" as const,
              repeat_header_rows: 1 as const,
            },
          }
        : {}),
    },
    content: Array.from({ length: rows }, (_, index) => ({
      type: "tableRow",
      attrs: { id: crypto.randomUUID() },
      content: Array.from({ length: columns }, () =>
        emptyCell(header && index === 0),
      ),
    })),
  };
  checked(table);
  return table;
}

/** Merge only a rectangle of complete cells; retain every paragraph in reading order. */
export function mergeTable(
  table: AuthoringRichTable,
  firstRow: number,
  firstColumn: number,
  rowSpan: number,
  columnSpan: number,
): AuthoringRichTable {
  const { grid, origins } = tableGrid(table);
  const row = firstRow - 1,
    column = firstColumn - 1;
  if (
    ![firstRow, firstColumn, rowSpan, columnSpan].every(
      (n) => Number.isSafeInteger(n) && n > 0,
    ) ||
    row + rowSpan > grid.length ||
    column + columnSpan > table.attrs.column_widths_twips.length ||
    rowSpan * columnSpan === 1
  )
    throw new Error("请选择表格范围内至少两个完整单元格。");
  const selected = new Set<Origin>();
  for (let y = row; y < row + rowSpan; y++)
    for (let x = column; x < column + columnSpan; x++) selected.add(grid[y][x]);
  for (const origin of selected)
    if (
      origin.row < row ||
      origin.column < column ||
      origin.row + origin.cell.attrs.rowspan > row + rowSpan ||
      origin.column + origin.cell.attrs.colspan > column + columnSpan
    )
      throw new Error(
        "所选范围切过已有合并单元格；请先拆分，或选中其完整范围。",
      );
  const anchor = grid[row][column];
  const content = origins
    .filter((item) => selected.has(item))
    .flatMap((item) => structuredClone(item.cell.content));
  const next = structuredClone(table);
  next.content.forEach((line, y) => {
    line.content = origins
      .filter(
        (origin) =>
          origin.row === y && (!selected.has(origin) || origin === anchor),
      )
      .map((origin) =>
        origin === anchor
          ? {
              ...structuredClone(origin.cell),
              attrs: {
                ...origin.cell.attrs,
                rowspan: rowSpan,
                colspan: columnSpan,
              },
              content,
            }
          : structuredClone(origin.cell),
      );
  });
  checked(next);
  return next;
}

/** The top-left cell keeps its original ID/content; new cells are explicit empty paragraphs. */
export function splitTableCell(
  table: AuthoringRichTable,
  firstRow: number,
  firstColumn: number,
): AuthoringRichTable {
  const { grid, origins } = tableGrid(table);
  if (
    ![firstRow, firstColumn].every((n) => Number.isSafeInteger(n) && n > 0) ||
    firstRow > grid.length ||
    firstColumn > table.attrs.column_widths_twips.length
  )
    throw new Error("请选择表格范围内的单元格。");
  const selected = grid[firstRow - 1][firstColumn - 1];
  if (selected.cell.attrs.rowspan === 1 && selected.cell.attrs.colspan === 1)
    throw new Error("该单元格尚未合并。");
  const nextOrigins = origins
    .filter((origin) => origin !== selected)
    .map((origin) => structuredClone(origin));
  for (
    let y = selected.row;
    y < selected.row + selected.cell.attrs.rowspan;
    y++
  )
    for (
      let x = selected.column;
      x < selected.column + selected.cell.attrs.colspan;
      x++
    ) {
      nextOrigins.push({
        row: y,
        column: x,
        cell:
          y === selected.row && x === selected.column
            ? {
                ...structuredClone(selected.cell),
                attrs: { ...selected.cell.attrs, rowspan: 1, colspan: 1 },
              }
            : emptyCell(selected.cell.attrs.header),
      });
    }
  const next = structuredClone(table);
  next.content.forEach((line, y) => {
    line.content = nextOrigins
      .filter((origin) => origin.row === y)
      .sort((a, b) => a.column - b.column)
      .map((origin) => origin.cell);
  });
  checked(next);
  return next;
}
