/** LIGHT — the layer that turns a floor plan into a place somebody is standing in.
 *
 *  The version this replaces lit a room by filling its whole floor with ten percent of a hue. One
 *  flat wash, edge to edge, identical in every cell. That is not light: it is a tint, and a tint
 *  is exactly what a diagram uses to say "this region is category B". It is also why the LIGHT
 *  theme read as washed out while the dark one read as a room — dark got its depth for free from
 *  a near-black background the mixes fell toward, and light had nothing underneath to fall to, so
 *  every surface landed inside a twelve-point band and the walls came out BRIGHTER than the floor
 *  they are supposed to be occluding.
 *
 *  So the value range stops coming from the theme and starts coming from LIGHT AND SHADOW, which
 *  is where it comes from in every game that has ever looked like a place:
 *
 *   - a room is DARK by default and its lamps carve pools out of that dark. The pool is quantised
 *     to the TILE GRID and stepped in four levels — no smooth ramp anywhere, because a smooth
 *     radial gradient rasterises at screen resolution and is the one effect that instantly
 *     un-pixels a pixel scene. Banded light on the tile grid is the signature; it is also what
 *     an 8-bit renderer could actually do, which is why it reads as a game rather than as CSS.
 *   - every wall casts. One global light direction (from the north-west, the oldest convention in
 *     the medium) means every wall drops a hard band onto the floor south and east of it, and the
 *     room acquires a corner you can see.
 *   - every prop casts its own SILHOUETTE, not a blob: the same drawing re-rendered through an
 *     all-ink palette, offset. It costs one extra entry in the sheet per distinct prop and one
 *     `use` per placement.
 *
 *  And the pool is TINTED by what the room is doing. The rail says a run's state in a word and a
 *  colour from `statusLanguage`; the world says the same state by the colour of the light in the
 *  room, which is legible from across the map before a single label resolves. Same taxonomy, two
 *  idioms — which is the whole point of having a taxonomy.
 */
import type { Rect, Room, World } from "./world";

/** Cells per tile. The map's user units are cells; a tile is eight of them. */
const C = 8;

/** Where light comes from in a room. Radius is in TILES. */
export interface Lamp {
  x: number;
  y: number;
  r: number;
  /** A fixture on the ceiling washes the room; a desk lamp or a screen is a hot spot in it. */
  kind: "fixture" | "spot";
}

/** How many steps the pool is quantised into. Four is enough to read as falloff and few enough
 *  that each band is a big visible shape rather than a gradient in disguise. */
export const LEVELS = 4;

/** The band edges, as a fraction of the lamp's radius. Deliberately uneven: an even split makes
 *  the middle band dominate and the pool reads as a disc with a rim. */
const EDGE = [0.3, 0.55, 0.78, 1];

/** The light in a room, as tile runs per level.
 *
 *  Index 0 is the brightest band; the LAST entry is everything no lamp reaches. The unlit set is
 *  returned rather than left implicit because the shade has to be painted only where the light is
 *  NOT: a dark wash under the pools would have to be lightened back by them, and two translucent
 *  fills stacked is a gradient, which is the one thing this layer exists not to be.
 */
export function poolRuns(room: Room, lamps: readonly Lamp[], stride: number): Rect[][] {
  const floor = new Set<number>();
  for (const r of room.floorRuns) {
    for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) floor.add(y * stride + x);
  }
  const level = new Map<number, number>();
  for (const key of floor) {
    const x = key % stride;
    const y = (key - x) / stride;
    let best = LEVELS;
    for (const l of lamps) {
      // Measured from the CENTRE of both tiles, so a lamp lights its own tile brightest rather
      // than lighting the corner it happens to sit on.
      const d = Math.hypot(x - l.x, (y - l.y) * 1.15) / Math.max(0.5, l.r);
      let band = LEVELS;
      for (let i = 0; i < EDGE.length; i++) {
        if (d <= EDGE[i]) {
          band = i;
          break;
        }
      }
      // A spot is a hot centre: it never contributes the outermost, flattest band, so a desk lamp
      // reads as a small bright thing rather than as a second wash over the whole room.
      if (l.kind === "spot" && band >= LEVELS - 1) band = LEVELS;
      if (band < best) best = band;
    }
    if (best < LEVELS) level.set(key, best);
  }
  const out: Rect[][] = [];
  for (let i = 0; i <= LEVELS; i++) {
    const cells = new Set<number>();
    if (i === LEVELS) for (const key of floor) { if (!level.has(key)) cells.add(key); }
    else for (const [key, v] of level) if (v === i) cells.add(key);
    out.push(runsOf(cells, room, stride));
  }
  return out;
}

