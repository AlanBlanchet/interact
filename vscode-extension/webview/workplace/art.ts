/** The art. Every shape in the workplace, as rows of characters.
 *
 *  Colours are named through CSS custom properties rather than baked in, so one rule in the
 *  stylesheet re-tunes the whole world for a light theme, and a worker's shirt can be their own
 *  accent without re-generating a single rectangle.
 *
 *  Each piece carries its own palette. Sharing one alphabet across ten props saved a few lines
 *  and made every char mean three things at once — a prop is easier to read when `d` is "the door
 *  panel" here and nothing at all next door.
 */
import type { Grid, Palette } from "./pixels";
import type { ZoneId } from "../../src/team";

export interface Piece {
  grid: Grid;
  pal: Palette;
}

/* ── People ──────────────────────────────────────────────────────────────────────────────────
 *
 *  Two frames, same canvas. Frame 1 raises the hands and shifts the stance; played slowly it
 *  reads as working at a desk, played fast it reads as walking. One asset, two tempos.
 */

export const POSE_REST: Grid = [
  "..hhhhhh..",
  "..hhhhhh..",
  "..kkkkkk..",
  "..kekkek..",
  "..kkkkkk..",
  "..kkmmkk..",
  "...kkkk...",
  ".ssssssss.",
  ".sssaasss.",
  ".ssssssss.",
  ".kssssssk.",
  "..tttttt..",
  "..tt..tt..",
  "..tt..tt..",
  "..bb..bb..",
  "..bb..bb..",
];

export const POSE_MOVE: Grid = [
  "..hhhhhh..",
  "..hhhhhh..",
  "..kkkkkk..",
  "..kekkek..",
  "..kkkkkk..",
  "..kkmmkk..",
  "...kkkk...",
  ".kssssssk.",
  ".sssaasss.",
  "..ssssss..",
  "..ssssss..",
  "..tttttt..",
  "..tt.tt...",
  "..tt.tt...",
  "..bb.bb...",
  "..bb.bb...",
];

/** A hat marks a role without a second sprite: the manager's cap, the researcher's field hat. */
export const HAT_BAND: Grid = ["..pppppp..", ".pppppppp."];

/** The palette a person is drawn with. Every entry is a custom property set per worker, so the
 *  same twenty rectangles come out as twenty different people. */
export const SKIN_PAL: Palette = {
  k: "var(--c-skin)",
  h: "var(--c-hair)",
  s: "var(--c-shirt)",
  a: "var(--c-badge)",
  t: "var(--c-trouser)",
  b: "var(--c-boot)",
  e: "var(--c-eye)",
  m: "var(--c-mouth)",
};

/** Someone else's session: we can see them, we do not drive them.
 *
 *  This used to map EVERY key to one tone. That is not a category, it is a HOLE — Alan read the
 *  result as broken, and correctly: a human silhouette with no hair, no face and no clothes is
 *  what a renderer draws when it has failed to find a sprite, so a flat fill will always say
 *  "missing asset" before it says "another project". Colour alone was never going to fix it,
 *  because the information the eye is missing is not hue, it is VALUE STRUCTURE — the five steps
 *  that make a shape a person.
 *
 *  So a visitor keeps every one of those steps and gives up only the HUE: one ramp, mixed from
 *  the `not-ours` accent the rail already prints that state in, so the two surfaces agree about
 *  who this is. A monochrome person in a colour photograph — somebody from another floor, in for
 *  the afternoon. They keep their eyes. What they do not get is our BADGE: the one mark that says
 *  a body belongs to this company is the one thing a guest cannot wear.
 */
export const VISITOR_PAL: Palette = {
  k: "var(--c-guest-skin)",
  h: "var(--c-guest-hair)",
  s: "var(--c-guest-coat)",
  a: "var(--c-guest-coat)",
  t: "var(--c-guest-leg)",
  b: "var(--c-guest-boot)",
  e: "var(--c-guest-eye)",
  m: "var(--c-guest-eye)",
  "#": "var(--c-guest-ink)",
};

/** The old name, kept pointing at the new palette so nothing imports a tone that no longer
 *  exists. */
