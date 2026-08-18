/** The look of the place.
 *
 *  Two rules run through all of it.
 *
 *  COLOUR follows the editor. Walls, floors, light and paper are mixed from `--vscode-*` tokens,
 *  so the building is dim and warm in a dark theme and bright and cool in a light one without a
 *  second palette existing anywhere. Only the people keep literal tones — a person tinted by the
 *  editor background stops looking like a person.
 *
 *  MOTION follows one beat. Every ambient animation's duration is an integer ratio of `--beat`,
 *  so a room full of sprites moves as one thing rather than as nine independent loops. The only
 *  duration that is not a ratio of the beat is travel, and that is deliberate: walking between
 *  rooms is an EVENT, and an event that lands on the ambient beat is invisible.
 */

export const STYLE = String.raw`
*, *::before, *::after { box-sizing: border-box; }
/* A worker is a <figure> and a nameplate a <figcaption> — the right elements, and both carry a
   UA margin (1em 40px) that silently padded every person in the building by 80px of width. */
html, body, figure, figcaption, header, footer, p { margin: 0; padding: 0; }

body {
  font-family: var(--vscode-font-family, system-ui, sans-serif);
  color: var(--vscode-foreground, #ccc);
  background: var(--vscode-editor-background, #1e1e1e);
  font-size: 12px;
  -webkit-font-smoothing: antialiased;
}

.wp {
  /* ── tempo ──────────────────────────────────────────────────────────────────────────────
     One beat. Everything ambient is a ratio of it; change this line and the whole workplace
     speeds up or slows down together. */
  --beat: 2.4s;
  --gait: calc(var(--beat) / 2);
  --travel: 820ms;
  --ease-walk: cubic-bezier(.34, .02, .2, 1);
  --ease-settle: cubic-bezier(.22, 1, .32, 1);

  /* ── world ──────────────────────────────────────────────────────────────────────────────
     Mixed from the theme so one set of rules serves every colour scheme. */
  --wp-bg: var(--vscode-editor-background, #1e1e1e);
  --wp-fg: var(--vscode-editor-foreground, #d4d4d4);
  --wp-dim: var(--vscode-descriptionForeground, #9a9a9a);
  --wp-ink: #14101c;
  --wp-tint: #e8e4f0;

  --wp-wall: color-mix(in srgb, var(--wp-fg) 7%, var(--wp-bg));
  --wp-wall-lit: color-mix(in srgb, var(--wp-fg) 13%, var(--wp-bg));
  --wp-line: color-mix(in srgb, var(--wp-fg) 26%, var(--wp-bg));
  --wp-floor: color-mix(in srgb, var(--wp-fg) 19%, var(--wp-bg));
  --wp-floor-line: color-mix(in srgb, var(--wp-fg) 30%, var(--wp-bg));
  --wp-lamp: color-mix(in srgb, var(--wp-h3) 22%, transparent);
  --wp-slab: color-mix(in srgb, var(--wp-fg) 34%, var(--wp-bg));
  /* A plate that carries BACKGROUND-coloured text, so it has to be light enough to read against
     the background — the decorative slab above is not (measured 2.38:1 dark, 1.89:1 light). */
  --wp-plate: color-mix(in srgb, var(--wp-fg) 82%, var(--wp-bg));

  --wp-metal: color-mix(in srgb, var(--wp-fg) 46%, var(--wp-bg));
  --wp-wood: color-mix(in srgb, #8a5a2b 74%, var(--wp-bg));
  --wp-door: color-mix(in srgb, #8a5a2b 44%, var(--wp-bg));
  --wp-screen: color-mix(in srgb, #0b2a33 78%, var(--wp-bg));
  --wp-paper: color-mix(in srgb, #f3efe4 82%, var(--wp-bg));
  --wp-glass: color-mix(in srgb, #9fd6e0 46%, var(--wp-bg));
  --wp-cushion: color-mix(in srgb, #d9c9a8 66%, var(--wp-bg));
  --wp-cloud: color-mix(in srgb, #ffffff 62%, transparent);
  --wp-leaf: var(--wp-h4);
  --wp-brass: #d2a54a;
  --wp-exit: var(--wp-h4);
  --wp-led: var(--wp-h4);
  --wp-led-dim: color-mix(in srgb, var(--wp-h4) 26%, var(--wp-ink));
  --wp-glow: var(--wp-h3);
  --wp-far: color-mix(in srgb, var(--wp-ink) 58%, var(--wp-h1));
  --wp-disc: color-mix(in srgb, var(--wp-h3) 72%, #ffffff);

  /* The six pod hues, from the theme's own chart palette. */
  --wp-h1: var(--vscode-charts-blue, #4f9cf5);
  --wp-h2: var(--vscode-charts-purple, #b180d7);
  --wp-h3: var(--vscode-charts-yellow, #e2c08d);
  --wp-h4: var(--vscode-charts-green, #6fc28b);
  --wp-h5: var(--vscode-charts-orange, #e8925a);
  /* Two more mixed from the palette rather than reaching for red, which is spoken for. */
  --wp-h6: color-mix(in srgb, var(--wp-h1) 55%, var(--wp-h4));
  --wp-h7: color-mix(in srgb, var(--wp-h2) 62%, var(--vscode-charts-red, #e06c75));

  --wp-ok: var(--vscode-charts-green, #6fc28b);
  --wp-bad: var(--vscode-errorForeground, #e06c75);
  --wp-bubble-bg: color-mix(in srgb, var(--wp-fg) 90%, var(--wp-bg));
  --wp-bubble-fg: var(--wp-bg);

  --w-lead: 122px;
  --w-rep: 104px;
  --w-mini: 92px;

  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px 16px;
  min-width: 320px;
}

/* A light theme needs a softer ink and the tint mixes the other way, or every report's shirt
   washes out to nothing. */
body.vscode-light .wp,
body.vscode-high-contrast-light .wp {
  --wp-ink: #2c2438;
  --wp-tint: #2f2a3a;
  /* An empty room must be the QUIETEST thing on screen, which on a light theme means greyer than
     its neighbours — not whiter. Lighting it up was exactly backwards: the dark room reading was
     inverted and "where is everyone" answered wrong. */
  --wp-wall: color-mix(in srgb, var(--wp-fg) 15%, var(--wp-bg));
  --wp-wall-lit: color-mix(in srgb, var(--wp-h3) 14%, var(--wp-bg));
  --wp-floor: color-mix(in srgb, var(--wp-fg) 22%, var(--wp-bg));
  --wp-floor-line: color-mix(in srgb, var(--wp-fg) 34%, var(--wp-bg));
  --wp-lamp: color-mix(in srgb, var(--wp-h3) 30%, transparent);
  --wp-bubble-bg: color-mix(in srgb, var(--wp-fg) 84%, var(--wp-bg));
}

/* ── the board by the door ───────────────────────────────────────────────────────────────── */

.wp-hud {
  display: flex;
  align-items: center;
  gap: 10px 16px;
  flex-wrap: wrap;
}

.wp-sign {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 3px 9px;
  background: var(--wp-plate);
  color: var(--wp-bg);
  border: 1px solid var(--wp-ink);
  box-shadow: 2px 2px 0 0 var(--wp-ink);
}
.wp-sign-name { font-weight: 700; letter-spacing: .18em; font-size: 11px; text-transform: uppercase; }
.wp-sign-sub { font-size: 10px; opacity: .78; }

.wp-tally { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.wp-chip { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--wp-dim); }
.wp-chip b { color: var(--wp-fg); font-weight: 600; font-variant-numeric: tabular-nums; }
.wp-chip svg { display: block; }
.wp-clock { margin-left: auto; font-size: 10px; color: var(--wp-dim); font-variant-numeric: tabular-nums; }

/* ── the scene: a building, and the outdoors beside it ───────────────────────────────────── */

.wp-scene {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(158px, .26fr);
  align-items: stretch;
  border: 2px solid var(--wp-ink);
  background: var(--wp-bg);
  overflow: hidden;
}

.wp-building { display: flex; flex-direction: column; min-width: 0; }

.wp-roof {
  height: 12px;
  background:
    repeating-linear-gradient(90deg, var(--wp-slab) 0 7px, color-mix(in srgb, var(--wp-slab) 70%, var(--wp-ink)) 7px 8px);
  border-bottom: 2px solid var(--wp-ink);
}

.wp-floor {
  display: grid;
  grid-template-columns: var(--cols, 1fr);
  grid-template-rows: 66px auto;
  min-width: 0;
  border-bottom: 2px solid var(--wp-ink);
}
.wp-floor:last-of-type { border-bottom: 0; }
/* An empty storey keeps its rooms and its shape, at a fraction of the height: with a small team
   the vacant floors were most of the canvas while the people crammed into a corner of it. The
   props scale with it rather than being cropped, so a dark room still reads as that room. */
.wp-floor[data-vacant="1"] { grid-template-rows: 30px auto; }
.wp-floor[data-vacant="1"] .wp-prop { transform: scale(.62); transform-origin: center bottom; }
.wp-floor[data-vacant="1"] .wp-sign { opacity: .72; }

.wp-base {
  height: 10px;
  background: var(--wp-slab);
  border-top: 2px solid var(--wp-ink);
}

/* ── a room ──────────────────────────────────────────────────────────────────────────────── */

.wp-room {
  --heads: 0;
  position: relative;
  min-width: 0;
  display: grid;
  grid-row: 1 / -1;
  /* Rows come from the floor, so every room on a storey puts its floorboards at the same height
     and the building has continuous storeys instead of a stepped skyline of panels. */
  grid-template-rows: subgrid;
  background: var(--wp-wall);
  border-right: 2px solid var(--wp-ink);
}
.wp-floor > .wp-room:last-child { border-right: 0; }

/* Not a zone: the stairwell that ties the storeys together. */
.wp-lobby { background: color-mix(in srgb, var(--wp-fg) 12%, var(--wp-bg)); }
.wp-lobby .wp-prop { opacity: .42; }

/* Occupied rooms are LIT. An empty room going dark is the cheapest possible answer to "where is
   everyone" — you see the shape of the team before you read one name. */
.wp-room[data-lit="1"] {
  background:
    radial-gradient(118% 84% at 50% -8%, var(--wp-lamp) 0%, transparent 64%),
    var(--wp-wall-lit);
}

.wp-wall {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  overflow: hidden;
  margin-bottom: -6px;
  min-width: 0;
}
.wp-prop { opacity: .5; flex: none; }
.wp-room[data-lit="1"] .wp-prop { opacity: 1; }
/* One breath per busy room, on twice the beat: the building is alive, not twitching. */
.wp-room[data-busy="1"] .wp-prop { animation: wp-breathe calc(var(--beat) * 2) ease-in-out infinite; }

.wp-plaque {
  position: absolute;
  top: 4px;
  left: 6px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 9px;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: var(--wp-dim);
  background: color-mix(in srgb, var(--wp-bg) 72%, transparent);
  padding: 1px 4px;
  z-index: 3;
  pointer-events: none;
}
.wp-room[data-lit="1"] .wp-plaque { color: var(--wp-fg); }
.wp-plaque b { font-weight: 700; font-size: 10px; letter-spacing: 0; color: var(--wp-fg); }

/* The floor people stand on. Boards drawn at whole pixels so the surface stays pixel art. */
.wp-deck {
  position: relative;
  z-index: 2;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: center;
  gap: 5px;
  padding: 4px 6px 13px;
  background:
    linear-gradient(var(--wp-ink), var(--wp-ink)) left bottom 11px / 100% 2px no-repeat,
    repeating-linear-gradient(90deg, var(--wp-floor) 0 11px, var(--wp-floor-line) 11px 12px)
      left bottom / 100% 11px no-repeat;
}

/* ── a pod: a lead and the people they sent out ──────────────────────────────────────────── */

.wp-pod {
  --accent: var(--wp-h1);
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 2px;
  padding: 0 5px 6px;
  background:
    linear-gradient(
      180deg,
      transparent 0%,
      color-mix(in srgb, var(--accent) 9%, transparent) 62%,
      color-mix(in srgb, var(--accent) 26%, transparent) 100%
    );
  box-shadow:
    inset 0 -3px 0 0 var(--accent),
    inset 2px 0 0 -1px color-mix(in srgb, var(--accent) 55%, transparent),
    inset -2px 0 0 -1px color-mix(in srgb, var(--accent) 55%, transparent);
  max-width: 100%;
}
/* When a room is too narrow for its teams they stack, and a platform on the upper row is no
   longer sitting on the floorboards — so every platform carries its own base. A pod reads as a
   thing standing on something at any height, which is what it is. */
.wp-pod::after {
  content: "";
  position: absolute;
  left: 0; right: 0; bottom: -2px;
  height: 2px;
  background: color-mix(in srgb, var(--wp-ink) 50%, transparent);
}

/* A visiting member's platform is the same object, smaller — its colour is the whole message:
   that person belongs to a pod somewhere else in the building. */
.wp-pod[data-visiting="1"] {
  background: linear-gradient(180deg, transparent 55%, color-mix(in srgb, var(--accent) 18%, transparent) 100%);
  box-shadow: inset 0 -2px 0 0 color-mix(in srgb, var(--accent) 75%, transparent);
}

/* ── a worker ────────────────────────────────────────────────────────────────────────────── */

.wp-worker {
  --idle: 0;
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  flex: 0 0 var(--w-rep);
  /* Definite px, and it has to be max-width, not width: a flex item offers its content's
     max-content size to the container unless a px maximum clamps it, which is how one long
     activity phrase used to make its pod 70% wider than the people standing in it. */
  max-width: var(--w-rep);
  min-width: 0;
  cursor: pointer;
  filter: saturate(calc(1 - .72 * var(--idle))) opacity(calc(1 - .3 * var(--idle)));
}
.wp-worker[data-depth="0"] { flex: 0 0 var(--w-lead); max-width: var(--w-lead); }
.wp-worker[data-depth="2"], .wp-worker[data-depth="3"] { flex: 0 0 var(--w-mini); max-width: var(--w-mini); }
/* Scoped to the sprite, not the whole worker: filtering the figure faded the NAME PLATE too,
   down to ~4.24:1 on real pixels — a contrast a computed-style check cannot even see. Someone who
   has finished should look finished; their name still has to be readable.

   The plate then carried an 'opacity: .82', which is the same mistake one level down: opacity
   composites the TEXT along with the plate, onto whatever room art is behind a translucent
   background, and visual-critic measured the result at 3.81-4.05:1 across four samples in three
   rooms. At 10px almost every pixel of a glyph is anti-aliased, so nominal contrast is not what
   is read — see plateContrast.test.ts, which holds the whole stack to a floor with headroom.
   Finished is already said twice over, by the faded sprite and by the dim status mark; the name
   does not have to whisper it a third time. */
.wp-worker[data-status="done"] .wp-stage { filter: grayscale(.6) opacity(.58); }
.wp-worker[data-status="foreign"] { filter: opacity(.72); }
.wp-worker:hover { filter: none; }
.wp-worker:focus-visible { outline: 1px solid var(--vscode-focusBorder, #4f9cf5); outline-offset: 2px; }
/* A worker carries role="button" and opens its conversation, and the pointer said otherwise.
   No screenshot can show this — the cursor property puts nothing in the frame — so it survived
   pass until a critic read the computed style instead of looking. */
.wp-worker { cursor: pointer; }

/* Activity is the liveliest thing here — it changes about once a second while an agent works —
   so it is the biggest text in the room, above the head, not a caption under a name. */
.wp-bubble {
  position: relative;
  max-width: 100%;
  margin-bottom: 5px;
  padding: 2px 4px;
  font-size: 10.5px;
  line-height: 1.2;
  text-align: center;
  color: var(--wp-bubble-fg);
  background: var(--wp-bubble-bg);
  border: 1px solid var(--wp-ink);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  /* Ellipsis, matching the name plates: a line that simply stops mid-word reads as a rendering
     fault rather than as text that carries on. */
  text-overflow: ellipsis;
  overflow: hidden;
  overflow-wrap: anywhere;
}
.wp-bubble::before,
.wp-bubble::after {
  content: "";
  position: absolute;
  left: 50%;
  background: var(--wp-bubble-bg);
  border-left: 1px solid var(--wp-ink);
  border-right: 1px solid var(--wp-ink);
}
.wp-bubble::before { top: 100%; width: 8px; height: 3px; margin-left: -4px; }
.wp-bubble::after  { top: calc(100% + 3px); width: 4px; height: 3px; margin-left: -2px; border-bottom: 1px solid var(--wp-ink); }

/* Someone has stopped: the bubble goes quiet rather than shouting a stale sentence. */
.wp-worker[data-stalled="1"] .wp-bubble { opacity: .5; }

.wp-stage { position: relative; display: flex; align-items: flex-end; justify-content: center; }
.wp-sprite { display: block; }

/* The two poses. Both frames are in the same svg so the sprite cannot shift by a pixel between
   them; the stylesheet just decides which one is showing. */
.wp-f { opacity: 0; }
.wp-f0 { opacity: 1; }
.wp-worker[data-status="running"][data-stalled="0"] .wp-f0 { animation: wp-fa var(--gait) steps(1, end) infinite; }
.wp-worker[data-status="running"][data-stalled="0"] .wp-f1 { animation: wp-fb var(--gait) steps(1, end) infinite; }
.wp-worker[data-status="running"][data-stalled="0"] .wp-sprite { animation: wp-bob var(--gait) steps(1, end) infinite; }
/* Walking is the same two frames, six times the tempo. One asset, two speeds. */
.wp-worker.is-walking { --gait: calc(var(--beat) / 8); }
.wp-worker.is-walking .wp-f0 { animation: wp-fa var(--gait) steps(1, end) infinite; }
.wp-worker.is-walking .wp-f1 { animation: wp-fb var(--gait) steps(1, end) infinite; }

.wp-shadow {
  position: absolute;
  bottom: -1px; left: 50%;
  width: 60%; height: 3px;
  transform: translateX(-50%);
  background: color-mix(in srgb, var(--wp-ink) 42%, transparent);
}

/* Sleep, drawn. Three grey sprites with z's above them say "half the team has stalled" faster
   than three timestamps ever will. */
.wp-snooze {
  position: absolute;
  top: -2px; right: 4px;
  animation: wp-snooze calc(var(--beat) * 1.5) ease-out infinite;
}

.wp-beacon {
  position: absolute;
  top: -4px; left: 50%;
  margin-left: -9px;
  --mark: var(--wp-bad);
  animation: wp-beacon calc(var(--beat) / 3) steps(1, end) infinite;
}

/* The nameplate. Status is a SHAPE first — a disc, a tick, a wedge, an open square — because a
   red dot and a green dot are the same dot to a lot of people, and at this size to everyone. */
.wp-plate {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  max-width: 100%;
  margin-top: 3px;
  padding: 1px 4px;
  /* Opaque, so what the plate is made of is not decided by the room behind it. At 78% it took a
     tint from whatever prop it stood over — which meant the same nameplate read dark-on-light in
     one room and light-on-dark in the next, and made its contrast uncomputable rather than merely
     low. A label's job is to be read; the room shows through everywhere else. */
  background: var(--wp-bg);
  border: 1px solid color-mix(in srgb, var(--wp-ink) 55%, transparent);
}
.wp-name {
  font-size: 10px;
  font-weight: 600;
  color: var(--wp-fg);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.wp-worker[data-depth="0"] .wp-name { font-size: 11px; }
.wp-plate svg { flex: none; }
/* Was 9px at plain --wp-dim: measured 1.5-2.6:1 on real pixels — worse than the name-plate
   complaint that started this, and missed by the first fix because it only looked at the name.
   Mixed toward --wp-dim rather than toward the background, so it stays dark in the light theme
   instead of washing out. */
.wp-since {
  /* 11px, not 10. Measured on real pixels this text came in at 4.64:1 against a 9.40 nominal —
     AA on a small glyph eats about half — so it cleared the floor by 0.14, which is not headroom.
     Size is the stronger lever than colour here: the mix cannot go much past the name's own
     contrast without the two reading as equals, but a larger glyph keeps more of its ink. */
  font-size: 11px;
  color: color-mix(in srgb, var(--wp-fg) 90%, var(--wp-dim));
  font-variant-numeric: tabular-nums;
  flex: none;
}
.wp-lead-of {
  max-width: 100%;
  font-size: 9px;
  line-height: 1.35;
  color: color-mix(in srgb, var(--accent) 50%, var(--wp-fg));
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

/* An empty footprint where a report used to stand, and where they went. The pod stays honest
   about its size even when half of it is out of the building. */
.wp-out {
  display: flex;
  flex-wrap: wrap;
  align-content: flex-end;
  align-items: center;
  gap: 2px 4px;
  max-width: 116px;
  padding-bottom: 3px;
}
.wp-away {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 0 3px 1px;
  font-size: 9px;
  line-height: 1.4;
  /* 8.5px at plain --wp-dim measured 4.49:1 — one hundredth under AA, which is under. */
  color: color-mix(in srgb, var(--wp-dim) 62%, var(--wp-fg));
  white-space: nowrap;
  border-bottom: 1px dashed color-mix(in srgb, var(--accent) 85%, transparent);
}
.wp-away i { font-style: normal; color: color-mix(in srgb, var(--accent) 88%, var(--wp-fg)); }

.wp-empty {
  align-self: center;
  margin: 0 auto;
  font-size: 10px;
  color: color-mix(in srgb, var(--wp-dim) 60%, transparent);
}

/* ── outside ─────────────────────────────────────────────────────────────────────────────── */

.wp-outside {
  position: relative;
  display: grid;
  grid-template-rows: minmax(66px, 1fr) auto;
  min-width: 0;
  overflow: hidden;
  background:
    linear-gradient(
      180deg,
      color-mix(in srgb, var(--wp-h2) 34%, var(--wp-bg)) 0%,
      color-mix(in srgb, var(--wp-h1) 30%, var(--wp-bg)) 34%,
      color-mix(in srgb, var(--wp-h1) 15%, var(--wp-bg)) 68%,
      color-mix(in srgb, var(--wp-h5) 16%, var(--wp-bg)) 100%
    );
}
.wp-outside .wp-deck {
  background:
    linear-gradient(var(--wp-ink), var(--wp-ink)) left bottom 11px / 100% 2px no-repeat,
    repeating-linear-gradient(
      90deg,
      color-mix(in srgb, var(--wp-h4) 22%, var(--wp-bg)) 0 13px,
      color-mix(in srgb, var(--wp-ink) 26%, transparent) 13px 14px
    ) left bottom / 100% 11px no-repeat;
}
/* Two clouds, sixty seconds across — the slowest thing on screen, so the eye reads the sky as
   sky and never as something to watch. */
.wp-cloud {
  position: absolute;
  left: 0;
  opacity: .8;
  animation: wp-drift calc(var(--beat) * 25) linear infinite;
  pointer-events: none;
}
/* Three depths, three speeds — the nearest cloud is biggest and quickest, which is the whole of
   parallax and costs three declarations. */
.wp-cloud.a { top: 14%; animation-duration: calc(var(--beat) * 30); opacity: .55; }
.wp-cloud.b { top: 34%; animation-duration: calc(var(--beat) * 46); opacity: .38; }
.wp-cloud.c { top: 52%; animation-duration: calc(var(--beat) * 20); opacity: .7; }

.wp-disc {
  position: absolute;
  top: 16px; right: 18px;
  opacity: .85;
  pointer-events: none;
}

/* The rest of the world, far enough away to be one flat tone. It exists so the sky reads as
   distance rather than as an empty column beside the building. */
.wp-skyline {
  position: absolute;
  left: 0; right: 0;
  bottom: -2px;
  display: block;
  opacity: .5;
  pointer-events: none;
}
.wp-wall.wp-yard { position: relative; padding-bottom: 0; overflow: hidden; }

/* The threshold. The entrance is the last room on the ground floor and the street is immediately
   to its right, so the two are joined by the one thing that makes it a route: a path. */
.wp-gangway {
  position: absolute;
  left: 0; bottom: 26px;
  width: 34px; height: 3px;
  background: repeating-linear-gradient(90deg, var(--wp-ink) 0 4px, transparent 4px 8px);
  opacity: .8;
  pointer-events: none;
}
.wp-gangway::after {
  content: "";
  position: absolute;
  left: 30px; top: -3px;
  border: 4px solid transparent;
  border-left-color: var(--wp-ink);
  opacity: .8;
}

/* The trail a walker leaves for a moment, so the eye can follow where somebody went. */
.wp-trail { position: absolute; inset: 0; pointer-events: none; z-index: 40; overflow: visible; }
.wp-trail path { fill: none; stroke: var(--accent, var(--wp-h1)); stroke-width: 2; stroke-dasharray: 3 4; }

/* ── legend ──────────────────────────────────────────────────────────────────────────────── */

.wp-legend {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 10px;
  color: var(--wp-dim);
}
.wp-legend span { display: inline-flex; align-items: center; gap: 4px; }

/* People's own colours. The SHIRT is the pod's — that is the whole mechanism by which a report
   three rooms from its lead is still visibly theirs — and everything else is the person's own,
   hashed from their run id so the same agent has the same face every refresh. */
.wp-worker {
  --c-shirt: var(--accent, var(--wp-h1));
  --c-badge: color-mix(in srgb, var(--accent, var(--wp-h1)) 42%, var(--wp-ink));
  --c-eye: var(--wp-ink);
  --c-mouth: color-mix(in srgb, var(--wp-ink) 62%, #a8564a);
  --c-ghost: color-mix(in srgb, var(--wp-dim) 55%, var(--wp-bg));
  --c-ghost-ink: color-mix(in srgb, var(--wp-dim) 92%, var(--wp-bg));
}
.wp-worker:not([data-depth="0"]) {
  --c-shirt: color-mix(in srgb, var(--accent, var(--wp-h1)) 60%, var(--wp-tint));
}

/* Post already exchanged. Quiet, because the arrival is what is worth watching — but present on a
   cold load, when there is no arrival left to show. */
.wp-mail {
  position: absolute;
  top: -2px; left: -5px;
  display: inline-flex;
  align-items: center;
  gap: 1px;
}
.wp-mail b { font-size: 8px; font-weight: 700; color: var(--wp-fg); }

/* The bag the script reads the exchanges out of, and the note it clones to carry one. */
.wp-post { display: none; }
.wp-courier { position: absolute; z-index: 60; pointer-events: none; will-change: transform; }

/* Status colour, applied to whichever mark the markup asked for. */
.wp-worker[data-status="running"] { --mark: var(--wp-ok); }
.wp-worker[data-status="done"] { --mark: var(--wp-dim); }
.wp-worker[data-status="error"] { --mark: var(--wp-bad); }
.wp-worker[data-status="foreign"] { --mark: var(--wp-dim); }

/* ── motion ──────────────────────────────────────────────────────────────────────────────── */

@keyframes wp-fa { 0%, 49.99% { opacity: 1 } 50%, 100% { opacity: 0 } }
@keyframes wp-fb { 0%, 49.99% { opacity: 0 } 50%, 100% { opacity: 1 } }
@keyframes wp-bob { 0%, 49.99% { transform: translateY(0) } 50%, 100% { transform: translateY(-1px) } }
@keyframes wp-breathe { 0%, 100% { filter: brightness(1) } 50% { filter: brightness(1.11) } }
@keyframes wp-beacon { 0%, 49.99% { opacity: 1 } 50%, 100% { opacity: .15 } }
@keyframes wp-snooze {
  0% { transform: translate(0, 0) scale(1); opacity: 0 }
  22% { opacity: .95 }
  100% { transform: translate(5px, -11px) scale(1); opacity: 0 }
}
@keyframes wp-drift {
  0% { transform: translateX(-46px) }
  100% { transform: translateX(240px) }
}

/* A stalled worker stops moving. That is the whole idea — the absence of motion IS the reading,
   so nothing here fades it out gently. */
@media (prefers-reduced-motion: reduce) {
  .wp * { animation: none !important; }
  .wp { --travel: 1ms; }
}

/* ── narrow ──────────────────────────────────────────────────────────────────────────────── */

@media (max-width: 860px) {
  .wp-scene { grid-template-columns: minmax(0, 1fr); }
  .wp-outside { border-top: 2px solid var(--wp-ink); min-height: 148px; }
  .wp-gangway { display: none; }
  .wp { --w-lead: 108px; --w-rep: 96px; --w-mini: 86px; }
}

@media (max-width: 620px) {
  .wp-floor { grid-template-columns: repeat(2, minmax(0, 1fr)); grid-template-rows: none; }
  .wp-room { grid-row: auto; grid-template-rows: minmax(40px, 1fr) auto; border-bottom: 2px solid var(--wp-ink); }
  .wp-lobby { display: none; }
  .wp { --w-lead: 100px; --w-rep: 92px; --w-mini: 84px; }
}
`;