/** Where a room's light actually hangs.
 *
 *  A fixture per rectangle of the footprint — so an L gets two, and the alcove is not a black
 *  hole behind a lit room — plus a hot spot on every prop that emits: a screen, a desk lamp, a
 *  kettle's ring. Nothing is placed by hand; a room furnished differently lights differently,
 *  which is the same rule the furniture already follows.
 */
export function lampsFor(room: Room): Lamp[] {
  const out: Lamp[] = [];
  for (const r of room.rects) {
    // A ROW of fixtures on a regular pitch, which is what a ceiling actually has — and the reason
    // it matters is that ONE lamp per room produces a single vignette that reads as a tint again.
    // Several overlapping pools scallop, and the scallop is the thing the eye reads as light.
    const pitch = 5;
    const nx = Math.max(1, Math.round(r.w / pitch));
    const ny = Math.max(1, Math.round(r.h / pitch));
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        out.push({
          x: r.x + ((i + 0.5) * r.w) / nx - 0.5,
          y: r.y + ((j + 0.5) * r.h) / ny - 0.5,
          r: Math.max(2.6, Math.min(4.4, (Math.min(r.w / nx, r.h / ny) * 0.86))),
          kind: "fixture",
        });
      }
    }
  }
  for (const p of room.props) {
    if (p.live === "screen") out.push({ x: p.x, y: p.y + 0.4, r: 2.1, kind: "spot" });
    else if (p.live === "lamp") out.push({ x: p.x, y: p.y + 0.8, r: 2.8, kind: "spot" });
    else if (p.live === "steam") out.push({ x: p.x, y: p.y + 0.5, r: 1.7, kind: "spot" });
  }
  return out;
}

/** Horizontal runs of a cell set inside a room's bounding box. Same merge the map already does
 *  for tiles: one rectangle per run, so a lit room costs tens of nodes rather than hundreds. */
function runsOf(cells: Set<number>, box: Rect, stride: number): Rect[] {
  const out: Rect[] = [];
  for (let y = box.y; y < box.y + box.h; y++) {
    let x = box.x;
    while (x < box.x + box.w) {
      if (!cells.has(y * stride + x)) {
        x++;
        continue;
      }
      let run = 1;
      while (cells.has(y * stride + x + run)) run++;
      out.push({ x, y, w: run, h: 1 });
      x += run;
    }
  }
  return out;
}

/** The path for a set of tile runs, in cell units. */
export function runPath(runs: readonly Rect[]): string {
  return runs.map((r) => `M${r.x * C} ${r.y * C}h${r.w * C}v${r.h * C}h-${r.w * C}z`).join("");
}

/** How deep a wall's shadow falls onto the floor beside it, in CELLS out of eight. Three is a
 *  visible band at every zoom this view uses and still leaves five clear cells of floor. */
const DROP = 3;

/** Every wall in the building, casting.
 *
 *  ONE direction for the whole world — light from the north-west — so the shadows agree with each
 *  other and with the offset every prop and every person is drawn with. A per-room light
 *  direction would be more correct and would read as noise.
 *
 *  Built from `world.solid`, which already knows every cell a body may not walk into, so this
 *  picks up the building's structural mass and the party walls between two rooms for free rather
 *  than needing a second description of the same geometry.
 */
