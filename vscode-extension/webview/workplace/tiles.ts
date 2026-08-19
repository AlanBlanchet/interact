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
  r: "var(--t-runner)",
  R: "var(--t-runner-hi)",
  F: "var(--t-face)",
  S: "var(--t-skirt)",
  G: "var(--t-screen)",
  i: "var(--t-warm)",
  z: "var(--t-shade)",
  H: "var(--t-hall)",
  J: "var(--t-hall-band)",
  K: "var(--t-mass)",
  U: "var(--t-rug)",
  Z: "var(--t-rug-hi)",
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
/* ── the corridor ────────────────────────────────────────────────────────────────────────────
   A corridor is not "the room floor, outside a room". It has its own ground, banded ACROSS the
   direction of travel so the eye runs along it, and a carpet runner down the middle. The moment a
   passage looks different from the places it joins, the plan stops being a partition of one
   surface and becomes a building you could walk through. */

export const LINO = tile([
  "JJJJJJJJ",
  "HHHHHHHH",
  "HHHHHHHH",
  "HHHHHHHH",
  "JJJJJJJJ",
  "HHHHHHHH",
  "HHHHHHHH",
  "HHHHHHHH",
]);

/** The building's own mass: everything inside the envelope that is neither a room nor a passage.
 *  Drawn DARKER than any floor and hatched, so the plan reads as spaces carved out of a solid
 *  block rather than as rectangles drawn on a sheet. Without it a shallow room leaves a hole the
 *  same colour as the corridor and the whole thing goes back to being a diagram. */
export const MASS = tile(
  [
    "KKKKKKKK",
    "KKKKKKKK",
    "KKwKKKKK",
    "KKKKKKKK",
    "KKKKKKKK",
    "KKKKKKwK",
    "KKKKKKKK",
    "KKKKKKKK",
  ],
  { solid: true },
);

/** A rug. Not furniture: a change of GROUND in the middle of a room, which is what a real room
 *  uses to stop being a rectangle of one colour and what stops a floor plan's interior reading as
 *  waiting space. It blocks nothing, so it costs no route. */
export const RUG = tile([
  "UUUUUUUU",
  "UUUZUUUU",
  "UUUUUUUU",
  "ZUUUUUUZ",
  "UUUUUUUU",
  "UUUUZUUU",
  "UUUUUUUU",
  "ZUUUUUUZ",
]);

/** The runner down the centre of the hall, in the house colour. One strip, laid along the spine,
 *  which is the cheapest possible way to say "this way to the front door". */
export const RUNNER = tile([
  "RRRRRRRR",
  "rrrrrrrr",
  "rRrrrrRr",
  "rrrrrrrr",
  "rrRrrrrr",
  "rrrrrrrr",
  "rrrrrRrr",
  "RRRRRRRR",
]);

/* ── the wall you can SEE ────────────────────────────────────────────────────────────────────
   The defect that made this read as a floor plan was that all four of a room's walls were the
   same one-tile band: a rectangle drawn in a darker colour is a border, not a wall. So the wall a
   room faces — its back one — is now TWO tiles: the cap you look down on, and beneath it the FACE
   you look at, with a skirting board where it meets the floor. Everything a real room hangs on a
   wall hangs here, and the room stops being a rectangle the instant it does. */

export const FACE = tile(
  [
    "FFFFFFFF",
    "FFFFFFFF",
    "FFFFFFFF",
    "FFFFFFFF",
    "FFFFFFFF",
    "SSSSSSSS",
    "SSSSSSSS",
    "kkkkkkkk",
  ],
  { solid: true },
);

const faceProp = (rows: string[]): Tile =>
  tile([...rows, "SSSSSSSS", "kkkkkkkk"], { solid: true });

/** Daylight. The one thing that tells you which wall is the outside one. */
export const WIN_FACE = faceProp([
  "FFFFFFFF",
  "FeeeeeeF",
  "FeaaaaeF",
  "FealaaeF",
  "FeaaaaeF",
  "FeeeeeeF",
]);

/** A whiteboard somebody has actually written on. */
export const WHITEBOARD = faceProp([
  "FFFFFFFF",
  "FeeeeeeF",
  "FeaaaaeF",
  "FexxaaeF",
  "FeaxxaeF",
  "FeeeeeeF",
]);

export const CLOCK = faceProp([
  "FFFFFFFF",
  "FFxxxxFF",
  "FxaaaaxF",
  "FxaxaaxF",
  "FxaxxaxF",
  "FFxxxxFF",
]);

export const PINBOARD = faceProp([
  "FFFFFFFF",
  "FooooooF",
  "FoyybbyF",
  "FoyybbyF",
  "FobbyybF",
  "FooooooF",
]);

export const PIPES = faceProp([
  "FFFFFFFF",
  "FeeeeeeF",
  "FFFFFFFF",
  "FeeeeeeF",
  "FFFFFFFF",
  "FFFFFFFF",
]);

export const VENT = faceProp([
  "FFFFFFFF",
  "FeeeeeeF",
  "FeFFFFeF",
  "FeeeeeeF",
  "FeFFFFeF",
  "FeeeeeeF",
]);

