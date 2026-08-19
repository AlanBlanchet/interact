/** The SUBSTRATE: square tiles, authored the same way every other piece of art here is.
 *
 *  The view this replaces drew rooms as flexbox boxes with one prop centred in each and a sprite
 *  laid out by the document's own flow. That is a diagram of a workplace: a character could never
 *  be anywhere except where the layout engine put it, so it could never WALK anywhere, and the
 *  only motion the whole surface could express was a few pixels of transform around a fixed slot.
 *
 *  So the floor is now a real GRID. Every tile is an 8x8 pixel drawing, drawn once into the
 *  document's sheet and referenced per cell, and a tile is either walkable or it is not — which is
 *  what lets a body have a position of its own, a route across the building, and somewhere to go.
 *
 *  Eight by eight, rendered at scale 3, gives a 24px tile: exactly the width of a worker sprite at
 *  scale 2. A character being one tile wide and a tile and a half tall is the proportion every
 *  side-on tile game settles on, and it is the reason the people still read as people at this
 *  size rather than becoming counters on a board.
 */
import type { Grid, Palette } from "./pixels";

/** One authored tile: the 8x8 art, and whether a body may stand on it. */
export interface Tile {
  grid: Grid;
  pal: Palette;
  /** Solid tiles block movement. The pathfinder reads this and nothing else. */
  solid?: boolean;
  /** Drawn with a derived ink rim. Off for anything that tessellates — a rim on a floor tile
   *  paints a grid of black lines across the whole building. */
  rim?: boolean;
}

/** Every colour a tile may use. Named against the room rather than against the theme, so a light
 *  and a dark building are the same drawings with a different set of these. */
const T: Palette = {
  f: "var(--t-floor)",
  g: "var(--t-grout)",
  h: "var(--t-floor-hi)",
  c: "var(--t-carpet)",
  d: "var(--t-carpet-hi)",
  w: "var(--t-wall)",
  p: "var(--t-wall-cap)",
  k: "var(--t-wall-foot)",
  m: "var(--t-mat)",
  o: "var(--t-wood)",
  n: "var(--t-wood-hi)",
  e: "var(--t-metal)",
  l: "var(--t-lit)",
  a: "var(--t-glass)",
  v: "var(--t-ground)",
  V: "var(--t-ground-hi)",
  L: "var(--t-leaf)",
  P: "var(--t-path)",
  Q: "var(--t-path-hi)",
  u: "var(--t-fabric)",
  b: "var(--t-book)",
  y: "var(--t-book2)",
  x: "var(--t-ink)",
  s: "var(--accent, var(--t-lit))",
  A: "var(--t-dais)",
  B: "var(--t-dais-hi)",
};

const tile = (grid: Grid, extra: Partial<Tile> = {}): Tile => ({ grid, pal: T, rim: false, ...extra });

/* ── ground ──────────────────────────────────────────────────────────────────────────────────
   The seam lives on the TOP and LEFT edge of every tile, never on all four: drawn on all four the
   grout doubles up between neighbours and the floor reads as a wire mesh rather than as tiling. */

export const FLOOR = tile([
  "gggggggg",
  "gfffffff",
  "gfffffff",
  "gfffhfff",
  "gfffffff",
  "gfffffff",
  "gfhfffff",
  "gfffffff",
]);

/** A room's own floor: warmer, and woven rather than seamed, so crossing a threshold is visible
 *  as a change of ground the way it is in a building. */
export const CARPET = tile([
  "cccccccc",
  "ccdccccc",
  "cccccccc",
  "cccccdcc",
  "cccccccc",
  "cdcccccc",
  "cccccccc",
  "ccccdccc",
]);

/** Under the brain. A ring of the team's own accent, so the middle of the building is the one
 *  place the floor itself is coloured. */
export const DAIS = tile([
  "AAAAAAAA",
  "AAAAAAAA",
  "AABAAAAA",
  "AAAAAAAA",
  "AAAAAAAA",
  "AAAAABAA",
  "AAAAAAAA",
  "AAAAAAAA",
]);

/* ── walls ───────────────────────────────────────────────────────────────────────────────────
   Seen from the same three-quarter angle the whole building is: a lit cap on top, the body of the
   wall below it, and a hard shadow line where it meets the floor. One tile serves every run —
   a wall drawn as a slab in plan is what makes the rooms read as rooms rather than as borders. */

export const WALL = tile(
  [
    "pppppppp",
    "pppppppp",
    "wwwwwwww",
    "wwwwwwww",
    "wwwwwwww",
    "wwwwwwww",
    "wwwwwwww",
    "kkkkkkkk",
  ],
  { solid: true },
);

/** A window in the wall run. Same slab, punched through to the daylight outside — the one thing
 *  that stops a long wall being a long rectangle. */
export const WINDOW = tile(
  [
    "pppppppp",
    "pppppppp",
    "waaaaaaw",
    "walaaalw",
    "waaaaaaw",
    "walaaalw",
    "wwwwwwww",
    "kkkkkkkk",
  ],
  { solid: true },
);

/* ── doors ───────────────────────────────────────────────────────────────────────────────────
   A gap in a wall run, with the jambs left standing. Two of them, because a doorway in a wall
   that runs left-to-right is a passage that runs up-and-down, and the jambs have to be on the
   other pair of sides. Both are WALKABLE: the door is the only way in, and pathing through it is
   the whole reason the rooms are separate. */