export function wallShadow(world: World): string {
  const solid = world.solid;
  const at = (x: number, y: number): boolean =>
    x >= 0 && y >= 0 && x < world.cols && y < world.rows && !!solid[y * world.cols + x];
  let d = "";
  for (let y = 0; y < world.rows; y++) {
    for (let x = 0; x < world.cols; x++) {
      if (at(x, y)) continue;
      const north = at(x, y - 1);
      const west = at(x - 1, y);
      const nw = at(x - 1, y - 1);
      const X = x * C;
      const Y = y * C;
      // The band under a wall runs the full tile; the band beside one runs the full tile; where
      // both meet, the corner is already covered by the two overlapping bands.
      if (north) d += `M${X} ${Y}h${C}v${DROP}h-${C}z`;
      if (west) d += `M${X} ${Y + (north ? DROP : 0)}v${C - (north ? DROP : 0)}h${DROP}v-${C - (north ? DROP : 0)}z`;
      // An inside corner with nothing orthogonally solid still catches the diagonal.
      else if (nw && !north) d += `M${X} ${Y}h${DROP}v${DROP}h-${DROP}z`;
    }
  }
  return d;
}

/** The palette a shadow is drawn with: the same grid, every colour replaced by one ink.
 *
 *  Re-drawing through the sheet rather than blurring or filtering keeps the shadow a PIXEL shape —
 *  it is the prop's own silhouette, one flat tone, offset. A CSS filter would have produced the
 *  same picture at a per-element compositing cost and, worse, would have been a smooth alpha ramp
 *  around the edges of an otherwise hard-edged scene.
 */
export function inkPalette(pal: Readonly<Record<string, string>>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const k of Object.keys(pal)) out[k] = "var(--wp-drop)";
  return out;
}

/** How far a standing thing's shadow is thrown, in cells. Matches the wall band's direction. */
export const CAST = { dx: 2, dy: 2 };

/** THE SHADOW IS PROJECTED ONTO THE GROUND, IN FRONT OF THE THING THAT CASTS IT.
 *
 *  Third report of "floating trees", and the two earlier fixes were each half of the answer. The
 *  first replaced a TRANSLATED copy with a real projection (a copy of a canopy moved two cells
 *  down is a dark canopy hanging in the air beside a green one). The second stepped the whole
 *  thing off the object's own foot, so a pine's skirt stopped swallowing its own shade. Both were
 *  right. Both left the third defect untouched, and it is the one that mattered:
 *
 *      THE PROJECTION RAN NORTH — TOWARD THE SUN.
 *
 *  `wallShadow` above drops its band SOUTH and EAST of every wall, `CAST` is `+2,+2`, the
 *  character's contact patch is thrown down and right, and this file's own header says the light
 *  comes from the north-west. This function disagreed with all four: a pixel `h` cells above the
 *  base landed `h * SQUASH` cells UP the screen, so the far end of a tree's shadow — the canopy,
 *  the biggest part — came to rest BEHIND the trunk, hidden by the very silhouette that cast it.
 *  What escaped was a thin bar level with the trunk, sticking out to the right, and nothing at all
 *  on the open ground in front. A tree with clear grass under its foot and a dark dash beside its
 *  waist is a tree standing on nothing. That is what he kept seeing, in both themes, at every
 *  zoom, on every tall thing in the picture.
 *
 *  It was invisible to the two rounds that came before because the compression hid it: at eight
 *  rows the whole shadow was three cells deep, so it never got far enough north to look wrong on
 *  its own — it just sat under the object like a stain, and every check asked "does it touch?"
 *  rather than "which way does it go?".
 *
 *  So the model is stated once, positively, and checked mechanically (`dev/shadows.ts`):
 *
 *    - the sun is in the NORTH-WEST for everything in this world;
 *    - a pixel `h` cells above the base is thrown `h * SHEAR` east and `h * SQUASH` SOUTH;
 *    - the base is the art's OWN lowest pixel, never the tile's bottom row, so a prop drawn short
 *      of its cell (a chair, a crate, a sofa — sixteen of the fifty-two are) has its shadow at its
 *      feet instead of a cell and a half below them;
 *    - one cell down and one cell right of that base before anything else, so a thing that is
 *      widest at the ground still shows its own shade.
 *
 *  Done to the GRID rather than with a transform, because a CSS skew would resample every hard
 *  edge in a scene whose whole substrate is hard edges.
 */
