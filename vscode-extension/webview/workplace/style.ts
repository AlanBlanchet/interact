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
 *  so a room full of sprites moves as one thing rather than as nine independent loops. The one
 *  exception is walking, and it is deliberate: a walk is driven by the ENGINE, frame by frame off
 *  the distance covered, because a footfall on a CSS clock slides the moment a body speeds up.
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
  overflow-x: hidden;
}

.wp {
  --beat: 2.4s;

  --wp-bg: var(--vscode-editor-background, #1e1e1e);
  --wp-fg: var(--vscode-editor-foreground, #d4d4d4);
  /* The editor's description colour is tuned for the EDITOR background, not for a small label on
     a busy floor: it measures 3.95:1 at 10px in a light theme, under the 4.5 floor. Lifted toward
     the foreground until both themes clear it — the same trap this project has already been bitten
     by on the side bar's role line. */
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
     empty room the BRIGHTEST thing on screen, so occupancy read backwards. Mixing toward ink
     greys it in a light theme and darkens it in a dark one, which is "off" in both. */
  --wp-shut: color-mix(in srgb, var(--wp-ink) 34%, transparent);
  --wp-plate: color-mix(in srgb, var(--wp-fg) 82%, var(--wp-bg));
  --wp-paper: color-mix(in srgb, #f3efe4 82%, var(--wp-bg));

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

  --stamp-ink: var(--wp-fg);
  --stamp-quiet: var(--wp-dim);
  --stamp-mix: var(--wp-bg);
  --stamp-bg: var(--wp-bg);
  --stamp-shadow: var(--wp-ink);

  padding: 6px 8px 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 100vh;
}

/* A light theme has to flip the tint dark, or every team colour pastels out against cream. */
body.vscode-light .wp,
body.vscode-high-contrast-light .wp {
  --wp-tint: #2f2a3a;
  --t-wall-foot: color-mix(in srgb, var(--wp-ink) 32%, var(--wp-bg));
  --t-carpet: color-mix(in srgb, var(--wp-h1) 9%, var(--wp-bg));
  --t-carpet-hi: color-mix(in srgb, var(--wp-h1) 15%, var(--wp-bg));
}

/* ── the board by the door ─────────────────────────────────────────────────────────────────── */

.wp-hud {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 11px;
}
.wp-sign {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  padding: 2px 8px;
  border: 2px solid var(--wp-line);
  background: color-mix(in srgb, var(--wp-fg) 8%, var(--wp-bg));
}
.wp-sign-name { font-weight: 700; letter-spacing: .13em; text-transform: uppercase; font-size: 11px; }
.wp-sign-sub { color: var(--wp-dim); font-size: 10px; }
.wp-tally { display: inline-flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.wp-chip { display: inline-flex; align-items: center; gap: 4px; color: var(--wp-dim); }
.wp-chip b { color: var(--wp-fg); }
.wp-clock { margin-left: auto; color: var(--wp-dim); font-size: 10px; }

/* ── the stage ─────────────────────────────────────────────────────────────────────────────
   The building is laid out ONCE at its true tile size and then scaled as one object. Letting it
   reflow would be the flexbox mistake in another costume: a floor plan has a shape, and every
   route the engine computes is in tiles, so the picture must stay in exact proportion at any
   panel width. */

.wp-view {
  position: relative;
  overflow: auto;
  margin: 0 auto;
  border: 2px solid var(--wp-line);
  background: color-mix(in srgb, var(--wp-ink) 30%, var(--wp-bg));
}
.wp-stagebox {
  position: relative;
  transform-origin: 0 0;
  image-rendering: pixelated;
}
.wp-map { position: absolute; inset: 0; display: block; }
.wp-world { display: none; }

/* Daylight crossing the building. One rectangle, one minute, no layout: it is the only thing on
   screen slower than a person, which is what makes the place feel like it has a time of day. */
.wp-view::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 400;
  background: linear-gradient(105deg,
    transparent 0%,
    color-mix(in srgb, var(--wp-h3) 7%, transparent) 42%,
    transparent 74%);
  background-size: 260% 100%;
  animation: wp-daylight calc(var(--beat) * 25) ease-in-out infinite alternate;
}
@keyframes wp-daylight { from { background-position: 0% 0; } to { background-position: 100% 0; } }

/* A room with somebody in it is LIT. Answering "where is everyone" with the shape of the light
   costs nothing to read and happens before a single label does. */
.wp-glow {
  fill: color-mix(in srgb, var(--wp-h3) 15%, transparent);
  opacity: 0;
  transition: opacity 420ms ease;
}
.wp-shut {
  fill: var(--wp-shut);
  opacity: 1;
  transition: opacity 420ms ease;
}
.wp-rm[data-lit="1"] .wp-glow { opacity: 1; }
.wp-rm[data-lit="1"] .wp-shut { opacity: 0; }
.wp-rm.is-brain .wp-glow { fill: color-mix(in srgb, var(--wp-h3) 18%, transparent); }
.wp-core { animation: wp-core calc(var(--beat) * 1.5) ease-in-out infinite; transform-origin: center; }
@keyframes wp-core { 0%, 100% { opacity: .72; } 50% { opacity: 1; } }

.wp-plaque {
  position: absolute;
  z-index: 300;
  font-size: 8px;
  letter-spacing: .09em;
  text-transform: uppercase;
  font-weight: 700;
  color: var(--wp-bg);
  background: var(--wp-plate);
  padding: 1px 4px;
  box-shadow: 2px 2px 0 var(--wp-ink);
  white-space: nowrap;
  pointer-events: none;
}

/* ── a character ───────────────────────────────────────────────────────────────────────────
   The element is a POINT — a zero-sized anchor standing on a tile — and everything hangs off it.
   That is what lets the engine move a person with one transform, and what stops the text around
   somebody from deciding where they are allowed to be.

   The text is deliberately small and deliberately below them. The version this replaced put a
   paragraph in a grey box over every head: the words out-massed the characters, and a place whose
   labels are bigger than its people is a diagram, not a place. */

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
.wp-actor[data-depth]:not([data-depth="0"]) { --c-shirt: color-mix(in srgb, var(--accent) 60%, var(--wp-tint)); }

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

/* The head of the company stands taller. It is the cheapest true thing the picture can say about
   the one agent everybody else reports to, and it needs no label to say it. */
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
  animation: wp-crown calc(var(--beat) * 2) ease-in-out infinite;
}
@keyframes wp-crown {
  0%, 100% { opacity: .35; transform: scale(.9); }
  50% { opacity: .9; transform: scale(1.08); }
}

.wp-shade {
  position: absolute;
  left: -12px;
  bottom: -2px;
  width: 24px;
  height: 6px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--wp-ink) 46%, transparent);
}

