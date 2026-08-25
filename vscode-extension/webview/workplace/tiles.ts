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
  /** FOLIAGE, so its shadow is DAPPLED rather than solid.
   *  A canopy is not an opaque object and its shadow is not a slab. It mattered here for a
   *  concrete reason rather than a botanical one: a tree's shadow rakes several cells, a copse is
   *  trees in touching cells, so solid shadows MERGE — three trees in a row cast one continuous
   *  dark bar that reads as a foreign feature lying on the ground rather than as shade. Two
   *  dappled shadows overlapping are still dapple. */
  leafy?: boolean;
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
  /* Outdoors. The grounds used to be furnished out of the INDOOR kit — a potted houseplant and a
     monitor-on-a-stand, scattered on a lawn — which is exactly what "floating trees" was: a wide
     canopy balanced on a two-pixel pot, with its silhouette translated up and to the right of it
     so the shadow floated too. A tree needs bark, three greens and its own trunk down to the
     bottom row of its tile, or it is a shrub hovering over grass. */
  t: "var(--t-bark)",
  T: "var(--t-bark-hi)",
  D: "var(--t-under)",
  M: "var(--t-leaf-hi)",
  N: "var(--t-leaf-lo)",
  q: "var(--t-stone)",
  W: "var(--t-stone-hi)",
  j: "var(--t-bloom)",
  Y: "var(--t-water)",
  C: "var(--t-water-hi)",
  /* THE FURNITURE RAMPS. Every material a prop is made of carries a lit and a shaded step derived
     from its base tone, mixed toward the scene's one warm light and one cool shade — the exact
     rule the trees already obey and the people now obey, extended to the desks and the shelves,
     because half of "the sprites are weird" was bodies and props being lit by different laws.
     Metal gets the widest ramp (it is the shiniest thing in the room), cloth the narrowest. */
  "1": "color-mix(in oklab, var(--t-metal) 66%, #eef4ff)",
  "2": "color-mix(in oklab, var(--t-metal) 62%, var(--px-shade, #2c2344))",
  "3": "color-mix(in oklab, var(--t-wood) 62%, var(--px-shade, #2c2344))",
  "4": "color-mix(in oklab, var(--t-fabric) 80%, var(--px-glint, #ffdfae))",
  "5": "color-mix(in oklab, var(--t-fabric) 74%, var(--px-shade, #2c2344))",
  "6": "color-mix(in oklab, var(--t-screen) 60%, #ffffff)",
  "7": "color-mix(in oklab, var(--t-glass) 72%, var(--px-shade, #2c2344))",
  "8": "color-mix(in oklab, var(--t-warm) 70%, var(--px-glint, #ffdfae))",
  "9": "color-mix(in oklab, var(--t-hall) 55%, var(--px-shade, #2c2344))",
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
    ".eeeeee.",
    ".e6GGGe.",
    ".eGGGGe.",
    ".eeeee2.",
    "...ee...",
    "nnnnnnnn",
    "oooooo33",
    "o3....33",
  ],
  { solid: true },
);

export const SHELF = tile(
  [
    "nnnnnnnn",
    "obbyb3y3",
    "obyybby3",
    "onnnnnn3",
    "oybb3by3",
    "obbybyy3",
    "onnnnnn3",
    "o3....33",
  ],
  { solid: true },
);

export const RACK = tile(
  [
    "11111112",
    "1eeleee2",
    "12222222",
    "1eeelee2",
    "12222222",
    "1eleeee2",
    "12222222",
    ".e....2.",
  ],
  { solid: true },
);

export const PLANT = tile(
  [
    "...MM...",
    "..MLLN..",
    ".MLLLLN.",
    ".LLNLLN.",
    "..LNLN..",
    "...tT...",
    "..noon..",
    "..o33o..",
  ],
  { solid: true },
);

export const SOFA = tile(
  [
    "........",
    ".444444.",
    "4uuuuuu5",
    "4uuuuuu5",
    "44uu5uu5",
    "4uuuuuu5",
    ".3....3.",
    "........",
  ],
  { solid: true },
);

export const BOARD = tile(
  [
    "xxxxxxxx",
    "x6aaaaax",
    "xasaa7ax",
    "xaa7ssax",
    "xaaaaa7x",
    "xxxxxxxx",
    "...xx...",
    "..x..x..",
  ],
  { solid: true },
);