/* Tuned on the rendered grounds, not on paper. At 0.62 the shadow of an eight-row tree reaches
   four cells and lands as a black BAR beside it — the projection is right and the length is a
   lie, because the same ink now covers three times the area the translated copy did. Shorter,
   and the outdoor group dims its own ink further (a lawn in daylight is not a room). */
const SHEAR = 0.45;
const SQUASH = 0.34;
/* AND THE WHOLE SHADOW STEPS OFF THE OBJECT'S OWN FOOT.
   Shear alone moves a pixel by how far it is ABOVE the base, so a pixel standing ON the base does
   not move at all — which is exactly right for the contact point and exactly wrong for anything
   whose widest part is DOWN THERE. A conifer's skirt and a shrub are widest at their feet, so the
   entire projection landed underneath the canopy that cast it and both read, again, as having no
   ground contact. One cell down and one cell right of the base puts the shadow out from under
   every silhouette regardless of its shape, and it is where a sun in the north-west puts it. */
const FOOT_X = 1;
const FOOT_Y = 1;

/** How far a full-height tile's shadow actually reaches, in CELLS, east and south.
 *
 *  Exported because the site plans around it: nothing tall may stand where its shade would land
 *  on the water, and a hand-kept number for that is a hand-kept copy of this projection. The last
 *  one said five cells EAST while the projection reached four east and none south, and it went on
 *  saying it after the throw direction changed — a keep-back that is a constant rather than a
 *  consequence is how a tree ends up laying a slab across the pond again.
 *
 *  A tile is `TILE_CELLS` tall, so the worst case is a prop drawn to the top of its cell. Reported
 *  in TILES, which is what a planner works in, rounded up. */
export function shadowReach(cells: number): { east: number; south: number } {
  const high = cells - 1;
  return {
    east: Math.ceil((FOOT_X + Math.round(high * SHEAR)) / cells),
    south: Math.ceil((FOOT_Y + Math.round(high * SQUASH)) / cells),
  };
}

/** The art's own lowest pixel: where the thing actually meets the ground.
 *
 *  Sixteen of the fifty-two drawn props stop a row or more short of their cell — a chair, a sofa,
 *  a crate, a printer, the door leaf. Measuring height and contact from `grid.length - 1` puts
 *  their shadow that far below their feet, which is a gap, which is the whole complaint. Returns
 *  -1 for a grid with nothing in it. */
export function footRow(grid: readonly string[]): number {
  for (let r = grid.length - 1; r >= 0; r--) {
    const row = grid[r];
    for (let c = 0; c < row.length; c++) if (row[c] !== "." && row[c] !== " ") return r;
  }
  return -1;
}

export function project(grid: readonly string[], leafy = false): string[] {
  const rows = grid.length;
  if (!rows) return [];
  const base = footRow(grid);
  if (base < 0) return [];
  const cols = Math.max(...grid.map((r) => r.length));
  const reach = Math.round(base * SHEAR) + FOOT_X;
  const tall = base + FOOT_Y + Math.round(base * SQUASH) + 1;
  const out: string[][] = Array.from({ length: tall }, () => new Array(cols + reach).fill("."));
  for (let r = 0; r <= base; r++) {
    const row = grid[r];
    const high = base - r;
    const dx = FOOT_X + Math.round(high * SHEAR);
    // SOUTH, away from the light. The far end of a tall thing's shadow is the end nearest the
    // viewer — that is what makes the ground in front of it read as ground it is standing on.
    const y = base + FOOT_Y + Math.round(high * SQUASH);
    if (y < 0 || y >= tall) continue;
    for (let c = 0; c < row.length; c++) {
      if (row[c] === "." || row[c] === " ") continue;
      const x = c + dx;
      /* DAPPLE, past the contact. The two cells nearest the foot stay solid — that is the part
         that says the thing is standing ON something — and everything the canopy throws beyond
         them is a checkerboard, which is what leaf shade looks like and, more to the point, what
         stops two neighbouring trees' shadows from merging into one continuous bar. In a scene
         made of hard pixels a dither IS the soft edge; a blur would not be. */
      if (leafy && dx > FOOT_X + 1 && (x + y) % 2 === 1) continue;
      out[y][x] = "#";
    }
  }
  return out.map((r) => r.join(""));
}