/* Two poses for standing, two for walking, in one element. Which pair shows is the engine's call:
   the walk frames are flipped on DISTANCE covered, not on a clock, so a body that accelerates
   keeps its feet under it. */
.wp-f { opacity: 0; }
.wp-stand .wp-f0 { opacity: 1; }
.wp-actor[data-status="running"] .wp-stand .wp-f0 { animation: wp-fa calc(var(--beat) / 2) steps(1, end) infinite; }
.wp-actor[data-status="running"] .wp-stand .wp-f1 { animation: wp-fb calc(var(--beat) / 2) steps(1, end) infinite; }
@keyframes wp-fa { 0%, 62% { opacity: 1; } 63%, 100% { opacity: 0; } }
@keyframes wp-fb { 0%, 62% { opacity: 0; } 63%, 100% { opacity: 1; } }
.wp-walk { visibility: hidden; }
.wp-actor.is-walking .wp-stand { visibility: hidden; }
.wp-actor.is-walking .wp-walk { visibility: visible; }
.wp-actor.is-walking .wp-walk .wp-f1 { opacity: 1; }
.wp-actor.is-walking.wp-fA .wp-walk .wp-f1 { opacity: 0; }
.wp-actor.is-walking.wp-fA .wp-walk .wp-f0 { opacity: 1; }
.wp-actor.is-walking .wp-shade { opacity: .55; }

.wp-tag {
  position: absolute;
  left: 0;
  top: 3px;
  transform: translateX(-50%);
  display: block;
  max-width: 76px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 7px;
  line-height: 1.35;
  letter-spacing: .01em;
  white-space: nowrap;
  color: var(--wp-fg);
  /* Opaque, not translucent. Two characters standing a tile apart WILL overlap — that is what a
     crowd is — so the one in front has to cover the one behind cleanly rather than blending into
     it. Depth ordering already decides which that is. */
  background: color-mix(in srgb, var(--wp-bg) 92%, var(--wp-fg));
  padding: 0 3px;
  border-bottom: 1px solid var(--accent, var(--wp-h1));
  pointer-events: none;
}
.wp-actor:hover .wp-tag,
.wp-actor:focus-visible .wp-tag { max-width: none; overflow: visible; }
.wp-tag i { font-style: normal; color: var(--wp-dim); margin-left: 3px; }
.wp-actor.is-brain .wp-tag { font-weight: 700; border-bottom-color: var(--wp-h3); }