/** A bank of screens, mounted. The room that WATCHES things has a wall of them. */
export const SCREEN_WALL = faceProp([
  "FFFFFFFF",
  "FxxxxxxF",
  "FxGGGGxF",
  "FxGGGGxF",
  "FxxxxxxF",
  "FFFFFFFF",
]);

export const POSTER = faceProp([
  "FFFFFFFF",
  "FxxxxxxF",
  "FxssssxF",
  "FxsaasxF",
  "FxssssxF",
  "FxxxxxxF",
]);

export const LAMP = faceProp([
  "FFFFFFFF",
  "FFFeeFFF",
  "FFeiieFF",
  "FeiiiieF",
  "FiiiiiiF",
  "FFFFFFFF",
]);

/* ── doorways with DEPTH ─────────────────────────────────────────────────────────────────────
   A door in a two-tile wall is two tiles: the opening seen from above, and the frame you walk
   through. Walking a body through those two cells is visibly passing through a wall rather than
   crossing a coloured line, and it costs nothing but the second tile. */

export const DOOR_CAP = tile([
  "pppppppp",
  "pppppppp",
  "zzzzzzzz",
  "zzzzzzzz",
  "zzzzzzzz",
  "zzzzzzzz",
  "zzzzzzzz",
  "zzzzzzzz",
]);

export const DOOR_WAY = tile([
  "eFFFFFFe",
  "e......e",
  "e......e",
  "e......e",
  "e......e",
  "e......e",
  "e......e",
  "ekkkkkke",
]);

/** The leaf itself, hinged on its left edge. Swung open by the engine when somebody is close, so
 *  a door is something that HAPPENS rather than a hole that was always there. */
export const DOOR_LEAF = tile([
  "oooooo..",
  "onnnno..",
  "onnnno..",
  "onneno..",
  "onnnno..",
  "onnnno..",
  "oooooo..",
  "........",
]);

export const MATT = tile([
  "........",
  ".mmmmmm.",
  ".mmmmmm.",
  ".mmmmmm.",
  ".mmmmmm.",
  ".mmmmmm.",
  ".mmmmmm.",
  "........",
]);

/* ── what a department DOES, as furniture ────────────────────────────────────────────────────
   Every one of these belongs to an archetype in world.ts, and the archetype is chosen from the
   faculties the department's own people actually declare. A room full of people who run commands
   is a machine room; a room full of people who only read is the stacks. Nothing is hard-coded to
   a department name, and no two rooms are furnished from the same list. */

export const STACKS = tile(
  [
    "oooooooo",
    "obbyybbo",
    "obbyybbo",
    "oooooooo",
    "oyybbyyo",
    "oyybbyyo",
    "oooooooo",
    "o......o",
  ],
  { solid: true },
);

export const SCREEN = tile(
  [
    "........",
    ".eeeeee.",
    ".eGGGGe.",
    ".eGGGGe.",
    ".eeeeee.",
    "...ee...",
    "..oooo..",
    "........",
  ],
  { solid: true },
);

export const DISH = tile(
  [
    "..eeee..",
    ".e....e.",
    "e..ee..e",
    "e.eeee.e",
    "e..ee..e",
    ".e.ee.e.",
    "...ee...",
    "..oooo..",
  ],
  { solid: true },
);

export const TABLE_L = tile(
  [
    "........",
    "...ooooo",
    "..onnnnn",
    "..onnnnn",
    "..onnnnn",
    "...ooooo",
    "...o....",
    "...o....",
  ],
  { solid: true },
);

export const TABLE_M = tile(
  [
    "........",
    "oooooooo",
    "nnnnnnnn",
    "nnnnnnnn",
    "nnnnnnnn",
    "oooooooo",
    "........",
    "........",
  ],
  { solid: true },
);

export const TABLE_R = tile(
  [
    "........",
    "ooooo...",
    "nnnnno..",
    "nnnnno..",
    "nnnnno..",
    "ooooo...",
    "....o...",
    "....o...",
  ],
  { solid: true },
);

export const CHAIR = tile(
  [
    "........",
    "..uuuu..",
    "..uuuu..",
    ".uuuuuu.",
    ".uuuuuu.",
    "..o..o..",
    "..o..o..",
    "........",
  ],
  { solid: true },
);

export const COFFEE = tile(
  [
    "..eeee..",
    ".eeeeee.",
    ".ellale.",
    ".eeeeee.",
    ".e.aa.e.",
    ".eeeeee.",
    ".oooooo.",
    "........",
  ],
  { solid: true },
);

export const COOLER = tile(
  [
    "..aaaa..",
    ".aaaaaa.",
    ".aaaaaa.",
    "..eeee..",
    "..eeee..",
    "..e..e..",
    ".oooooo.",
    "........",
  ],
  { solid: true },
);

export const PRINTER = tile(
  [
    "........",
    ".eeeeee.",
    ".eaaaae.",
    ".eeeeee.",
    ".e....e.",
    ".eeeeee.",
    ".oooooo.",
    "........",
  ],
  { solid: true },
);

