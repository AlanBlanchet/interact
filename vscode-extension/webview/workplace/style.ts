/** The look of the place.
 *
 *  Three rules run through all of it.
 *
 *  COLOUR follows the editor. Walls, floors, light and paper are mixed from `--vscode-*` tokens,
 *  so the building is dim and warm in a dark theme and bright and cool in a light one without a
 *  second palette existing anywhere. Only the people keep literal tones — a person tinted by the
 *  editor background stops looking like a person.
 *
 *  MOTION follows one beat. Every ambient animation's duration is an integer ratio of `--beat`,
 *  so a floor full of screens, plants and steam moves as one thing rather than as thirty
 *  independent loops. Two deliberate exceptions: walking, driven by the ENGINE off the distance
 *  covered (a footfall on a CSS clock slides the moment a body speeds up), and the fan, which is
 *  the one thing in the building that genuinely turns at a constant rate.
 *
 *  The FRAME is a window, not a fit. The building is bigger than the panel on purpose and the
 *  camera goes to the work. Scaling the whole plan down to fit is what produced eighteen-pixel
 *  characters and six-pixel capability marks in the side bar this actually ships in.
 */

import { STAMP_CSS } from "./status";

export const STYLE = String.raw`
*, *::before, *::after { box-sizing: border-box; }
html, body, figure, figcaption, header, footer, p { margin: 0; padding: 0; }

body {
  font-family: var(--vscode-font-family, system-ui, sans-serif);
  color: var(--vscode-foreground, #ccc);
  background: var(--vscode-editor-background, #1e1e1e);
  font-size: 12px;
  -webkit-font-smoothing: antialiased;
  overflow: hidden;
}

.wp {
  --beat: 2.4s;

  --wp-bg: var(--vscode-editor-background, #1e1e1e);
  --wp-fg: var(--vscode-editor-foreground, #d4d4d4);
  /* The editor's description colour is tuned for the EDITOR background, not for a small label on
     a busy floor: it measures 3.95:1 at 10px in a light theme, under the 4.5 floor. */
  --wp-dim: color-mix(in srgb, var(--vscode-descriptionForeground, #9a9a9a) 68%, var(--wp-fg));
  --wp-ink: #14101c;
  --wp-tint: #e8e4f0;

  --wp-h1: var(--vscode-charts-blue, #4f9cf5);
  --wp-h2: var(--vscode-charts-purple, #b180d7);
  --wp-h3: var(--vscode-charts-yellow, #d7ba7d);
  --wp-h4: var(--vscode-charts-green, #89d185);
  --wp-h5: var(--vscode-charts-orange, #d18616);
  --wp-h6: color-mix(in srgb, var(--wp-h1) 55%, var(--wp-h4));
  --wp-h7: color-mix(in srgb, var(--wp-h2) 55%, var(--wp-h5));
  --wp-ok: var(--wp-h4);
  --wp-bad: var(--vscode-errorForeground, #f14c4c);
  --wp-line: color-mix(in srgb, var(--wp-fg) 26%, var(--wp-bg));
  /* A room nobody is in. A VEIL rather than an absent glow: in a light theme "no light" left the
     empty room the BRIGHTEST thing on screen, so occupancy read backwards. */
  --wp-shut: color-mix(in srgb, var(--wp-ink) 34%, transparent);
  --wp-plate: color-mix(in srgb, var(--wp-fg) 82%, var(--wp-bg));
  --wp-paper: color-mix(in srgb, #f3efe4 82%, var(--wp-bg));
  --wp-chrome: color-mix(in srgb, var(--wp-bg) 92%, var(--wp-fg));

  /* ── the tile palette ───────────────────────────────────────────────────────────────────
     Every colour any tile may use, in one place. The art is authored against these names, so a
     light building and a dark one are the same drawings — no second tileset exists. */
  --t-floor: color-mix(in srgb, var(--wp-fg) 13%, var(--wp-bg));
  --t-floor-hi: color-mix(in srgb, var(--wp-fg) 20%, var(--wp-bg));
  --t-grout: color-mix(in srgb, var(--wp-fg) 19%, var(--wp-bg));
  --t-dais: color-mix(in srgb, var(--wp-h3) 22%, var(--wp-bg));
  --t-dais-hi: color-mix(in srgb, var(--wp-h3) 34%, var(--wp-bg));
  --t-carpet: color-mix(in srgb, var(--wp-fg) 11%, var(--wp-bg));
  --t-carpet-hi: color-mix(in srgb, var(--wp-fg) 16%, var(--wp-bg));
  --t-wall: color-mix(in srgb, var(--wp-fg) 24%, var(--wp-bg));
  --t-wall-cap: color-mix(in srgb, var(--wp-fg) 38%, var(--wp-bg));
  --t-wall-foot: color-mix(in srgb, var(--wp-ink) 60%, var(--wp-bg));
  /* The wall you LOOK AT rather than down on: lighter than the cap, with a skirting under it.
     One tile band on all four sides is a border; this is what makes it a room. */
  --t-face: color-mix(in srgb, var(--wp-fg) 31%, var(--wp-bg));
  --t-skirt: color-mix(in srgb, var(--wp-fg) 17%, var(--wp-bg));
  --t-shade: color-mix(in srgb, var(--wp-ink) 72%, var(--wp-bg));
  /* The passage has to look nothing like the places it joins, so the hall is the LIGHTEST ground
     in the building and the runner down the middle of it is the only warm one. */
  --t-hall: color-mix(in srgb, var(--wp-fg) 27%, var(--wp-bg));
  --t-hall-band: color-mix(in srgb, var(--wp-fg) 36%, var(--wp-bg));
  /* And the building's own mass has to look nothing like a floor: darker than any of them, so a
     room reads as carved out of a solid block rather than drawn on a sheet. */
  --t-mass: color-mix(in srgb, var(--wp-ink) 50%, var(--wp-bg));
  --t-rug: color-mix(in srgb, var(--wp-fg) 15%, var(--wp-bg));
  --t-rug-hi: color-mix(in srgb, var(--wp-fg) 23%, var(--wp-bg));
  --t-runner: color-mix(in srgb, var(--wp-h5) 30%, var(--wp-bg));
  --t-runner-hi: color-mix(in srgb, var(--wp-h5) 44%, var(--wp-bg));
  --t-screen: color-mix(in srgb, var(--wp-h1) 74%, var(--wp-bg));
  --t-warm: color-mix(in srgb, var(--wp-h3) 62%, var(--wp-bg));
  --t-mat: color-mix(in srgb, var(--wp-h3) 26%, var(--wp-bg));
  --t-wood: color-mix(in srgb, #8a5a2b 74%, var(--wp-bg));
  --t-wood-hi: color-mix(in srgb, #b8834a 74%, var(--wp-bg));
  --t-metal: color-mix(in srgb, var(--wp-fg) 46%, var(--wp-bg));
  --t-lit: var(--wp-h4);
  --t-glass: color-mix(in srgb, #9fd6e0 52%, var(--wp-bg));
  --t-leaf: color-mix(in srgb, var(--wp-h4) 62%, var(--wp-bg));
  --t-ground: color-mix(in srgb, var(--wp-h4) 26%, var(--wp-bg));
  --t-ground-hi: color-mix(in srgb, var(--wp-h4) 36%, var(--wp-bg));
  --t-path: color-mix(in srgb, var(--wp-h3) 30%, var(--wp-bg));
  --t-path-hi: color-mix(in srgb, var(--wp-h3) 40%, var(--wp-bg));
  --t-fabric: color-mix(in srgb, var(--wp-h5) 40%, var(--wp-bg));
  --t-book: color-mix(in srgb, var(--wp-h2) 62%, var(--wp-bg));
  --t-book2: color-mix(in srgb, var(--wp-h3) 62%, var(--wp-bg));
  --t-ink: color-mix(in srgb, var(--wp-ink) 78%, var(--wp-bg));

  /* ── the light model ────────────────────────────────────────────────────────────────────
     Depth in this view comes from LIGHT, not from the theme. A room is dark and its lamps carve
     quantised pools out of that dark; every wall drops a hard band; every standing thing drops
     its own silhouette. Which is why the two themes are two TIMES OF DAY rather than one picture
     with its contrast drained: at night the pools are most of what you can see, and by day the
     range comes from shadow instead. */
  --l-lamp: var(--wp-h3);
  --l-tint: var(--l-lamp);
  --l-mix: 0%;
  /* Night. Strong pools on a genuinely dark floor. */
  --l-0: 36%;
  --l-1: 20%;
  --l-2: 7%;
  --l-edge: color-mix(in srgb, var(--wp-ink) 30%, transparent);
  --l-unlit: color-mix(in srgb, var(--wp-ink) 58%, transparent);
  --l-ao: color-mix(in srgb, var(--wp-ink) 50%, transparent);
  --wp-drop: color-mix(in srgb, var(--wp-ink) 62%, transparent);

  --stamp-ink: var(--wp-fg);
  --stamp-quiet: var(--wp-dim);
  --stamp-mix: var(--wp-bg);
  --stamp-bg: var(--wp-bg);
  --stamp-shadow: var(--wp-ink);

  display: flex;
  flex-direction: column;
  height: 100vh;
  padding: 3px;
  gap: 0;
}

/* A light theme has to flip the tint dark, or every team colour pastels out against cream. */
body.vscode-light .wp,
body.vscode-high-contrast-light .wp {
  --wp-tint: #2f2a3a;
  --t-wall-foot: color-mix(in srgb, var(--wp-ink) 32%, var(--wp-bg));
  --t-carpet: color-mix(in srgb, color-mix(in srgb, var(--wp-h1) 26%, var(--wp-fg)) 30%, var(--wp-bg));
  --t-carpet-hi: color-mix(in srgb, color-mix(in srgb, var(--wp-h1) 26%, var(--wp-fg)) 40%, var(--wp-bg));
  --t-shade: color-mix(in srgb, var(--wp-ink) 46%, var(--wp-bg));

  /* THE GROUND HAS TO BE A MID-TONE, or light has nothing to lift and shadow nothing to drop.
     Every ground tile is mixed from the editor foreground toward the background, and on a WHITE
     background thirteen percent of a dark grey is L* 92 — so the floor was already brighter than
     any lamp could make it and the pools came out as pastel stickers on paper. */
  --t-floor: color-mix(in srgb, var(--wp-fg) 28%, var(--wp-bg));
  --t-floor-hi: color-mix(in srgb, var(--wp-fg) 20%, var(--wp-bg));
  --t-grout: color-mix(in srgb, var(--wp-fg) 34%, var(--wp-bg));
  --t-rug: color-mix(in srgb, var(--wp-fg) 30%, var(--wp-bg));
  --t-rug-hi: color-mix(in srgb, var(--wp-fg) 40%, var(--wp-bg));
  --t-hall: color-mix(in srgb, var(--wp-fg) 20%, var(--wp-bg));
  --t-hall-band: color-mix(in srgb, var(--wp-fg) 30%, var(--wp-bg));

  /* AND THE WALL INVERTS. More foreground means LIGHTER on a dark background and DARKER on a
     light one, so a cap tuned to be the brightest surface at night was the darkest by day and the
     wall read as advancing out of the floor. The cap catches the light in both themes; the FACE —
     the vertical surface you look at — is in shade in both. */
  --t-wall: color-mix(in srgb, var(--wp-fg) 34%, var(--wp-bg));
  --t-wall-cap: color-mix(in srgb, var(--wp-fg) 19%, var(--wp-bg));
  --t-face: color-mix(in srgb, var(--wp-fg) 46%, var(--wp-bg));
  --t-skirt: color-mix(in srgb, var(--wp-fg) 60%, var(--wp-bg));
  /* The building's mass has to be the DARKEST thing in either theme. At 34% of a near-black over
     white it came out mid-grey — brighter than several room floors — so the structure advanced
     instead of receding and the whole plan flattened. It is the single biggest reason the light
     theme read as washed out. */
  --t-mass: color-mix(in srgb, var(--wp-ink) 62%, var(--wp-bg));

  /* DAY. The sun is the fixture, so the pools are weaker and the SHADOWS carry the range: a hard
     shadow on a bright floor is the whole reason a daylit pixel scene reads as three-dimensional.
     Every one of these numbers is per-theme on purpose — the same alpha buys about four times the
     ink on a light substrate, so copying a night value across is how the shadow ends up either
     invisible or a black bar. */
  --l-lamp: var(--wp-h5);
  --l-0: 30%;
  --l-1: 17%;
  --l-2: 6%;
  --l-edge: color-mix(in srgb, #2b3348 15%, transparent);
  --l-unlit: color-mix(in srgb, #2b3348 30%, transparent);
  --l-ao: color-mix(in srgb, #232a3d 30%, transparent);
  --wp-drop: color-mix(in srgb, #232a3d 34%, transparent);
}

/* ── the window ────────────────────────────────────────────────────────────────────────────
   A bounded viewport with a building inside it that is deliberately bigger. The camera lives in
   the engine and arrives here as one transform on the stage, so every tile, sprite and route
   stays in exact proportion and nothing ever reflows. */

.wp-view {
  position: relative;
  flex: 1 1 auto;
  min-height: 180px;
  overflow: hidden;
  border: 2px solid var(--wp-line);
  background: color-mix(in srgb, var(--wp-ink) 30%, var(--wp-bg));
  cursor: grab;
}
.wp-view.is-dragging { cursor: grabbing; }
.wp-stagebox {
  position: absolute;
  left: 0;
  top: 0;
  transform-origin: 0 0;
  image-rendering: pixelated;
  will-change: transform;
}
.wp-map { position: absolute; inset: 0; display: block; }
.wp-world { display: none; }

/* Daylight crossing the building, and the dust hanging in it. The two slowest things on screen:
   a place with a time of day reads as a place even when nobody in it is moving. */
.wp-view::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 400;
  background: linear-gradient(105deg,
    transparent 0%,
    color-mix(in srgb, var(--wp-h3) 8%, transparent) 42%,
    transparent 74%);
  background-size: 260% 100%;
  animation: wp-daylight calc(var(--beat) * 25) ease-in-out infinite alternate;
}
@keyframes wp-daylight { from { background-position: 0% 0; } to { background-position: 100% 0; } }
.wp-view::before {
  content: "";
  position: absolute;
  inset: -40px;
  pointer-events: none;
  z-index: 390;
  opacity: .5;
  background-image:
    radial-gradient(circle, color-mix(in srgb, var(--wp-h3) 55%, transparent) 1px, transparent 1.6px),
    radial-gradient(circle, color-mix(in srgb, var(--wp-h3) 34%, transparent) 1px, transparent 1.6px);
  background-size: 140px 110px, 90px 170px;
  animation: wp-motes calc(var(--beat) * 18) linear infinite;
}
@keyframes wp-motes {
  from { background-position: 0 0, 40px 20px; }
  to { background-position: 90px -110px, -60px -170px; }
}

/* ── the board by the door ─────────────────────────────────────────────────────────────────
   One strip laid OVER the world, not a band beside it. The complaint that this reads as an ops
   dashboard was mostly volume of chrome: a stats bar above, a ten-item legend below, and a row
   of marks under every head. The legend is gone (the marks carry their own words when you point
   at them), and what is left is a line thin enough that the floor is the biggest thing on screen
   at any panel width. */

.wp-hud {
  position: absolute;
  z-index: 500;
  left: 0;
  right: 0;
  top: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 6px;
  font-size: 10px;
  background: var(--wp-chrome);
  border-bottom: 1px solid var(--wp-line);
  pointer-events: none;
  overflow: hidden;
  white-space: nowrap;
}
.wp-sign { display: inline-flex; align-items: baseline; gap: 5px; }
.wp-sign-name { font-weight: 700; letter-spacing: .12em; text-transform: uppercase; font-size: 10px; }
.wp-sign-sub { color: var(--wp-dim); font-size: 9px; }
.wp-chip { display: inline-flex; align-items: center; gap: 3px; color: var(--wp-dim); }
.wp-chip b { color: var(--wp-fg); }
.wp-spend { color: var(--wp-dim); }
.wp-clock { margin-left: auto; color: var(--wp-dim); font-size: 9px; }

/* ── the plan, in the corner ───────────────────────────────────────────────────────────────
   The camera takes the overview away; this gives it back in the one form that costs no space.
   Rooms as shapes, a dot per person in their pod's colour, and a box showing where you are
   looking — which is also how you steer, because clicking it takes the camera there. */

.wp-mini {
  position: absolute;
  z-index: 500;
  right: 5px;
  bottom: 5px;
  width: 96px;
  height: 72px;
  background: var(--wp-chrome);
  border: 1px solid var(--wp-line);
  opacity: .92;
  cursor: pointer;
}
.wp-mini svg { position: absolute; inset: 2px; width: calc(100% - 4px); height: calc(100% - 4px); }
.wp-mini .mm-bg { fill: color-mix(in srgb, var(--wp-fg) 10%, var(--wp-bg)); }
.wp-mini .mm-r { fill: color-mix(in srgb, var(--wp-fg) 26%, var(--wp-bg)); }
.wp-mini .mm-hall { fill: color-mix(in srgb, var(--wp-h5) 34%, var(--wp-bg)); }
.wp-mini .mm-r[data-lit="1"] { fill: color-mix(in srgb, var(--wp-h3) 52%, var(--wp-bg)); }
.wp-eye {
  position: absolute;
  border: 1px solid var(--wp-fg);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--wp-ink) 60%, transparent);
  pointer-events: none;
}
.wp-dots { position: absolute; inset: 2px; pointer-events: none; }
.wp-dots i {
  position: absolute;
  width: 3px;
  height: 3px;
  margin: -1px 0 0 -1px;
  background: var(--accent, var(--wp-h1));
}

/* ── the rooms ─────────────────────────────────────────────────────────────────────────────*/

/* A room with somebody in it is LIT — and the light is a POOL, banded on the tile grid, with the
   hue of what that room is DOING. "Where is everyone" and "who is in trouble" are both answered
   by the colour and shape of the light, before a single label resolves.

   data-voice is the engine's, and its values are the rail's own Attention names: the panel
   that prints the word ERROR in charts-red is the panel this room is lit by. */
.wp-pool {
  /* The mix is written HERE, not hoisted into a token on the container. A custom property
     substitutes its var()s at the element that DECLARES it, so a --l-hue declared on .wp resolved
     --l-tint from .wp and inherited that finished colour down — every room, including the one
     with a crashed agent in it, came out the same lamp yellow. Nesting the mix at the point of use
     is what lets an ancestor data-voice reach it. */
  fill: color-mix(in srgb,
    color-mix(in srgb, var(--l-tint) var(--l-mix), var(--l-lamp)) var(--l-a, 0%), transparent);
  opacity: 0;
  transition: opacity 520ms cubic-bezier(.33, 0, .2, 1), fill 700ms ease-in-out;
}
.wp-pool[data-l="0"] { --l-a: var(--l-0); }
.wp-pool[data-l="1"] { --l-a: var(--l-1); }
.wp-pool[data-l="2"] { --l-a: var(--l-2); }
/* The two outer bands are SHADE, not weaker light, and that is the whole difference between a
   ramp and a tint: three decreasing washes of one hue over one floor move the value by a handful
   of points and read as a coloured rectangle — which is exactly the flat category-fill this layer
   replaced. Light near the fixture, dark away from it, is what a light map actually does.
   They are also never faded: the far corner of a room is dark whether or not anybody is home. */
.wp-pool[data-l="3"] { fill: var(--l-edge); opacity: 1; }
.wp-pool[data-l="4"] { fill: var(--l-unlit); opacity: 1; }
.wp-rm[data-lit="1"] .wp-pool { opacity: 1; }
.wp-shut {
  fill: var(--wp-shut);
  opacity: 1;
  transition: opacity 520ms cubic-bezier(.33, 0, .2, 1);
}
.wp-rm[data-lit="1"] .wp-shut { opacity: 0; }

/* What each state does to the light. Only the states that WANT something take the room's colour
   over; work in progress keeps the lamp warm, or a floor of eleven busy agents would be eleven
   blue rooms and the one that needs a person would not stand out at all. */
.wp-lit[data-voice="error"] { --l-tint: var(--vscode-charts-red, #f14c4c); --l-mix: 100%; }
.wp-lit[data-voice="asked"] { --l-tint: var(--vscode-charts-blue, #4daafc); --l-mix: 82%; }
.wp-lit[data-voice="held"] { --l-tint: var(--vscode-charts-yellow, #d7ba7d); --l-mix: 55%; }
.wp-lit[data-voice="finished"] { --l-tint: var(--vscode-charts-green, #89d185); --l-mix: 46%; }

/* And the fixture itself differs by trade: a machine room burns colder than a library. The old
   flat wash carried this and it was worth keeping — it is most of what tells two lit rooms apart
   when everyone in both of them is simply working. */
/* THE LIGHT BREATHES WITH THE WORK, and that is the point of tying it to the taxonomy at all: a
   static colour says what state a room is in, a rhythm says the room is LIVE. Both are on the one
   beat everything else in this building runs on, and both are eased — a light that steps linearly
   between two levels reads as a switch being flicked, not as a lamp.

   ERROR takes the stamp's own alarm tempo, so the placard over the head and the light in the room
   pulse together rather than beating against each other. Everything else takes a slow four-beat
   breath, shallow enough that a floor of eleven working agents is alive rather than strobing. */
.wp-lit[data-lit="1"] .wp-pool[data-l="0"],
.wp-lit[data-lit="1"] .wp-pool[data-l="1"] {
  animation: wp-breathe calc(var(--beat) * 4) cubic-bezier(.45, .05, .55, .95) var(--d, 0s) infinite;
}
/* fill-opacity, NOT opacity: the element's own opacity is what fades a room in when somebody
   walks into it, and an animation on the same property wins outright over the declaration, so the
   room stopped fading and started snapping on. The two multiply. */
@keyframes wp-breathe {
  0%, 100% { fill-opacity: .84; }
  50% { fill-opacity: 1; }
}
.wp-lit[data-voice="error"] .wp-pool[data-l="0"],
.wp-lit[data-voice="error"] .wp-pool[data-l="1"],
.wp-lit[data-voice="error"] .wp-pool[data-l="2"] {
  animation: wp-alarm calc(var(--beat) * 2 / 3) ease-in-out infinite;
}
@keyframes wp-alarm {
  0%, 100% { fill-opacity: .55; }
  50% { fill-opacity: 1; }
}

/* The passage burns a cooler, flatter light than any room off it: overheads in a corridor, not
   lamps on a desk. It is also the one light in the building that is never switched off. */
.wp-lit[data-kind="hall"] { --l-lamp: color-mix(in srgb, var(--wp-h1) 34%, var(--wp-fg)); }
.wp-lit[data-kind="machine"] { --l-lamp: color-mix(in srgb, var(--wp-h1) 62%, var(--wp-h3)); }
.wp-lit[data-kind="signals"] { --l-lamp: color-mix(in srgb, var(--wp-h6) 58%, var(--wp-h3)); }
.wp-lit[data-kind="stacks"] { --l-lamp: color-mix(in srgb, var(--wp-h2) 40%, var(--wp-h3)); }
.wp-lit[data-kind="boardroom"] { --l-lamp: color-mix(in srgb, var(--wp-h5) 48%, var(--wp-h3)); }
.wp-lit[data-kind="drafting"] { --l-lamp: color-mix(in srgb, var(--wp-h4) 32%, var(--wp-h3)); }

/* Every wall in the building, casting into the floor beside it. ONE path for the whole world, so
   the overlaps at a corner paint once rather than stacking into a black notch. */
.wp-ao { fill: var(--l-ao); pointer-events: none; }
/* A prop's own silhouette, lying where the light is not.
   NOT .wp-cast — that class is the ACTORS container the engine re-binds every refresh, and a
   shadow wearing it appears earlier in the document, so querySelector('.wp-cast') found a desk's
   shadow instead of the cast. */
.wp-drop { pointer-events: none; }

/* The rug is bordered by a stroke rather than by its own tile: a pattern repeats the border in
   every cell and the floor comes out a chequerboard, which is louder than the carpet it replaced. */
.wp-rug { fill: none; stroke: var(--t-rug-hi); stroke-width: 1; }
.wp-struct { fill: var(--t-wall); }
.wp-core { animation: wp-core calc(var(--beat) * 1.5) ease-in-out infinite; transform-origin: center; }
@keyframes wp-core { 0%, 100% { opacity: .72; } 50% { opacity: 1; } }

/* ── the building is ALIVE when nobody is working ──────────────────────────────────────────
   Every one of these is an overlay on a prop that is already there, never a redraw of it, and
   every duration is a ratio of the one beat. The point is not decoration: a floor where a screen
   flickers, a kettle steams, a fan turns and the plants move is a place somebody LIVES in, and it
   is the difference between a still picture of a workplace and a workplace. */

.wp-lv { pointer-events: none; }
.wp-lv-screen {
  opacity: .55;
  animation: wp-flick calc(var(--beat) * 2) steps(1, end) infinite;
  animation-delay: var(--d, 0s);
}
@keyframes wp-flick {
  0%, 22% { opacity: .30; }
  23%, 47% { opacity: .62; }
  48%, 51% { opacity: .18; }
  52%, 78% { opacity: .55; }
  79%, 100% { opacity: .38; }
}
.wp-lv-steam {
  opacity: 0;
  transform-box: fill-box;
  transform-origin: 50% 100%;
  animation: wp-steam calc(var(--beat) * 2) cubic-bezier(.16, .72, .38, 1) infinite;
  animation-delay: var(--d, 0s);
}
@keyframes wp-steam {
  0% { opacity: 0; transform: translateY(2px) scale(.6); }
  30% { opacity: .7; }
  100% { opacity: 0; transform: translateY(-9px) scale(1.15); }
}
.wp-lv-lamp {
  opacity: .3;
  animation: wp-lamp calc(var(--beat) * 4) cubic-bezier(.45, .05, .55, .95) infinite;
  animation-delay: var(--d, 0s);
}
@keyframes wp-lamp { 0%, 100% { opacity: .22; } 50% { opacity: .46; } }
.wp-lv-sway {
  transform-box: fill-box;
  transform-origin: 50% 100%;
  animation: wp-sway calc(var(--beat) * 3) cubic-bezier(.37, 0, .63, 1) infinite;
  animation-delay: var(--d, 0s);
}
@keyframes wp-sway {
  0%, 100% { transform: rotate(-1.6deg); }
  50% { transform: rotate(1.6deg); }
}
.wp-lv-fan {
  transform-box: fill-box;
  transform-origin: 50% 50%;
  animation: wp-fan calc(var(--beat) / 2) linear infinite;
}
@keyframes wp-fan { to { transform: rotate(360deg); } }

/* A door is something that HAPPENS. The leaf is shut until the engine sees somebody within a
   tile and a half of it, which makes walking between rooms legible from across the building. */
.wp-leaf {
  transform-box: fill-box;
  transform-origin: 0% 50%;
  transition: transform 260ms cubic-bezier(.34, 1.4, .64, 1);
}
.wp-leaf.is-open { transform: scaleX(.18); }

/* Labels hold a constant SCREEN size while the world zooms under them — the standard answer for
   anything that is read rather than looked at, and the reason the same 132px bubble does not turn
   into a 264px banner the moment the camera moves in. The world scales; the words do not. */
.wp-plaque {
  position: absolute;
  z-index: 300;
  transform: scale(var(--inv, 1));
  transform-origin: 0 0;
  font-size: 7px;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: .04em;
  text-transform: uppercase;
  font-weight: 700;
  color: var(--wp-bg);
  background: var(--wp-plate);
  padding: 1px 4px;
  box-shadow: 1px 1px 0 var(--wp-ink);
  white-space: nowrap;
  pointer-events: none;
}

/* ── a character ───────────────────────────────────────────────────────────────────────────
   The element is a POINT — a zero-sized anchor standing on a tile — and everything hangs off it.
   That is what lets the engine move a person with one transform, and what stops the text around
   somebody from deciding where they are allowed to be. */

.wp-cast { position: absolute; inset: 0; }
.wp-actor {
  position: absolute;
  left: 0;
  top: 0;
  width: 0;
  height: 0;
  z-index: 100;
  cursor: pointer;
  --c-shirt: var(--accent, var(--wp-h1));
  --c-badge: color-mix(in srgb, var(--accent, var(--wp-h1)) 42%, var(--wp-ink));
  --c-eye: #1b1723;
  --c-mouth: color-mix(in srgb, var(--c-skin, #e0a877) 62%, var(--wp-ink));
  --c-ghost: color-mix(in srgb, var(--wp-fg) 34%, var(--wp-bg));
  --c-ghost-ink: color-mix(in srgb, var(--wp-fg) 52%, var(--wp-bg));
}

.wp-body {
  position: absolute;
  left: 0;
  bottom: 0;
  width: 36px;
  height: 54px;
  transform: translateX(-50%) rotate(var(--lean, 0deg));
  transform-origin: 50% 100%;
}
.wp-body .wp-sprite { position: absolute; left: 0; bottom: 0; }
.wp-actor.face-left .wp-body .wp-sprite { transform: scaleX(-1); }

/* The head of the company stands taller. The cheapest true thing the picture can say about the
   one agent everybody else reports to, and it needs no label to say it. */
.wp-actor.is-brain .wp-body { transform: translateX(-50%) scale(1.3) rotate(var(--lean, 0deg)); }
.wp-actor.is-brain::before {
  content: "";
  position: absolute;
  left: -22px;
  bottom: -5px;
  width: 44px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid color-mix(in srgb, var(--wp-h3) 76%, transparent);
  animation: wp-crown calc(var(--beat) * 2) ease-in-out var(--d, 0s) infinite;
}
@keyframes wp-crown {
  0%, 100% { opacity: .35; transform: scale(.9); }
  50% { opacity: .9; transform: scale(1.08); }
}

.wp-shade {
  /* A border-radius 50% ellipse is a SOFT shape in a scene made entirely of hard ones, and at
     sprite scale it read as a smudge rather than as contact with the floor. Stepped in threes it
     is a pixel shape.
     It also has to come OUT from under the body: at 26px under a 36px sprite it was entirely
     hidden behind the character it belonged to, which is why the floor still looked like a floor
     nobody was standing on. Thrown down and to the right, the same way every wall and every prop
     in this building throws. */
  position: absolute;
  left: -8px;
  bottom: -5px;
  width: 32px;
  height: 8px;
  background: var(--wp-drop);
  clip-path: polygon(
    6px 0, 24px 0, 24px 2px, 28px 2px, 28px 6px, 24px 6px, 24px 8px,
    6px 8px, 6px 6px, 2px 6px, 2px 2px, 6px 2px);
}
.wp-actor.is-brain .wp-shade { width: 40px; left: -12px; }

/* Two poses for standing, two for walking, in one element. Which pair shows is the engine's call:
   the walk frames are flipped on DISTANCE covered, not on a clock. */
.wp-f { opacity: 0; }
.wp-stand .wp-f0 { opacity: 1; }
.wp-actor[data-status="running"] .wp-stand .wp-f0 { animation: wp-fa calc(var(--beat) / 2) steps(1, end) var(--d, 0s) infinite; }
.wp-actor[data-status="running"] .wp-stand .wp-f1 { animation: wp-fb calc(var(--beat) / 2) steps(1, end) var(--d, 0s) infinite; }
@keyframes wp-fa { 0%, 62% { opacity: 1; } 63%, 100% { opacity: 0; } }
@keyframes wp-fb { 0%, 62% { opacity: 0; } 63%, 100% { opacity: 1; } }
.wp-walk { visibility: hidden; }
.wp-actor.is-walking .wp-stand { visibility: hidden; }
.wp-actor.is-walking .wp-walk { visibility: visible; }
.wp-actor.is-walking .wp-walk .wp-f1 { opacity: 1; }
.wp-actor.is-walking.wp-fA .wp-walk .wp-f1 { opacity: 0; }
.wp-actor.is-walking.wp-fA .wp-walk .wp-f0 { opacity: 1; }
/* A body off the ground throws a smaller, tighter shadow. */
.wp-actor.is-walking .wp-shade { transform: scaleX(.82); }

.wp-tag {
  position: absolute;
  left: 0;
  top: 3px;
  transform: translateX(-50%);
  display: block;
  /* Seats are three tiles apart, i.e. seventy-two world pixels. A plate allowed seventy-six was
     wider than the space between two people by construction, so two neighbours' names overlapped
     before anything else in the scene did. */
  max-width: 66px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 7px;
  line-height: 1.35;
  letter-spacing: .01em;
  white-space: nowrap;
  color: var(--wp-fg);
  /* Opaque, not translucent. Two characters standing a tile apart WILL overlap — that is what a
     crowd is — so the one in front has to cover the one behind cleanly. */
  background: color-mix(in srgb, var(--wp-bg) 92%, var(--wp-fg));
  padding: 0 3px;
  border-bottom: 1px solid var(--accent, var(--wp-h1));
  pointer-events: none;
}
.wp-actor:hover .wp-tag,
.wp-actor:focus-visible .wp-tag { max-width: none; overflow: visible; }
.wp-tag i { font-style: normal; color: var(--wp-dim); margin-left: 3px; }
.wp-actor.is-brain .wp-tag { font-weight: 700; border-bottom-color: var(--wp-h3); }

/* What this one can DO, read off its own definition file.
   Six marks at twelve CSS pixels — which the old whole-building fit then HALVED to six — was
   measured as illegible, and illegible is not ergonomic. So it is the three that make this agent
   different from everybody else, at fourteen pixels, on a camera that no longer shrinks the world
   to fit the panel. Hung BESIDE the body rather than under the name: as a row it was half again
   the character's own width and the loudest thing on them, which is the chrome-crowds-the-sprite
   complaint in miniature. The full set, with its words, is one hover away. */
.wp-can {
  /* TOOLS ON THE DESK, not a column of chips.
     Three framed squares stacked beside a 36x54 character measured 32px each on screen — ninety-six
     pixels of interface against fifty-four pixels of person, so the loudest object in a room full
     of people was a stack of icons. Laid flat at the feet, with the plate taken away and the same
     hard pixel shadow every sign in this building throws, they stop being interface and become
     things lying on the desk. Same size, a quarter of the weight. */
  position: absolute;
  left: 0;
  top: var(--belt, 17px);
  transform: translateX(-50%);
  display: flex;
  gap: 2px;
  /* LIVE. It carried a title and a pointer cursor while pointer-events said none, so it offered
     an affordance it could never honour — the tooltip never fired and the cursor never changed.
     A click on one now reaches the same handler a click on the person does. */
  pointer-events: auto;
}
/* The back rank has no nameplate under its boots, so its belt sits right at them.
   Tried and REJECTED: lifting it above the head, the way the nameplate is lifted. It clears the
   front rank's placard and it reads as three icons floating unattached over somebody — tools that
   have stopped belonging to anyone. The two measured overlaps that remain are a back-rank belt
   under a front-rank stamp, where depth ordering already draws the stamp on top; that reads as one
   person standing in front of another, which is what it is. */
.wp-actor[data-label="up"] .wp-can { --belt: 2px; }
.wp-fac {
  --mark: color-mix(in srgb, var(--accent, var(--wp-h1)) 34%, #f4f1ff);
  font-style: normal;
  display: inline-flex;
  /* Keeps the mark at sixteen world pixels, i.e. the thirty-two on screen an earlier round
     measured as the point where these stop being illegible. Dropping the plate must not quietly
     shrink them back. */
  padding: 1px;
  filter: drop-shadow(1px 1px 0 var(--wp-ink)) drop-shadow(-1px 0 0 var(--wp-ink))
    drop-shadow(0 -1px 0 var(--wp-ink));
  transition: transform 150ms cubic-bezier(.34, 1.56, .64, 1);
}
.wp-fac:hover,
.wp-fac:focus-visible {
  --mark: #fff;
  transform: translateY(-4px) scale(1.15);
  outline: none;
}
.wp-fac:active { transform: translateY(-1px); }
.wp-fac svg { display: block; }
.wp-actor[data-status="foreign"] .wp-fac,
.wp-actor[data-status="done"] .wp-fac { background: color-mix(in srgb, var(--wp-dim) 70%, var(--wp-bg)); }

/* The whole kit with its words, for a reader who points at somebody. Display NONE at rest, not
   opacity zero: an invisible element that still occupies layout is how a label-collision check
   once reported four collisions nobody could see. */
.wp-kit { display: none; }
.wp-actor:hover .wp-kit,
.wp-actor:focus-visible .wp-kit {
  display: block;
  position: absolute;
  left: 10px;
  top: 34px;
  z-index: 950;
  padding: 3px 5px;
  background: var(--wp-chrome);
  border: 1px solid var(--wp-line);
  box-shadow: 2px 2px 0 var(--wp-ink);
  font-size: 8px;
  line-height: 1.5;
  color: var(--wp-fg);
  white-space: nowrap;
  pointer-events: none;
}
.wp-kit i { font-style: normal; display: flex; align-items: center; gap: 4px; --mark: var(--wp-fg); }

/* The line above their head.
   "A lot of transparency" was the ask, and the answer used to be opacity zero until you hovered
   the exact right character — the richest information in the product, invisible unless you knew
   where to point. It is on at rest now. What makes that possible is the camera: eight people on
   screen instead of twenty-five, so the engine can hand out three levels of bubble and drop any
   that would collide with another bubble or with somebody's name. */
.wp-say {
  position: absolute;
  left: 0;
  bottom: 66px;
  transform: translate(-50%, 3px) scale(var(--inv, 1));
  transform-origin: 50% 100%;
  width: 132px;
  padding: 2px 5px;
  font-size: 9px;
  line-height: 1.3;
  color: var(--wp-ink);
  background: var(--wp-paper);
  box-shadow: 2px 2px 0 var(--wp-ink);
  opacity: 0;
  pointer-events: none;
  transition: opacity 220ms ease, transform 220ms ease;
  z-index: 5;
}
.wp-say b { font-weight: 400; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wp-say::after {
  content: "";
  position: absolute;
  left: 50%;
  bottom: -4px;
  width: 4px;
  height: 4px;
  margin-left: -2px;
  background: var(--wp-paper);
}
.wp-actor.is-saying .wp-say { opacity: 1; transform: translate(-50%, 0) scale(var(--inv, 1)); }
.wp-actor:hover, .wp-actor:focus-visible { z-index: 900 !important; }

/* The back rank wears its name over its head: three tiles is room for two people and not enough
   for two people plus their labels, and the front body would otherwise be drawn over the back
   body's name. */
.wp-actor[data-label="up"] .wp-tag { top: auto; bottom: 58px; }
.wp-actor[data-label="up"] .wp-say { bottom: 96px; }
.wp-actor[data-label="up"] .wp-mark { bottom: 84px; }
.wp-actor[data-label="up"] .wp-kit { top: auto; bottom: 100px; }

.wp-mark {
  position: absolute;
  left: 0;
  bottom: 54px;
  transform: translateX(-50%) scale(.5);
  transform-origin: 50% 100%;
  pointer-events: none;
}
.wp-zzz { position: absolute; left: 22px; bottom: 44px; --mark: var(--wp-dim); }

/* Somebody has come over to say something. Both of them stop and turn to each other — a message
   that lands with nobody reacting is a note flying past a person rather than to one. */
.wp-actor.is-talking .wp-body { animation: wp-talk 480ms ease-in-out infinite; }
@keyframes wp-talk { 0%, 100% { transform: translateX(-50%) translateY(0); } 50% { transform: translateX(-50%) translateY(-1px); } }
.wp-actor.has-post .wp-shade { background: color-mix(in srgb, var(--wp-h3) 60%, transparent); }

/* A worker the registry says has stopped stops. Scoped to the sprite, never to the whole actor:
   an ancestor opacity composites the nameplate and the stamp with it, and a greyed-out ERROR is
   the one word that must never be hard to read. */
.wp-actor[data-stalled="1"] .wp-body,
.wp-actor[data-status="done"] .wp-body,
.wp-actor[data-status="foreign"] .wp-body { opacity: calc(1 - var(--idle, 0) * .38); }
.wp-actor[data-status="error"] .wp-body { filter: drop-shadow(0 0 4px color-mix(in srgb, var(--wp-bad) 70%, transparent)); }

.wp-proto { position: absolute; visibility: hidden; pointer-events: none; }

${STAMP_CSS}

/* ── reduced motion ────────────────────────────────────────────────────────────────────────
   Everything above degrades to a still building with everybody standing at their own desk. The
   engine never starts its clock, so nothing walks and nothing pulses; the camera holds where it
   was put, and the speech stays ON, because a reader who has turned motion off still needs to
   know what the team is doing. */
@media (prefers-reduced-motion: reduce) {
  .wp-view::after,
  .wp-view::before,
  .wp-core,
  .wp-lv-screen,
  .wp-lv-steam,
  .wp-lv-lamp,
  .wp-lv-sway,
  .wp-lv-fan,
  .wp-actor.is-brain::before,
  .wp-actor .wp-stand .wp-f0,
  .wp-actor .wp-stand .wp-f1,
  .wp-actor.is-talking .wp-body { animation: none !important; }
  .wp-pool, .wp-shut, .wp-leaf { transition: none; }
  .wp-lit .wp-pool { animation: none !important; }
  .wp-stand .wp-f0 { opacity: 1; }
  .wp-stand .wp-f1 { opacity: 0; }
  .wp-lv-steam { opacity: 0; }
}
`;