export const GHOST_PAL = VISITOR_PAL;

/* ── Rooms ───────────────────────────────────────────────────────────────────────────────────
 *
 *  One prop per room, standing against the back wall. The prop is what tells you which room you
 *  are looking at before you read the sign — a rack of servers, a wall of books, a door.
 */

const CODE: Piece = {
  grid: [
    "....MMMMMMMMMM......",
    "....MggggggggM......",
    "....MgGGGGgggM......",
    "....MgggGGGGGM......",
    "....MgGGGgggGM......",
    "....MggGGGGggM......",
    "....MMMMMMMMMM......",
    "........MM..........",
    "......MMMMMM........",
    "DDDDDDDDDDDDDDDDDDDD",
    "D..................D",
    "D..................D",
    "D..................D",
    "DD................DD",
  ],
  pal: {
    M: "var(--wp-metal)",
    g: "var(--wp-screen)",
    G: "var(--wp-glow)",
    D: "var(--wp-wood)",
  },
};

const DATA: Piece = {
  grid: [
    "..RRRRRR....RRRRRR..",
    "..RLLLLR....RLLLLR..",
    "..RllllR....RllllR..",
    "..RLLLLR....RllllR..",
    "..RllllR....RLLLLR..",
    "..RLLLLR....RllllR..",
    "..RllllR....RLLLLR..",
    "..RLLLLR....RllllR..",
    "..RllllR....RLLLLR..",
    "..RRRRRR....RRRRRR..",
    "..R....R....R....R..",
    "..RRRRRR....RRRRRR..",
    "....................",
    "....................",
  ],
  pal: {
    R: "var(--wp-metal)",
    L: "var(--wp-led)",
    l: "var(--wp-led-dim)",
  },
};

/** Outside: a mast, its guy-wires, and weather. The only piece that is not furniture. */
const WEB: Piece = {
  grid: [
    ".........A..........",
    "........AAA.........",
    ".......A.A.A........",
    ".........A..........",
    "..CCCC...A...CCCC...",
    ".CCCCCC..A..CCCCCC..",
    "..CCCC..AAA..CCCC...",
    ".......AA.AA........",
    "......AA...AA.......",
    ".....AA.....AA......",
    "....AA.......AA.....",
    "...AA.........AA....",
    "..AA...........AA...",
    "....................",
  ],
  pal: {
    A: "var(--wp-metal)",
    C: "var(--wp-cloud)",
  },
};

const LIBRARY: Piece = {
  grid: [
    "SSSSSSSSSSSSSSSSSSSS",
    "SaabbccddeeffaabbccS",
    "SaabbccddeeffaabbccS",
    "SaabbccddeeffaabbccS",
    "SSSSSSSSSSSSSSSSSSSS",
    "SccddaabbffeeccddaaS",
    "SccddaabbffeeccddaaS",
    "SccddaabbffeeccddaaS",
    "SSSSSSSSSSSSSSSSSSSS",
    "SeeffccaabbddeeffccS",
    "SeeffccaabbddeeffccS",
    "SeeffccaabbddeeffccS",
    "SSSSSSSSSSSSSSSSSSSS",
    "S..................S",
  ],
  pal: {
    S: "var(--wp-wood)",
    a: "var(--wp-h1)",
    b: "var(--wp-h2)",
    c: "var(--wp-h3)",
    d: "var(--wp-h4)",
    e: "var(--wp-h5)",
    f: "var(--wp-h6)",
  },
};

const STUDIO: Piece = {
  grid: [
    "...FFFFFFFFFFFFFF...",
    "...FppppppppppppF...",
    "...FpqqqppppppppF...",
    "...FpqqqqqqppppqF...",
    "...FppqqqqqqqpppF...",
    "...FpppqqqqqqqppF...",
    "...FppppqqqqqpppF...",
    "...FppppppppppppF...",
    "...FFFFFFFFFFFFFF...",
    "........FF..........",
    "........FF..........",
    "......FFFFFF........",
    "....................",
    "....................",
  ],
  pal: {
    F: "var(--wp-wood)",
    p: "var(--wp-paper)",
    q: "var(--wp-glow)",
  },
};

