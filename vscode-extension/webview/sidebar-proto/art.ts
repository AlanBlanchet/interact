/** The hardware. Everything the SPINDLE is made of, as rows of characters.
 *
 *  Deliberately small. The people, their faces, the status marks and the sleep mark are NOT
 *  re-drawn here — they are imported from `webview/workplace/art.ts` and rendered through the
 *  workplace's own engine, so the same twenty rectangles that make a person in the building make
 *  the same person on this board. That is the point: the two surfaces are coherent because they
 *  share ASSETS and a RENDERER, not because one was restyled to resemble the other.
 *
 *  What is new here is the ironmongery a paper spike needs and a building does not: the rod, its
 *  point, its base, and the curl a slip takes on when nobody has touched it for hours.
 */
import type { Grid, Palette } from "../workplace/pixels";

export interface Piece {
  grid: Grid;
  pal: Palette;
}

/** The rod is drawn as three tones read left to right — highlight, body, shade — which is the
 *  whole trick for making a flat column read as a cylinder at six pixels wide. The long middle of
 *  the rod is a CSS gradient with the same three hard stops (it has to stretch to whatever height
 *  the panel is), so the tip and base below must use exactly these proportions or the join shows.
 */
const ROD: Palette = {
  l: "var(--sp-rod-hi)",
  m: "var(--sp-rod)",
  d: "var(--sp-rod-lo)",
};

/** The point, poking up above the topmost slip. A spike with no point is a pipe. */
export const SPINDLE_TIP: Piece = {
  grid: [
    "..lm..",
    "..lm..",
    "..lm..",
    ".llmd.",
    ".llmd.",
    "llmmmd",
    "llmmmd",
  ],
  pal: ROD,
};

/** The weighted foot. It sits at the very bottom of the panel, under everything — including the
 *  composer — because the one rod running through every slip is what makes this panel ONE object
 *  instead of two stacked ones. */
export const SPINDLE_BASE: Piece = {
  grid: [
    "..llmmmd..",
    "..llmmmd..",
    ".llmmmmdd.",
    "llmmmmmmdd",
    "dddddddddd",
    ".dddddddd.",
  ],
  pal: ROD,
};

/** The curl a slip takes when it has been sitting untouched. Drawn, not written: a corner that has
 *  lifted says "nobody has been back to this in hours" before a timestamp is read, which is the
 *  same reasoning the workplace uses when it stops a stalled worker moving. */
export const DOG_EAR: Piece = {
  grid: [
    "ppppp.",
    "ppppq.",
    "pppqq.",
    "ppqqq.",
    "pqqqq.",
    ".qqqq.",
  ],
  pal: {
    p: "var(--sp-paper-shade)",
    q: "var(--sp-paper-back)",
  },
};

/** A pennant clipped to the slip of anyone who has left the building. The workplace says "outside"
 *  by putting a person past the exterior wall under a sky; a board on a desk has no outside, so it
 *  says it with a flag instead — same fact, told in the language the object actually has. */
export const OUT_FLAG: Piece = {
  grid: [
    "pp....",
    "pFFFF.",
    "pFFFFF",
    "pFFFF.",
    "pp....",
    "pp....",
  ],
  pal: {
    p: "var(--sp-rod)",
    F: "var(--pod, var(--sp-rod-hi))",
  },
};

/** The staple holding a report's slip onto its lead's. Two legs and a bar — at scale 2 that is
 *  six pixels of metal, and it is the difference between "a nested list row" and "a smaller piece
 *  of paper physically attached to a bigger one". */
export const STAPLE: Piece = {
  grid: [
    "mmmm",
    "m..m",
  ],
  pal: { m: "var(--sp-rod-lo)" },
};

/** What is standing on the desk when there is nothing on the spike.
 *
 *  The workplace answers "this room is empty" with a room that still has a floor, its props and its
 *  plaque — a furnished room with nobody in it, never a hole in the picture. A desk with a clear
 *  spike is the same problem, so it gets the same answer: the stamp and its pad sit there whether
 *  or not there is anything to stamp, and they are what makes the empty stretch a PLACE rather than
 *  unlit canvas. It also rhymes: DONE and ERROR are stamped on the slips above, and this is the
 *  thing that stamps them.
 */
export const DESK_STAMP: Piece = {
  grid: [
    "...mmmm...........",
    "..mmmmmm..........",
    "...mmmm...........",
    "....nn............",
    "....nn............",
    "..bbbbbb..........",
    "..bbbbbb...ppppppp",
    "..bbbbbb...pIIIIIp",
    "..rrrrrr...ppppppp",
  ],
  pal: {
    m: "var(--sp-prop-hi)",
    n: "var(--sp-prop-lo)",
    b: "var(--sp-prop)",
    r: "var(--sp-prop-lo)",
    p: "var(--sp-prop)",
    I: "var(--sp-prop-lo)",
    // The derived rim, named explicitly: the engine defaults it to the workplace's literal ink,
    // which disappears against a dark desk. A prop that sits ON the desk rims in the desk's own
    // shadow line instead, so it reads in both themes.
    "#": "var(--sp-desk-rim)",
  },
};

/** The corner of the pad, the way a desk blotter is actually held down: four leather mounts the
 *  sheet slides into. One grid, placed four times and turned — which is what the real object is.
 *  It is the piece that gives the empty stretch an EDGE, and an edge is the difference between an
 *  empty room and a hole in the picture. */
export const PAD_CORNER: Piece = {
  grid: [
    "mmmmmmmm",
    "mmmmmmm.",
    "mmmmmm..",
    "mmmmm...",
    "mmmm....",
    "mmm.....",
    "mm......",
    "m.......",
  ],
  pal: { m: "var(--sp-prop)" },
};