export const DOOR_H = tile([
  "wwffffww",
  "wwffffww",
  "wwmmmmww",
  "wwmmmmww",
  "wwmmmmww",
  "wwmmmmww",
  "wwffffww",
  "wwffffww",
]);

export const DOOR_V = tile([
  "wwwwwwww",
  "wwwwwwww",
  "ffffffff",
  "mmmmmmmm",
  "mmmmmmmm",
  "ffffffff",
  "wwwwwwww",
  "wwwwwwww",
]);

/* ── the furniture, one tile each ────────────────────────────────────────────────────────────
   Every one is SOLID, so a body walks around it rather than through it. That is the cheapest
   possible way to make a room feel like a room: the moment a route has to bend around a desk,
   the floor stops being a backdrop and becomes a place with things in it. */

export const DESK = tile(
  [
    "........",
    "..eeee..",
    "..elle..",
    "..eeee..",
    "..o..o..",
    "oooooooo",
    "onnnnnno",
    "o......o",
  ],
  { solid: true },
);

export const SHELF = tile(
  [
    "oooooooo",
    "obybybyo",
    "obybybyo",
    "oooooooo",
    "oybybybo",
    "oybybybo",
    "oooooooo",
    "o......o",
  ],
  { solid: true },
);

export const RACK = tile(
  [
    "eeeeeeee",
    "elllllle",
    "eeeeeeee",
    "elllllle",
    "eeeeeeee",
    "elllllle",
    "eeeeeeee",
    "e......e",
  ],
  { solid: true },
);

export const PLANT = tile(
  [
    "...LL...",
    "..LLLL..",
    ".LLLLLL.",
    "LLLLLLLL",
    "..LLLL..",
    "...oo...",
    "..oooo..",
    "..onno..",
  ],
  { solid: true },
);

export const SOFA = tile(
  [
    "........",
    "..uuuu..",
    ".uuuuuu.",
    "uuuuuuuu",
    "uuuuuuuu",
    "u.uuuu.u",
    "u......u",
    "........",
  ],
  { solid: true },
);

export const BOARD = tile(
  [
    "xxxxxxxx",
    "xaaaaaax",
    "xasaaaax",
    "xaaassax",
    "xaaaaaax",
    "xxxxxxxx",
    "...xx...",
    "..x..x..",
  ],
  { solid: true },
);

export const BENCH = tile(
  [
    "........",
    "..a..a..",
    "..a..a..",
    ".aaa.aa.",
    "oooooooo",
    "onnnnnno",
    "o......o",
    "o......o",
  ],
  { solid: true },
);

export const URN = tile(
  [
    "........",
    "..eeee..",
    "..elle..",
    "..eeee..",
    "..eeee..",
    "..o..o..",
    ".oooooo.",
    ".onnnno.",
  ],
  { solid: true },
);

/** The brain's own console. The only tile in the building that is drawn in the team's accent, and
 *  the one thing on the map that is unmistakably the middle of it. */
export const CORE = tile(
  [
    "..ssss..",
    ".seeees.",
    "sel..les",
    "se.ll.es",
    "se.ll.es",
    "sel..les",
    ".seeees.",
    "..ssss..",
  ],
  { solid: true },
);

/* ── outside ─────────────────────────────────────────────────────────────────────────────────
   The web is genuinely outdoors, reached through the front door, so it needs ground of its own
   that is not the building's floor. */

export const GRASS = tile([
  "vvvvvvvv",
  "vvvvvvvv",
  "vvvvvvvv",
  "vvvVvvvv",
  "vvvvvvvv",
  "vvvvvvvv",
  "vvvvvvVv",
  "vvvvvvvv",
]);

export const PATH = tile([
  "PPPPPPPP",
  "PPPPQPPP",
  "PPPPPPPP",
  "PQPPPPPP",
  "PPPPPPPP",
  "PPPPPPQP",
  "PPPPPPPP",
  "PQPPPPPP",
]);

export const MAST = tile(
  [
    "...ee...",
    "..eeee..",
    ".e.ee.e.",
    "e..ee..e",
    "...ee...",
    "...ee...",
    "...ee...",
    "..oooo..",
  ],
  { solid: true },
);

/** Everything a room plan may name, so the plan is DATA and this file is the only place a tile
 *  exists. A new domain room costs a row in `world.ts`, never a drawing here. */
export const TILES = {
  floor: FLOOR,
  carpet: CARPET,
  dais: DAIS,
  wall: WALL,
  window: WINDOW,
  doorH: DOOR_H,
  doorV: DOOR_V,
  desk: DESK,
  shelf: SHELF,
  rack: RACK,
  plant: PLANT,
  sofa: SOFA,
  board: BOARD,
  bench: BENCH,
  urn: URN,
  core: CORE,
  grass: GRASS,
  path: PATH,
  mast: MAST,
} as const;

export type TileId = keyof typeof TILES;

/** How big a tile is drawn, and the sprite scale that matches it. Stated once here because the
 *  stylesheet, the renderer and the simulation all have to agree on it to the pixel — a body's
 *  position is in tiles and its element is placed in CSS pixels. */
export const TILE_PX = 24;
export const TILE_CELLS = 8;
export const TILE_SCALE = TILE_PX / TILE_CELLS;
