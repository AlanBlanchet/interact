/** The pixel engine: a char grid in, crisp SVG out.
 *
 *  Every piece of art in this view — a person, a server rack, a coffee machine — is authored as
 *  rows of characters and coloured by a palette. Nothing here knows what it is drawing, which is
 *  the point: the art is DATA (`art.ts`), this file is the only renderer, and a new prop costs a
 *  string literal rather than a hand-tuned SVG path.
 *
 *  Two things it does that authoring by hand would not:
 *   - the OUTLINE is derived, never drawn. Any empty cell touching a solid one becomes ink, so a
 *     sprite always reads against whatever wall it stands on and the art stays about the shape.
 *   - runs of one colour merge into one `<rect>`, so a 10x16 person costs ~25 nodes, not 160.
 */

/** Rows of equal length. `.` is empty; every other char is a palette key. */
export type Grid = readonly string[];

/** Palette key to any CSS colour — a literal, or a `var(--vscode-…)` so it follows the theme. */
export type Palette = Readonly<Record<string, string>>;

export const EMPTY = ".";
/** Reserved: the derived outline writes into cells with this key. */
export const INK = "#";

export interface DrawOptions {
  /** Cell size in CSS pixels. Integers only — a fractional scale blurs the whole point. */
  scale?: number;
  /** Derive the ink rim. Off for flat props that are already framed. */
  outline?: boolean;
  /** Class on the `<svg>`. */
  className?: string;
  /** Extra attributes, already safe (we author them). */
  attrs?: string;
  /** Stretch to the container's width instead of an integer multiple. Only for art with no text
   *  and no square features — a distant horizon, never a sprite. */
  fluid?: boolean;
}

interface Cells {
  w: number;
  h: number;
  at: (x: number, y: number) => string;
  set: (x: number, y: number, ch: string) => void;
}

function cells(grid: Grid, pad: number): Cells {
  const w = Math.max(0, ...grid.map((r) => r.length)) + pad * 2;
  const h = grid.length + pad * 2;
  const buf: string[] = new Array(w * h).fill(EMPTY);
  grid.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) buf[(y + pad) * w + (x + pad)] = row[x];
  });
  return {
    w,
    h,
    at: (x, y) => (x < 0 || y < 0 || x >= w || y >= h ? EMPTY : buf[y * w + x]),
    set: (x, y, ch) => {
      if (x >= 0 && y >= 0 && x < w && y < h) buf[y * w + x] = ch;
    },
  };
}

/** An empty cell orthogonally touching a solid one is rim. Diagonals are deliberately left out —
 *  including them fattens every corner and the sprite loses its silhouette. */
function outline(c: Cells): void {
  const rim: [number, number][] = [];
  for (let y = 0; y < c.h; y++) {
    for (let x = 0; x < c.w; x++) {
      if (c.at(x, y) !== EMPTY) continue;
      const touching =
        c.at(x - 1, y) !== EMPTY ||
        c.at(x + 1, y) !== EMPTY ||
        c.at(x, y - 1) !== EMPTY ||
        c.at(x, y + 1) !== EMPTY;
      if (touching) rim.push([x, y]);
    }
  }
  for (const [x, y] of rim) c.set(x, y, INK);
}

/** Horizontal run-length merge. Vertical merging would halve the node count again but costs a
 *  second pass and the rectangles stop matching how the art was authored, which makes a wrong
 *  pixel much harder to find. */
function rects(c: Cells, pal: Palette): string {
  const out: string[] = [];
  for (let y = 0; y < c.h; y++) {
    let x = 0;
    while (x < c.w) {
      const ch = c.at(x, y);
      let run = 1;
      while (x + run < c.w && c.at(x + run, y) === ch) run++;
      // The rim is derived, so its colour is too — a palette that never mentions ink still gets a
      // silhouette, and a piece that wants a different rim just declares one.
      const fill = ch === EMPTY ? null : (pal[ch] ?? (ch === INK ? "var(--wp-ink)" : null));
      if (fill) {
        out.push(
          `<rect x="${x}" y="${y}" width="${run}" height="1" fill="${fill}"/>`,
        );
      }
      x += run;
    }
  }
  return out.join("");
}

/** One grid as a standalone `<svg>`, sized to an exact integer multiple so edges stay hard. */
export function draw(grid: Grid, pal: Palette, opts: DrawOptions = {}): string {
  const { scale = 2, outline: rim = true, className = "", attrs = "", fluid = false } = opts;
  const c = cells(grid, rim ? 1 : 0);
  if (rim) outline(c);
  const body = rects(c, pal);
  const cls = className ? ` class="${className}"` : "";
  const size = fluid
    ? `width="100%" height="${c.h * scale}" preserveAspectRatio="none"`
    : `width="${c.w * scale}" height="${c.h * scale}"`;
  return (
    `<svg${cls} ${size} viewBox="0 0 ${c.w} ${c.h}" ` +
    `shape-rendering="crispEdges" aria-hidden="true" focusable="false"${attrs ? " " + attrs : ""}>` +
    `${body}</svg>`
  );
}

/** Two poses in ONE `<svg>`, stacked as groups the stylesheet flips between. A frame animation
 *  needs both frames present and identically placed; drawing them as separate elements is how the
 *  sprite ends up jittering by a pixel when one grid is a row taller than the other. */
export function drawFrames(
  frames: readonly Grid[],
  pal: Palette,
  opts: DrawOptions = {},
): string {
  const { scale = 2, outline: rim = true, className = "", attrs = "" } = opts;
  const built = frames.map((g) => {
    const c = cells(g, rim ? 1 : 0);
    if (rim) outline(c);
    return c;
  });
  const w = Math.max(...built.map((c) => c.w));
  const h = Math.max(...built.map((c) => c.h));
  const groups = built
    .map((c, i) => `<g class="wp-f wp-f${i}">${rects(c, pal)}</g>`)
    .join("");
  const cls = className ? ` class="${className}"` : "";
  return (
    `<svg${cls} width="${w * scale}" height="${h * scale}" viewBox="0 0 ${w} ${h}" ` +
    `shape-rendering="crispEdges" aria-hidden="true" focusable="false"${attrs ? " " + attrs : ""}>` +
    `${groups}</svg>`
  );
}

/** Rendered size of a grid, so layout can reserve room without measuring in the browser. */
export function sizeOf(grid: Grid, scale: number, rim = true): [number, number] {
  const pad = rim ? 2 : 0;
  return [(Math.max(0, ...grid.map((r) => r.length)) + pad) * scale, (grid.length + pad) * scale];
}