export const BENCH = tile(
  [
    "........",
    "..7..a..",
    "..a..7..",
    ".aa7.77.",
    "nnnnnnnn",
    "oooooo33",
    "o3....33",
    "o3....33",
  ],
  { solid: true },
);

export const URN = tile(
  [
    "........",
    ".11112..",
    ".1e66e2.",
    ".1eeee2.",
    ".1e88e2.",
    ".12222..",
    ".nooo3..",
    ".o3333..",
  ],
  { solid: true },
);

/** The brain's own console. The only tile in the building that is drawn in the team's accent, and
 *  the one thing on the map that is unmistakably the middle of it. */
export const CORE = tile(
  [
    "..ssss..",
    ".s1ee2s.",
    "s1l11l2s",
    "s1e22e2s",
    "s1e11e2s",
    "s1l22l2s",
    ".s1ee2s.",
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

/** MEADOW: the same ground left unmown. The single cheapest thing that gives a site structure —
 *  at this pitch a change of GROUND does more than any number of props, because it is the only
 *  mark big enough to be read as a shape rather than as an object. */
export const MEADOW = tile([
  "VvVvvVvV",
  "vVLVvVVv",
  "VvVvLVvV",
  "vVVvVvVL",
  "LVvVVvVv",
  "vVvLvVLV",
  "VVvVLvVv",
  "vVLvVVvV",
]);

/** FOREST FLOOR — the ground under a canopy, where grass does not grow. This is the mark that
 *  finally grounds a tree at MAP scale: a cast shadow is three device pixels at the whole-floor
 *  rung and no alpha makes three pixels read as contact, but a change of GROUND is tile-sized and
 *  reads as a shape at every rung. A copse standing in its own darker clearing is attached to the
 *  earth the way a copse on billiard-table lawn never is. */
export const LITTER = tile([
  "DDNDDDDD",
  "DDDDDtDD",
  "DNDDDDDD",
  "DDDDNDDD",
  "DDDDDDDN",
  "DtDDDDDD",
  "DDDNDDDD",
  "DDDDDDtD",
]);

/** Bare earth, where the ground is walked or a bed has been turned over. */
export const EARTH = tile([
  "PPPQPPPP",
  "PPPPPPQP",
  "PQPPPPPP",
  "PPPPQPPP",
  "PPPPPPPP",
  "PPQPPPQP",
  "PPPPPPPP",
  "PQPPPPPP",
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

/* ── the grounds ─────────────────────────────────────────────────────────────────────────────
   Everything out here used to be drawn from the indoor kit, which is the whole of the
   "floating trees" defect: `PLANT` is a houseplant — five rows of canopy balanced on a
   three-pixel pot — and `URN` is a screen on a stand. Neither has a base wide enough to sit on
   grass, and neither has a trunk.

   Three rules the outdoor pieces all keep, because breaking any one of them is what makes a
   sprite hover:
     1. THE BASE TOUCHES ROW SEVEN. A thing standing on the ground is drawn down to the bottom of
        its own tile; a gap under it is the picture saying it is in the air.
     2. THE BASE IS WIDER THAN NOTHING. A canopy needs a trunk and the trunk needs a foot: a
        one-pixel stem under a six-pixel crown reads as a balloon on a string.
     3. THE MASS IS OFF-CENTRE AND THE TONES RUN NORTH-WEST TO SOUTH-EAST, so every plant is lit
        by the same sun as the building it stands beside. */

/** A broadleaf. The crown is three greens — lit on the north-west shoulder, mid through the body,
 *  shade under the south-east — so it turns rather than reading as a flat blob. */
export const TREE = tile(
  [
    "..MMMM..",
    ".MMMMLM.",
    "MMLLLLLM",
    "MLLLLLLN",
    ".LLLLNN.",
    "..LNNL..",
    "...Tt...",
    "..ttTt..",
  ],
  { solid: true, leafy: true },
);

/** The same tree, older and heavier, so a wood is not one drawing repeated. */
export const TREE_BIG = tile(
  [
    ".MMMMM..",
    "MMMLLLM.",
    "MLLLLLLM",
    "MLLLLLLN",
    "MLLLLNNN",
    ".LLNNNL.",
    "...TtT..",
    "..tttTt.",
  ],
  { solid: true, leafy: true },
);

/** A conifer. Stepped rather than smooth: three tiers with a hard shelf under each is what an
 *  8x8 pine can actually say, and it silhouettes against the broadleaves beside it. */
export const PINE = tile(
  [
    "...MM...",
    "..MLLM..",
    "..LLLN..",
    ".MLLLLN.",
    ".LLLLNN.",
    "MLLLLLNN",
    "...Tt...",
    "..ttTt..",
  ],
  { solid: true, leafy: true },
);

/** A shrub: mass with no trunk, low to the ground, which is what keeps a copse from being a row
 *  of lollipops. */
export const BUSH = tile(
  [
    "........",
    "........",
    "...MM...",
    "..MLLM..",
    ".MLLLLN.",
    ".LLLLNN.",
    "LLLLNNNL",
    ".LNNLNN.",
  ],
  { solid: true, leafy: true },
);

/** A boulder. The one thing out here that is neither green nor built, so it is what stops the
 *  grounds reading as a nursery. */
export const ROCK = tile(
  [
    "........",
    "........",
    "...WW...",
    "..WWqq..",
    ".WWqqqq.",
    ".Wqqqqq.",
    "qqqqqqq.",
    ".qqqqq..",
  ],
  { solid: true },
);

/** A flowerbed. Low, so it never blocks a sightline, and the one warm colour in the grounds. */
export const BLOOMS = tile(
  [
    "........",
    "........",
    "........",
    "..j..j..",
    ".LjLLjL.",
    "LLLjLLLL",
    ".LLLLLL.",
    "..LLLL..",
  ],
);

/** A tuft of longer grass. Not solid and barely there: it exists so the lawn has a texture the
 *  ground pattern alone cannot give it at this pitch. */
export const TUFT = tile([
  "........",
  "........",
  "........",
  "........",
  "..L..L..",
  ".LLL.LL.",
  "..LLLLL.",
  "...LL...",
]);

/** Standing water. It TESSELLATES — flat, with a few glints — because a pond is a cluster of
 *  these and a tile with its own rounded rim tiles into a grid of blue circles, which is exactly
 *  what the first attempt drew. The BANK is a ring of earth laid by the caller, and that is what
 *  gives the water an edge. */
export const POND = tile([
  "YYYYYYYY",
  "YYYCYYYY",
  "YYYYYYYY",
  "YYYYYYCY",
  "YCYYYYYY",
  "YYYYYYYY",
  "YYYYYCYY",
  "YYYYYYYY",
]);

/** A lamp on a post, along the path out of the gate. The only fixture outside the building, and
 *  the reason the way out reads as a way out rather than as a gap in a wall. */
export const LAMPPOST = tile(
  [
    "..llll..",
    ".l88iil.",
    ".liiiil.",
    "..1ee2..",
    "...e2...",
    "...e2...",
    "...e2...",
    "..1ee2..",
  ],
  { solid: true },
);

export const MAST = tile(
  [
    "...1e...",
    "..1ee2..",
    ".1.ee.2.",
    "1..ee..2",
    "...e2...",
    "...e2...",
    "...e2...",
    "..noo3..",
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
  "nnnnnn..",
  "onnnn3..",
  "onnnn3..",
  "onnen3..",
  "onnnn3..",
  "onnnn3..",
  "o33333..",
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
    "nnnnnnnn",
    "oybby3b3",
    "obb3yby3",
    "onnnnnn3",
    "obyy3yb3",
    "oyybbyb3",
    "onnnnnn3",
    "o3....33",
  ],
  { solid: true },
);

export const SCREEN = tile(
  [
    "........",
    ".eeeeee.",
    ".e6GGGe.",
    ".eGGGGe.",
    ".eeeee2.",
    "...ee...",
    "..nooo..",
    "..o333..",
  ],
  { solid: true },
);

/** A dish that reads as a DISH. The first drawing was a ring with a blob and a stem — the same
 *  ghost-in-a-halo misread as the old globe, from the same cause: frontal symmetry. An antenna is
 *  a TILTED bowl with a mast; the diagonal is what says "aimed at the sky". */
export const DISH = tile(
  [
    "....ee..",
    "..eeae..",
    ".eaaae..",
    "eeaaaee.",
    "eeaaee..",
    ".eeee...",
    "...ee...",
    "..oooo..",
  ],
  { solid: true },
);

export const TABLE_L = tile(
  [
    "........",
    "..nnnnnn",
    ".nnnnnnn",
    ".nnnnnnn",
    ".ooooooo",
    ".3333333",
    "..o3....",
    "..o3....",
  ],
  { solid: true },
);

export const TABLE_M = tile(
  [
    "........",
    "nnnnnnnn",
    "nnnnnnnn",
    "nnnnnnnn",
    "oooooooo",
    "33333333",
    "........",
    "........",
  ],
  { solid: true },
);

export const TABLE_R = tile(
  [
    "........",
    "nnnnnn..",
    "nnnnnnn.",
    "nnnnnnn.",
    "ooooooo.",
    "3333333.",
    "....o3..",
    "....o3..",
  ],
  { solid: true },
);

export const CHAIR = tile(
  [
    "........",
    "..4444..",
    "..uuu5..",
    "..uuu5..",
    ".uuuuu5.",
    "..e..e..",
    "..2..2..",
    "........",
  ],
  { solid: true },
);

export const COFFEE = tile(
  [
    "........",
    "..1112..",
    ".1eeee2.",
    ".18lee2.",
    ".1e77e2.",
    ".122222.",
    ".nooo3..",
    ".o3333..",
  ],
  { solid: true },
);

export const COOLER = tile(
  [
    "........",
    "..6aa7..",
    ".aaaaa7.",
    "..aaa7..",
    "..1112..",
    "..1ee2..",
    "..e..2..",
    "..2222..",
  ],
  { solid: true },
);

export const PRINTER = tile(
  [
    "........",
    "..aaaa..",
    ".111122.",
    ".1eeee2.",
    ".1e22e2.",
    ".122222.",
    ".nooo3..",
    ".o3333..",
  ],
  { solid: true },
);

export const CRATES = tile(
  [
    "........",
    "..nnnn..",
    "..o33o..",
    "..o33o..",
    "nnnnnnnn",
    "o33oo33o",
    "o3oo3o3o",
    "oooooooo",
  ],
  { solid: true },
);

export const TANK = tile(
  [
    "11111112",
    "1a6aaaa2",
    "1asaaaa2",
    "1aaaa7a2",
    "1asaa7a2",
    "1aaaaaa2",
    "12222222",
    "o3....33",
  ],
  { solid: true },
);

export const VENDING = tile(
  [
    "11111122",
    "16aaal12",
    "1abbae12",
    "1ayybl12",
    "1abbae12",
    "1aaaae12",
    "12222222",
    ".e....2.",
  ],
  { solid: true },
);

export const CABINET = tile(
  [
    "nnnnnnnn",
    "oooooo33",
    "o33ee3o3",
    "oooooo33",
    "o33ee3o3",
    "oooooo33",
    "oooooo33",
    "o3....33",
  ],
  { solid: true },
);

export const DRAFTING = tile(
  [
    "........",
    "....nnnn",
    "...nnnnn",
    "..nnnnnn",
    ".nnnnnnn",
    ".ooooooo",
    "..e...2.",
    "..e...2.",
  ],
  { solid: true },
);

/** A globe that reads as a GLOBE. The first drawing was a same-tone ring around a symmetric
 *  column of "continents", which at 24px is a grey figure inside a halo — an independent sweep
 *  literally reported it as a ghost placeholder. A planet is a FRAME around WATER with
 *  asymmetric LAND: three tones, no symmetry. */
export const GLOBE = tile(
  [
    "..eeee..",
    ".eaaLLe.",
    "eaLLaaae",
    "eaaLLLae",
    "eaLaaaae",
    ".eLaaLe.",
    "..eeee..",
    "..oooo..",
  ],
  { solid: true },
);

export const LADDER = tile(
  [
    "..n..o..",
    "..nooo..",
    "..n..o..",
    "..nooo..",
    "..n..o..",
    "..nooo..",
    "..n..o..",
    "..nooo..",
  ],
  { solid: true },
);

/** A column, not a wall. The chamber at the head of the building is held up rather than closed
 *  in, which is what makes it read as the one place in the plan that is not a room. */
export const PILLAR = tile(
  [
    "..pppp..",
    "..pww9..",
    "..pww9..",
    "..pww9..",
    "..pww9..",
    "..pww9..",
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
  meadow: MEADOW,
  litter: LITTER,
  earth: EARTH,
  path: PATH,
  mast: MAST,
  tree: TREE,
  treeBig: TREE_BIG,
  pine: PINE,
  bush: BUSH,
  rock: ROCK,
  blooms: BLOOMS,
  tuft: TUFT,
  pond: POND,
  lamppost: LAMPPOST,
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