const LAB: Piece = {
  grid: [
    "....................",
    ".....vv.....OOOOOO..",
    ".....vv.....OyyyyO..",
    "....vvvv....OyzzyO..",
    "...vvvvvv...OyyyyO..",
    "...vxxxxv...OOOOOO..",
    "...vxxxxv.....OO....",
    "...vvvvvv...OOOOOO..",
    "BBBBBBBBBBBBBBBBBBBB",
    "B..................B",
    "B..................B",
    "BB................BB",
    "....................",
    "....................",
  ],
  pal: {
    v: "var(--wp-glass)",
    x: "var(--wp-h5)",
    O: "var(--wp-metal)",
    y: "var(--wp-screen)",
    z: "var(--wp-glow)",
    B: "var(--wp-wood)",
  },
};

const MANAGERS: Piece = {
  grid: [
    "..WWWWWWWWWWWWWW....",
    "..WnnnnnnnnnnnnW....",
    "..WnjjnnnnjjnnnW....",
    "..WnnjjjjjjnnnnW....",
    "..WnjjnnnnjjnnnW....",
    "..WnnnnnnnnnnnnW....",
    "..WWWWWWWWWWWWWW....",
    "....................",
    "...TTTTTTTTTTTT.....",
    "..TTTTTTTTTTTTTT....",
    "....TT......TT......",
    "....TT......TT......",
    "....TT......TT......",
    "....................",
  ],
  pal: {
    W: "var(--wp-metal)",
    n: "var(--wp-paper)",
    j: "var(--wp-glow)",
    T: "var(--wp-wood)",
  },
};

const ENTRY: Piece = {
  grid: [
    ".....XXXXXX.........",
    ".....XxxxxX.........",
    "....................",
    "....DDDDDDDD........",
    "....DddddddD........",
    "....DddddddD........",
    "....DddddddD........",
    "....DdddhddD........",
    "....DddddddD........",
    "....DddddddD........",
    "....DddddddD........",
    "....DddddddD........",
    "....DDDDDDDD........",
    "...MMMMMMMMMM.......",
  ],
  pal: {
    X: "var(--wp-metal)",
    x: "var(--wp-exit)",
    D: "var(--wp-wood)",
    d: "var(--wp-door)",
    h: "var(--wp-brass)",
    M: "var(--wp-h2)",
  },
};

const BREAK: Piece = {
  grid: [
    "....................",
    "..............PP....",
    ".............PPPP...",
    "..CCCCCCCCC..PPPPP..",
    ".CCCCCCCCCCC.PPPP...",
    ".CuuuuuuuuuC..VV....",
    ".CuuuuuuuuuC..VV....",
    ".CCCCCCCCCCC..VV....",
    "..C.......C..VVVV...",
    "..C.......C..VVVV...",
    "....................",
    "....................",
    "....................",
    "....................",
  ],
  pal: {
    C: "var(--wp-h6)",
    u: "var(--wp-cushion)",
    P: "var(--wp-leaf)",
    V: "var(--wp-wood)",
  },
};

/** Not a zone — the connective tissue that makes eight rooms read as one building, and now the
 *  thing every journey in the place actually goes through.
 *
 *  It used to be a small pale wedge: a picture of stairs, at the bottom of the building only,
 *  standing for a vertical circulation that did not exist. It is now a FLIGHT, repeated on every
 *  storey and plumb by construction, because the engine routes real walks up and down it — a
 *  worker sent from the Lab to the Code room climbs these. So it is drawn as steps with a rail
 *  rather than as a triangle: at 4px a tread, a silhouette reads as stairs and a ramp does not. */
export const STAIRS: Piece = {
  grid: [
    "..........rr",
    "........rr.s",
    "........rrss",
    "......rr.sss",
    "......rrssss",
    "....rr.sssss",
    "....rrssssss",
    "..rr.sssssss",
    "..rrssssssss",
    "rr.sssssssss",
    "rrssssssssss",
    "ssssssssssss",
    "ssssssssssss",
  ],
  pal: { s: "var(--wp-metal)", r: "var(--wp-brass)" },
};