/* What this one can DO, read off its own definition file. Six glyphs is the whole vocabulary, so
   a character that can only read is visibly a different character from one that drives a browser
   and puts others to work — without a word of prose anywhere. */
.wp-can {
  position: absolute;
  left: 0;
  top: 14px;
  transform: translateX(-50%);
  display: flex;
  gap: 1px;
  pointer-events: none;
}
.wp-fac {
  --mark: var(--wp-bg);
  font-style: normal;
  font-size: 8px;
  line-height: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px;
  color: var(--wp-bg);
  background: color-mix(in srgb, var(--accent, var(--wp-h1)) 86%, var(--wp-bg));
}
.wp-fac svg { display: block; }
.wp-actor[data-status="foreign"] .wp-fac,
.wp-actor[data-status="done"] .wp-fac { background: color-mix(in srgb, var(--wp-dim) 70%, var(--wp-bg)); }

/* The line above their head. Hidden by default and shown for a few seconds when it CHANGES, or
   while a reader is pointing at them. Permanently-open speech was the single biggest thing making
   this read as a labelled diagram. */
.wp-say {
  position: absolute;
  left: 0;
  bottom: 66px;
  transform: translate(-50%, 4px);
  max-width: 190px;
  padding: 2px 5px;
  font-size: 9px;
  line-height: 1.3;
  color: var(--wp-ink);
  background: var(--wp-paper);
  box-shadow: 2px 2px 0 var(--wp-ink);
  opacity: 0;
  pointer-events: none;
  transition: opacity 180ms ease, transform 180ms ease;
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
.wp-actor.is-saying .wp-say,
.wp-actor:hover .wp-say,
.wp-actor:focus-visible .wp-say { opacity: 1; transform: translate(-50%, 0); }
.wp-actor:hover .wp-say b,
.wp-actor:focus-visible .wp-say b { white-space: normal; }
.wp-actor:hover, .wp-actor:focus-visible { z-index: 900 !important; }

/* The back rank wears its name over its head. See Seat.up in world.ts: three tiles is room for two
   people and not enough for two people plus their labels, and the front body would otherwise be
   drawn over the back body's name — the wrong person hiding the right person's identity. */
.wp-actor[data-label="up"] .wp-tag { top: auto; bottom: 58px; }
.wp-actor[data-label="up"] .wp-can { top: auto; bottom: 70px; }
.wp-actor[data-label="up"] .wp-say { bottom: 96px; }
.wp-actor[data-label="up"] .wp-mark { bottom: 84px; }

.wp-mark {
  position: absolute;
  left: 0;
  bottom: 54px;
  transform: translateX(-50%) scale(.55);
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

/* ── the key ───────────────────────────────────────────────────────────────────────────────── */

.wp-legend {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 10px;
  color: var(--wp-dim);
}
.wp-key { display: inline-flex; align-items: center; gap: 4px; }
.wp-facs { display: inline-flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.wp-facs .wp-fac {
  margin-left: 6px;
  background: color-mix(in srgb, var(--wp-fg) 30%, var(--wp-bg));
  color: var(--wp-bg);
}
.wp-proto { position: absolute; visibility: hidden; pointer-events: none; }

${STAMP_CSS}

/* ── reduced motion ────────────────────────────────────────────────────────────────────────
   Everything above degrades to a still floor plan with everybody standing at their own desk. The
   engine never starts its clock, so nothing walks, nothing pulses and the picture is exactly the
   one a reader would get if they paused it. */
@media (prefers-reduced-motion: reduce) {
  .wp-view::after,
  .wp-core,
  .wp-actor.is-brain::before,
  .wp-actor .wp-stand .wp-f0,
  .wp-actor .wp-stand .wp-f1,
  .wp-actor.is-talking .wp-body { animation: none !important; }
  .wp-glow, .wp-shut { transition: none; }
  .wp-stand .wp-f0 { opacity: 1; }
  .wp-stand .wp-f1 { opacity: 0; }
}
`;