export const CRATES = tile(
  [
    "........",
    "..oooo..",
    "..onno..",
    "..oooo..",
    ".oooooo.",
    ".onnnno.",
    ".oooooo.",
    "........",
  ],
  { solid: true },
);

export const TANK = tile(
  [
    "eeeeeeee",
    "eaaaaaae",
    "easaaaae",
    "eaaaasae",
    "easaaaae",
    "eaaaaaae",
    "eeeeeeee",
    "o......o",
  ],
  { solid: true },
);

export const VENDING = tile(
  [
    "eeeeeeee",
    "eaaaaeee",
    "eabbaeee",
    "eayybeee",
    "eabbaeee",
    "eaaaaeee",
    "eeeeeeee",
    "e......e",
  ],
  { solid: true },
);

export const CABINET = tile(
  [
    "oooooooo",
    "onnnnnno",
    "o..ee..o",
    "onnnnnno",
    "o..ee..o",
    "onnnnnno",
    "o..ee..o",
    "o......o",
  ],
  { solid: true },
);

export const DRAFTING = tile(
  [
    "........",
    "...ooooo",
    "..onnnnn",
    ".onnnnnn",
    ".ooooooo",
    "..o...o.",
    "..o...o.",
    "........",
  ],
  { solid: true },
);

export const GLOBE = tile(
  [
    "..LLLL..",
    ".LvvvvL.",
    "LvLvvLvL",
    "LvvLLvvL",
    "LvvLLvvL",
    "LvLvvLvL",
    ".LvvvvL.",
    "..oooo..",
  ],
  { solid: true },
);

export const LADDER = tile(
  [
    "..o..o..",
    "..oooo..",
    "..o..o..",
    "..oooo..",
    "..o..o..",
    "..oooo..",
    "..o..o..",
    "........",
  ],
  { solid: true },
);

/** A column, not a wall. The chamber at the head of the building is held up rather than closed
 *  in, which is what makes it read as the one place in the plan that is not a room. */
export const PILLAR = tile(
  [
    "..pppp..",
    "..wwww..",
    "..wwww..",
    "..wwww..",
    "..wwww..",
    "..wwww..",
    ".pppppp.",
    ".kkkkkk.",
  ],
  { solid: true },
);

/* ── things that MOVE ────────────────────────────────────────────────────────────────────────
   Overlays, never part of the prop underneath: a separate node is what lets the stylesheet drive
   one at a tempo of its own without touching the drawing it sits on. All of them are drawn on
   cells that are already solid, so none of them costs a route. */

export const SCREEN_GLOW = tile([
  "........",
  "..GGGG..",
  "..GGGG..",
  "..GGGG..",
  "........",
  "........",
  "........",
  "........",
]);

export const WALL_GLOW = tile([
  "........",
  ".GGGGGG.",
  ".GGGGGG.",
  ".GGGGGG.",
  "........",
  "........",
  "........",
  "........",
]);

export const STEAM = tile([
  "...a....",
  "..a.a...",
  "...a....",
  "..a.....",
  "...a....",
  "........",
  "........",
  "........",
]);

export const FAN = tile([
  "........",
  "...ee...",
  ".eeeeee.",
  "..eeee..",
  "..eeee..",
  ".eeeeee.",
  "...ee...",
  "........",
]);

export const LAMP_POOL = tile([
  "........",
  "..iiii..",
  ".iiiiii.",
  ".iiiiii.",
  ".iiiiii.",
  "..iiii..",
  "........",
  "........",
]);

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
  lino: LINO,
  mass: MASS,
  rug: RUG,
  runner: RUNNER,
  face: FACE,
  winFace: WIN_FACE,
  whiteboard: WHITEBOARD,
  clock: CLOCK,
  pinboard: PINBOARD,
  pipes: PIPES,
  vent: VENT,
  screenWall: SCREEN_WALL,
  poster: POSTER,
  lamp: LAMP,
  doorCap: DOOR_CAP,
  doorWay: DOOR_WAY,
  doorLeaf: DOOR_LEAF,
  matt: MATT,
  stacks: STACKS,
  screen: SCREEN,
  dish: DISH,
  tableL: TABLE_L,
  tableM: TABLE_M,
  tableR: TABLE_R,
  chair: CHAIR,
  coffee: COFFEE,
  cooler: COOLER,
  printer: PRINTER,
  crates: CRATES,
  tank: TANK,
  vending: VENDING,
  cabinet: CABINET,
  drafting: DRAFTING,
  globe: GLOBE,
  ladder: LADDER,
  pillar: PILLAR,
  screenGlow: SCREEN_GLOW,
  wallGlow: WALL_GLOW,
  steam: STEAM,
  fan: FAN,
  lampPool: LAMP_POOL,
} as const;

export type TileId = keyof typeof TILES;

/** How big a tile is drawn, and the sprite scale that matches it. Stated once here because the
 *  stylesheet, the renderer and the simulation all have to agree on it to the pixel — a body's
 *  position is in tiles and its element is placed in CSS pixels. */
export const TILE_PX = 24;
export const TILE_CELLS = 8;
export const TILE_SCALE = TILE_PX / TILE_CELLS;