export const PROPS: Record<ZoneId, Piece> = {
  entry: ENTRY,
  managers: MANAGERS,
  code: CODE,
  data: DATA,
  web: WEB,
  library: LIBRARY,
  studio: STUDIO,
  lab: LAB,
  idle: BREAK,
};

/* ── Status marks ────────────────────────────────────────────────────────────────────────────
 *
 *  Status is read by SHAPE first. Colour is the second signal, never the only one: a red dot and
 *  a green dot are the same dot to a third of readers, and at 4px they are the same dot to
 *  everyone.
 */

export const MARKS: Record<string, Piece> = {
  // running — a filled disc, the one that pulses
  running: {
    grid: ["..MM..", ".MMMM.", "MMMMMM", "MMMMMM", ".MMMM.", "..MM.."],
    pal: { M: "var(--mark)" },
  },
  // done — a tick
  done: {
    grid: ["....MM", "...MM.", "M..MM.", "MM.MM.", ".MMM..", "..MM.."],
    pal: { M: "var(--mark)" },
  },
  // error — a warning wedge, the only pointed shape in the set
  error: {
    grid: ["..MM..", "..MM..", ".MMMM.", ".M..M.", "MMMMMM", "MM..MM"],
    pal: { M: "var(--mark)" },
  },
  // foreign — an open square: present, not ours
  foreign: {
    grid: ["MMMMMM", "M....M", "M....M", "M....M", "M....M", "MMMMMM"],
    pal: { M: "var(--mark)" },
  },
  // asked — a sealed note. The one state where the agent is waiting on a PERSON, so the shape is
  // the only one in the set that depicts a thing handed over rather than a condition.
  asked: {
    grid: ["MMMMMM", "MM..MM", "M.MM.M", "M....M", "M....M", "MMMMMM"],
    pal: { M: "var(--mark)" },
  },
  // held — an hourglass: running, but nothing has happened for a long time.
  //
  // It needed its own shape. The side bar used to stamp HELD with the open square, which is the
  // mark for NOT OURS — two different facts wearing one silhouette in a set whose entire premise
  // is that shape carries the status before colour does. An hourglass is also the only mark in
  // the set that says "time is the problem", which is exactly what held means.
  held: {
    grid: ["MMMMMM", ".M..M.", "..MM..", "..MM..", ".M..M.", "MMMMMM"],
    pal: { M: "var(--mark)" },
  },
};

/** Weather, and the rest of the world seen from the yard. Both exist so that "outside" reads as
 *  somewhere a person has GONE rather than as an empty column beside the building. */
export const CLOUD: Piece = {
  grid: [
    "....ccccc.....",
    "..ccccccccc...",
    ".ccccccccccc..",
    "ccccccccccccc.",
    ".ccccccccc....",
  ],
  pal: { c: "var(--wp-cloud)" },
};

/** One bright disc. It is the sun in a light theme and the moon in a dark one without changing a
 *  pixel — the sky it sits on is mixed from the editor background, so the same circle reads both
 *  ways and the outdoors stops being a flat rectangle of colour. */
export const DISC: Piece = {
  grid: [
    "..oooo..",
    ".oooooo.",
    "oooooooo",
    "oooooooo",
    "oooooooo",
    "oooooooo",
    ".oooooo.",
    "..oooo..",
  ],
  pal: { o: "var(--wp-disc)" },
};

export const HORIZON: Piece = {
  grid: [
    "......bb..............bb................",
    "......bb....bbbb......bb......bbb.......",
    "..bbbbbb....bbbb..bb..bbbb....bbb...bbb.",
    "..bbbbbb.bbbbbbb..bb..bbbb.bbbbbb...bbb.",
    "bbbbbbbb.bbbbbbb.bbbbbbbbb.bbbbbb.bbbbbb",
    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  ],
  pal: { b: "var(--wp-far)" },
};

/** A message between two agents, carried across the building by hand. The workplace already had
 *  a way to say "this person moved"; this is the same idea for "this person SPOKE to that one" —
 *  a thing that travels, not a wire that hangs there forever. */
export const NOTE: Piece = {
  grid: [
    "eeeeeee",
    "efeeefe",
    "eefefee",
    "eeefeee",
    "eeeeeee",
  ],
  pal: { e: "var(--wp-paper)", f: "var(--wp-ink)" },
};

/** Someone has stopped. Drawn, not written — a room where three sprites have gone grey and
 *  sprouted z's says "half my team is stalled" faster than three timestamps do. */
export const SNOOZE: Piece = {
  grid: ["zzzz.", "...z.", "..z..", ".z...", "zzzz."],
  pal: { z: "var(--mark)" },
};

/* ── Presence — the world noticing the person at the glass ───────────────────────────────────
 *
 *  Three small pieces for the three beats of being noticed: a hand raised in greeting when the
 *  pointer rests on somebody, a startled mark when they are poked, and a claim ring under the one
 *  who has been picked up. All drawn in the engine's own rectangles — a rotated CSS arm or a
 *  border-radius ring is a soft shape in a scene made entirely of hard ones. */

/** Two frames of a wave: the hand crosses its own arc, pivoting over the wrist pixel. The skin
 *  var is the actor's own, so every character waves with their own hand. */
export const WAVE_A: Grid = [
  "kk...",
  "kkk..",
  "..k..",
];
export const WAVE_B: Grid = [
  "...kk",
  "..kkk",
  "..k..",
];
export const WAVE_PAL: Palette = { k: "var(--c-skin, #e0a877)" };

/** The startle. A poked character says "!" the way a unit in any tile game does — above the
 *  head, loud, and gone in half a second. */
export const BANG: Piece = {
  /* A fixed loud yellow, not the theme's chart tan: a startle that lasts half a second earns the
     one saturated pixel colour in the building, in both themes. */
  grid: ["yy", "yy", "yy", "yy", "..", "yy"],
  pal: { y: "#ffd94a" },
};

/** The claim ring: picked up, the way a unit is picked up. Stepped, never round, and drawn in
 *  the pod's own accent so WHOSE team you are holding is part of the mark. */
export const RING: Piece = {
  grid: [
    "..rrrrrrrr..",
    ".r........r.",
    "r..........r",
    ".r........r.",
    "..rrrrrrrr..",
  ],
  /* The accent lifted toward the foreground: the raw pod hue is tuned for shirts and pools and
     sinks into the floor as a one-pixel line. */
  pal: { r: "color-mix(in srgb, var(--accent, var(--wp-h1, #4daafc)) 62%, var(--wp-fg, #ccc))" },
};

/* ── Travel ──────────────────────────────────────────────────────────────────────────────────
 *
 *  `POSE_MOVE` played fast reads as "busy", which is what it was authored for — the hands move,
 *  the feet barely do. That is right for someone AT a desk and wrong for someone crossing the
 *  building: at 4px a foot the eye reads the STRIDE, not the arms, so a person walking a corridor
 *  with their feet 2px apart looks like a picture being dragged.
 *
 *  So travel gets its own two frames, and the only thing they exaggerate is the split between the
 *  legs and the counter-swing of the arms. Same canvas, same palette keys — a traveller is the
 *  same person, walking.
 */
export const POSE_WALK_A: Grid = [
  "..hhhhhh..",
  "..hhhhhh..",
  "..kkkkkk..",
  "..kekkek..",
  "..kkkkkk..",
  "..kkmmkk..",
  "...kkkk...",
  "..ssssssk.",
  ".ksssaass.",
  "..ssssss..",
  "..ssssss..",
  "..tttttt..",
  ".ttt..tt..",
  ".tt....tt.",
  "bb......bb",
  "bb......bb",
];

export const POSE_WALK_B: Grid = [
  "..hhhhhh..",
  "..hhhhhh..",
  "..kkkkkk..",
  "..kekkek..",
  "..kkkkkk..",
  "..kkmmkk..",
  "...kkkk...",
  ".kssssss..",
  ".sssaasss.",
  "..ssssss..",
  "..ssssss..",
  "..tttttt..",
  "..tt..ttt.",
  ".tt....tt.",
  "bb......bb",
  "bb......bb",
];

/* ── Sitting down ────────────────────────────────────────────────────────────────────────────
 *
 *  The state of a run used to be a WORD on a placard over a standing body: DONE, HELD, NOT OURS,
 *  stamped on everybody, all the time. "All the agents say finished whereas we don't care —
 *  instead they could have a seat or rest in their room."
 *
 *  So the body carries the ordinary states and the placard is kept for the two that actually want
 *  a person: ERROR and ASKED. Which means the sprite sheet needs postures, and a posture is worth
 *  authoring only if it reads at 30x42 across a room:
 *
 *    SIT     forward, elbows out to the desk, knees toward you. Working.
 *    SLUMP   the same seat with the head sunk into the shoulders and the eyes shut. Stopped.
 *    LOUNGE  leaned back, arms along the back of the bench, legs stretched. Done, and at ease.
 *
 *  All three are 14 rows against the standing figure's 16, and every sprite is anchored at the
 *  boots — so sitting down literally lowers the head six pixels and the difference is visible
 *  before any of the detail is.
 */

/** At the desk. The arms reach OUT to where the desk is, which is the whole tell: a seated figure
 *  with its arms at its sides is a person on a chair, not a person working. */
export const POSE_SIT_A: Grid = [
  "..hhhhhh..",
  "..hhhhhh..",
  "..kkkkkk..",
  "..kekkek..",
  "..kkkkkk..",
  "..kkmmkk..",
  "...kkkk...",
  ".ssssssss.",
  ".sssaasss.",
  "kssssssssk",
  ".tttttttt.",
  ".bb....bb.",
];

/** The same seat, leaned one pixel into the screen. Played on the beat this is somebody typing;
 *  it is the same trick the standing pair uses and it costs one row of difference. */
export const POSE_SIT_B: Grid = [
  "..........",
  "..hhhhhh..",
  "..hhhhhh..",
  "..kkkkkk..",
  "..kekkek..",
  "..kkkkkk..",
  "..kkmmkk..",
  "...kkkk...",
  ".ssssssss.",
  "kssssssssk",
  ".tttttttt.",
  ".bb....bb.",
];

/** Stopped. Head down into the shoulders, eyes shut, arms hanging — and NOT played as a pair, so
 *  the one body on the floor that is genuinely not moving is genuinely not moving. */
export const POSE_SLUMP: Grid = [
  "..........",
  "..........",
  "..hhhhhh..",
  "..hhhhhh..",
  "..kkkkkk..",
  "..kmkkmk..",
  "..kkkkkk..",
  ".ssssssss.",
  ".sssaasss.",
  ".kssssssk.",
  ".tttttttt.",
  ".bb....bb.",
];

/** At ease. Shoulders up around the neck, arms spread along the back of the bench, legs pushed
 *  out — the posture nobody holds at a desk, which is why it says "finished" without a word. */
export const POSE_REST_A: Grid = [
  "..........",
  "..hhhhhh..",
  "..hhhhhh..",
  "..kkkkkk..",
  "..kekkek..",
  "..kkkkkk..",
  "..kkmmkk..",
  "..skkkks..",
  "kssssssssk",
  ".sssaasss.",
  ".tttttttt.",
  "ttt....ttt",
  "bb......bb",
];

/** The breath. One row of chest, which at this size is the whole difference between a person
 *  resting and a prop of a person. */
export const POSE_REST_B: Grid = [
  "..hhhhhh..",
  "..hhhhhh..",
  "..kkkkkk..",
  "..kekkek..",
  "..kkkkkk..",
  "..kkmmkk..",
  "..skkkks..",
  "kssssssssk",
  ".sssaasss.",
  ".ssssssss.",
  ".tttttttt.",
  "ttt....ttt",
  "bb......bb",
];

/** The runner who carries the post. Deliberately NOT one of the team: a message crossing the
 *  building must not be mistaken for a person changing rooms, so the courier is smaller, has no
 *  face and no badge, and is drawn in one flat tone with the note in front of them. */
export const POSE_RUN_A: Grid = [
  "..hhhh..",
  "..kkkk..",
  ".ssssss.",
  "nssssss.",
  "nsssss..",
  "..tttt..",
  ".tt..tt.",
  "bb....bb",
];

export const POSE_RUN_B: Grid = [
  "..hhhh..",
  "..kkkk..",
  ".ssssss.",
  "nssssss.",
  "nssssss.",
  "..tttt..",
  "..t..t..",
  ".bb..bb.",
];

/** A courier is a silhouette plus the thing they are carrying. The note keeps the post's own
 *  colour so the object crossing the floor is recognisably the same object the legend names. */
export const RUNNER_PAL: Palette = {
  k: "var(--wp-runner)",
  h: "var(--wp-runner)",
  s: "var(--wp-runner)",
  t: "var(--wp-runner)",
  b: "var(--wp-runner)",
  n: "var(--wp-paper)",
  // The derived rim defaults to the building's ink, and at this size the rim is half the body —
  // a courier drawn mostly in near-black vanished against every wall it crossed. Its own rim,
  // one step darker than the body, keeps the silhouette without swallowing it.
  "#": "var(--wp-runner-ink)",
};

/** The front door, open. Same canvas as `ENTRY` so the two frames sit on the same pixel grid and
 *  the door swings instead of the whole wall jumping. It opens because somebody went through it —
 *  never on a timer. */
export const ENTRY_OPEN: Grid = [
  ".....XXXXXX.........",
  ".....XxxxxX.........",
  "....................",
  "....DDDDDDDD........",
  "....DddooooD........",
  "....DddooooD........",
  "....DddooooD........",
  "....DddooooD........",
  "....DddooooD........",
  "....DddooooD........",
  "....DddooooD........",
  "....DddooooD........",
  "....DDDDDDDD........",
  "...MMMMMMMMMM.......",
];

/** The door as a two-frame piece: shut, and open onto daylight. */
export const DOOR: { frames: Grid[]; pal: Palette } = {
  frames: [ENTRY.grid, ENTRY_OPEN],
  pal: { ...ENTRY.pal, o: "var(--wp-daylight)" },
};

/* ── faculties ───────────────────────────────────────────────────────────────────────────────
 *
 *  What a character can DO, drawn rather than typed. `capabilities.ts` gives each faculty a single
 *  unicode mark, which is right for a log line and wrong here: half of them (the alchemical air
 *  sign for "searches", the chain link for "delegates") are missing from the fonts a VS Code
 *  webview actually has, so they render as tofu boxes — six identical squares under every
 *  character, which is worse than showing nothing. Six drawings cost less than one font fallback
 *  and are legible at ten pixels, which the glyphs are not.
 *
 *  Keyed by the faculty ID, so `capabilities.ts` stays the single source of what a tool grants and
 *  this is only how it is drawn. An id with no drawing falls back to its unicode mark.
 */
export const FACULTY_ART: Record<string, Piece> = {
  // reads the code — a page with lines written on it
  reads: {
    grid: ["MMMMMMM", "M.....M", "M.MMM.M", "M.....M", "M.MMM.M", "M.....M", "MMMMMMM"],
    pal: { M: "var(--mark)" },
  },
  // changes files — a pencil, nib down
  writes: {
    grid: [".....MM", "....MMM", "...MMM.", "..MMM..", ".MMM...", "MMM....", "MM....."],
    pal: { M: "var(--mark)" },
  },
  // runs commands — the prompt caret and its line
  runs: {
    grid: ["MM.....", ".MM....", "..MM...", "...MM..", "..MM...", ".MM....", "MM.MMMM"],
    pal: { M: "var(--mark)" },
  },
  // sees the screen — an eye
  sees: {
    grid: ["..MMM..", ".M...M.", "M..M..M", "M.MMM.M", "M..M..M", ".M...M.", "..MMM.."],
    pal: { M: "var(--mark)" },
  },
  // searches the web — a globe with its meridians
  searches: {
    grid: ["..MMM..", ".M.M.M.", "M..M..M", "MMMMMMM", "M..M..M", ".M.M.M.", "..MMM.."],
    pal: { M: "var(--mark)" },
  },
  // puts others to work — one that becomes two
  delegates: {
    grid: ["MM...MM", "MM...MM", ".M...M.", "..MMM..", "...M...", "...M...", "..MMM.."],
    pal: { M: "var(--mark)" },
  },
};
