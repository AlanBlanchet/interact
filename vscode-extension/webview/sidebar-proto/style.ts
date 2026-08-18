/** The look of the board.
 *
 *  Three rules run through all of it, and two of them are the workplace's own — deliberately, since
 *  the whole point of this panel is that it is the same world seen from a different desk.
 *
 *  COLOUR follows the editor. Paper, ink, steel and the printed rules are mixed from `--vscode-*`
 *  tokens, so the board is a warm dark card in a dark theme and a cream one in a light theme with
 *  no second palette existing anywhere. Only the people keep literal tones, which is why they are
 *  the one thing imported from the workplace unchanged.
 *
 *  MOTION follows one beat. Every ambient duration is an integer ratio of `--beat`, so a board full
 *  of live work moves as ONE thing rather than as six independent loops. The easing is declared
 *  inside the keyframes as well as on the shorthand, because `getComputedTiming().easing` reports
 *  `linear` for every CSS animation and the real value only survives on the keyframe.
 *
 *  PAPER IS A SILHOUETTE, NOT A BRIGHTNESS. The temptation with a paper metaphor is to make the
 *  slips white, and twelve white cards in a dark side bar is glare, not craft. So what makes these
 *  read as paper is the die-cut: the punch hole with a steel rod behind it, the binding gutter, the
 *  perforation between parts of the form, the tear on a job that died, the curled corner on one
 *  nobody has been back to. The fill can then follow the theme all the way down, which it does.
 *  Same reasoning as the workplace's derived ink rim — the shape carries the reading, so the colour
 *  is free to follow the editor.
 */

export const STYLE = String.raw`
*, *::before, *::after { box-sizing: border-box; }
/* Not a reset — the two UA margins that actually bite. <figure>/<p>/<h3> all carry one, and a
   silent 1em 40px on a slip is how every row ends up mysteriously too wide. */
html, body, p, h1, h2, h3, header, footer, section, article, figure { margin: 0; padding: 0; }

body {
  font-family: var(--vscode-font-family, system-ui, sans-serif);
  color: var(--vscode-foreground, #ccc);
  background: var(--vscode-editor-background, #1e1e1e);
  font-size: 12px;
  -webkit-font-smoothing: antialiased;
}

/* The size container. The narrow rules below have to restyle .sp itself, and a container query
   cannot style its own container — hence a wrapper whose only job is to be measured. Querying the
   CONTAINER rather than the viewport is also the truthful test: a side bar's width is its own, not
   the window's. */
.sp-panel { container-type: inline-size; }

.sp {
  /* ── tempo ───────────────────────────────────────────────────────────────────────────────
     One beat, shared with the workplace so the two surfaces breathe together. */
  --beat: 2.4s;
  --gait: calc(var(--beat) / 2);
  --ease-settle: cubic-bezier(.22, 1, .32, 1);

  /* ── the world, mixed from the theme ─────────────────────────────────────────────────── */
  --wp-bg: var(--vscode-editor-background, #1e1e1e);
  --wp-fg: var(--vscode-editor-foreground, #d4d4d4);
  --wp-dim: var(--vscode-descriptionForeground, #9a9a9a);
  --wp-ink: #14101c;
  --wp-tint: #e8e4f0;

  /* The same seven pod hues the building uses, from the theme's own chart palette. None of them
     is red: red means "stuck" everywhere on this surface, and a team whose spine happened to be
     red would read as a team on fire. */
  --wp-h1: var(--vscode-charts-blue, #4f9cf5);
  --wp-h2: var(--vscode-charts-purple, #b180d7);
  --wp-h3: var(--vscode-charts-yellow, #e2c08d);
  --wp-h4: var(--vscode-charts-green, #6fc28b);
  --wp-h5: var(--vscode-charts-orange, #e8925a);
  --wp-h6: color-mix(in srgb, var(--wp-h1) 55%, var(--wp-h4));
  --wp-h7: color-mix(in srgb, var(--wp-h2) 62%, var(--vscode-charts-red, #e06c75));

  --wp-ok: var(--vscode-charts-green, #6fc28b);
  --wp-bad: var(--vscode-errorForeground, #e06c75);

  /* ── stock and steel ─────────────────────────────────────────────────────────────────────
     A warm manila lifted just off the background — enough that a slip is an object, not so much
     that eight of them glare. The silhouette is doing the "this is paper" work, not the value. */
  --sp-paper: color-mix(in srgb, #d9cfae 13%, var(--wp-bg));
  --sp-paper-shade: color-mix(in srgb, #d9cfae 8%, var(--wp-bg));
  --sp-paper-back: color-mix(in srgb, var(--wp-fg) 26%, var(--wp-bg));
  --sp-edge: color-mix(in srgb, var(--wp-fg) 30%, var(--wp-bg));
  --sp-shadow: color-mix(in srgb, var(--wp-ink) 62%, transparent);
  --sp-rule: color-mix(in srgb, var(--wp-fg) 22%, var(--wp-bg));
  --sp-ink: var(--wp-fg);
  --sp-dim: color-mix(in srgb, var(--wp-dim) 62%, var(--wp-fg));
  --sp-plate: color-mix(in srgb, var(--wp-fg) 82%, var(--wp-bg));

  --sp-rod: color-mix(in srgb, var(--wp-fg) 52%, var(--wp-bg));
  --sp-rod-hi: color-mix(in srgb, var(--wp-fg) 78%, var(--wp-bg));
  --sp-rod-lo: color-mix(in srgb, var(--wp-fg) 26%, var(--wp-bg));
  /* Three hard stops in the proportions of the tip's own pixel row (l l m m m d), so the drawn
     point and the stretched rod are the same cylinder and the join is invisible. */
  --sp-rod-fill: linear-gradient(90deg,
    var(--sp-rod-hi) 0 33.333%,
    var(--sp-rod) 33.333% 83.333%,
    var(--sp-rod-lo) 83.333% 100%);

  position: relative;
  display: flex;
  flex-direction: column;
  padding: 9px 9px 15px 4px;
  min-height: 100vh;
}

/* A light theme needs the ink to soften and the paper to go the other way, or the slips end up
   darker than the page they sit on and the whole pile reads as a hole. */
.vscode-light .sp,
.vscode-high-contrast-light .sp {
  --wp-ink: #2c2438;
  /* The tint mixes INTO the shirt colour, so on a light theme it has to go the other way or every
     pod hue washes out to a pastel with nothing to sit against. The workplace flips it here too. */
  --wp-tint: #2f2a3a;
  --sp-paper: color-mix(in srgb, #efe6cd 88%, var(--wp-bg));
  --sp-paper-shade: color-mix(in srgb, #e3d8ba 88%, var(--wp-bg));
  --sp-paper-back: color-mix(in srgb, #b9ac8a 92%, var(--wp-bg));
  --sp-edge: color-mix(in srgb, var(--wp-fg) 42%, var(--wp-bg));
  --sp-shadow: color-mix(in srgb, var(--wp-ink) 30%, transparent);
  --sp-rule: color-mix(in srgb, var(--wp-fg) 30%, var(--wp-bg));
  --sp-ink: color-mix(in srgb, var(--wp-ink) 90%, var(--wp-bg));
  --sp-dim: color-mix(in srgb, var(--wp-ink) 72%, var(--wp-bg));
  --sp-rod: color-mix(in srgb, var(--wp-fg) 46%, var(--wp-bg));
  --sp-rod-hi: color-mix(in srgb, var(--wp-fg) 24%, var(--wp-bg));
  --sp-rod-lo: color-mix(in srgb, var(--wp-fg) 72%, var(--wp-bg));
}

/* ── the spike ───────────────────────────────────────────────────────────────────────────────
   One rod, from above the first slip to below the composer. It is the reason this panel is one
   object: the paperwork and the thing you type into are impaled on the same piece of steel. */

.sp-rail {
  position: absolute;
  left: 10px; top: 0; bottom: 0;
  width: 12px;
  z-index: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  pointer-events: none;
}
.sp-tip svg, .sp-base svg { display: block; }
.sp-rod { flex: 1 1 auto; width: 12px; background: var(--sp-rod-fill); }
.sp-base { margin-left: -4px; }

/* ── the plate by the door ─────────────────────────────────────────────────────────────────
   The same pressed sign the workplace hangs over its entrance: light plate, background-coloured
   letters, hard ink shadow. Copied on purpose — it is the cheapest possible proof that the two
   surfaces are one product. */

.sp-plate {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  margin: 0 0 8px 22px;
}
.sp-plate-name {
  padding: 2px 8px;
  background: var(--sp-plate);
  color: var(--wp-bg);
  border: 1px solid var(--sp-edge);
  box-shadow: 2px 2px 0 0 var(--sp-shadow);
  font-weight: 700;
  font-size: 10px;
  letter-spacing: .18em;
  text-transform: uppercase;
}
.sp-tally { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.sp-chip {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 10px; color: var(--sp-dim);
  --mark: var(--sp-dim);
}
.sp-chip b { color: var(--sp-ink); font-weight: 600; font-variant-numeric: tabular-nums; }
.sp-chip:first-child { --mark: var(--wp-ok); }
.sp-chip svg { display: block; }
.sp-chip-sum b { font-variant-numeric: tabular-nums; }

/* ── one work order ────────────────────────────────────────────────────────────────────────
   A team is ONE piece of paper: the lead printed at the top, its reports stapled underneath, one
   punch hole for the document. The 22px gutter on the left is the binding margin — it holds the
   hole and the staples, and it is what stops the text colliding with the rod. */

.sp-stack { position: relative; z-index: 1; }

.sp-order {
  position: relative;
  margin: 0 0 9px 0;
  padding: 5px 7px 0 22px;
  background: var(--sp-paper);
  border: 1px solid var(--sp-edge);
  box-shadow: 2px 2px 0 0 var(--sp-shadow);
}

/* The margin rule. Every printed form has one down its binding edge, and it is most of why a
   rectangle of theme colour reads as a FORM rather than as a card. */
.sp-order::before {
  content: "";
  position: absolute;
  left: 19px; top: 0; bottom: 0;
  width: 1px;
  background: color-mix(in srgb, var(--wp-fg) 20%, transparent);
  pointer-events: none;
}

/* The team's colour, run down the binding edge. A report standing three rooms away in the
   workplace keeps this same hue on its shirt — one assignment, two surfaces. */
.sp-spine {
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 4px;
  background: var(--accent, var(--wp-h1));
}

/* Punched, with the rod visible through it. The fill is the rod's own gradient at the rod's own
   x-offset, so it is pixel-identical to seeing the steel through the hole. */
.sp-hole {
  position: absolute;
  left: 6px; top: 7px;
  width: 12px; height: 12px;
  /* Round, because a punched hole is. It is the one curve in a panel of hard edges and it earns
     the exception: a 12px square filled with the rod gradient read as a BUTTON, not as steel seen
     through paper. The fill is the rod's own gradient at the rod's own x-offset, so it is
     pixel-identical to seeing the rod through the hole. */
  border-radius: 50%;
  background: var(--sp-rod-fill);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--wp-ink) 80%, transparent),
    inset 0 2px 3px -1px color-mix(in srgb, var(--wp-ink) 85%, transparent),
    0 1px 0 0 color-mix(in srgb, var(--wp-fg) 22%, transparent);
}

/* ── one job ──────────────────────────────────────────────────────────────────────────────── */

.sp-slip {
  position: relative;
  padding: 5px 0 6px;
  border-top: 1px dashed var(--sp-rule);
  cursor: pointer;
  transition: transform 120ms var(--ease-settle), filter 120ms linear;
}
.sp-slip:first-of-type { border-top: 0; }
.sp-slip[data-depth="1"] { margin-left: 9px; }

.sp-slip:hover { transform: translate(-1px, -1px); filter: brightness(1.07); }
.sp-slip:focus-visible {
  outline: 2px solid var(--vscode-focusBorder, #0078d4);
  outline-offset: -1px;
}

.sp-row { display: flex; gap: 7px; align-items: flex-start; }
.sp-mug { flex: 0 0 auto; line-height: 0; }
.sp-mug-slim { padding-top: 3px; --mark: var(--sp-dim); }
.sp-slip[data-status="running"] .sp-mug-slim { --mark: var(--wp-ok); }
.sp-slip[data-status="error"] .sp-mug-slim { --mark: var(--wp-bad); }
.sp-body { flex: 1 1 auto; min-width: 0; }

.sp-head { display: flex; align-items: center; gap: 5px; }
.sp-name {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.25;
  color: var(--sp-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sp-head > :not(.sp-name) { flex: 0 0 auto; }

.sp-role {
  font-size: 10px;
  color: var(--sp-dim);
  letter-spacing: .02em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* What it is actually doing, in its own words. Two lines, then it stops — the whole sentence is on
   the hover title and in the conversation a click away. */
.sp-said {
  margin-top: 2px;
  font-size: 11px;
  line-height: 1.34;
  color: var(--sp-ink);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.sp-said-none { color: var(--sp-dim); font-style: italic; }

.sp-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 3px;
  font-size: 10px;
  color: var(--sp-dim);
  font-variant-numeric: tabular-nums;
}
.sp-from { margin-left: auto; opacity: .9; }

/* ── the pile ──────────────────────────────────────────────────────────────────────────────
   Paper sinks. Live work sits on top at full height; anything finished, held or somebody else's
   is pressed down to a sliver you can still read a name off. Vertical space goes to whatever wants
   a person's attention, which is the one thing a list of equal rows cannot do. Lifting a slip —
   hover or keyboard focus — brings it back up. */

.sp-slip[data-fold="slim"] { padding: 3px 0 4px; }
.sp-slip[data-fold="slim"] .sp-body { display: flex; align-items: center; gap: 7px; }
.sp-slip[data-fold="slim"] .sp-head { flex: 1 1 auto; min-width: 0; }
.sp-slip[data-fold="slim"] .sp-name { font-size: 11px; font-weight: 600; color: var(--sp-dim); }
.sp-slip[data-fold="slim"] .sp-role,
.sp-slip[data-fold="slim"] .sp-said { display: none; }
.sp-slip[data-fold="slim"] .sp-foot { flex: 0 0 auto; margin-top: 0; }
.sp-slip[data-fold="slim"] .sp-from { display: none; }
.sp-slip[data-fold="slim"] .sp-stamp { transform: rotate(-4deg); }

.sp-slip[data-fold="slim"]:hover .sp-body,
.sp-slip[data-fold="slim"]:focus-visible .sp-body { display: block; }
.sp-slip[data-fold="slim"]:hover .sp-name,
.sp-slip[data-fold="slim"]:focus-visible .sp-name { color: var(--sp-ink); }
.sp-slip[data-fold="slim"]:hover .sp-role,
.sp-slip[data-fold="slim"]:focus-visible .sp-role { display: block; }
.sp-slip[data-fold="slim"]:hover .sp-said,
.sp-slip[data-fold="slim"]:focus-visible .sp-said { display: -webkit-box; }
.sp-slip[data-fold="slim"]:hover .sp-foot,
.sp-slip[data-fold="slim"]:focus-visible .sp-foot { margin-top: 3px; }

/* ── the marks ─────────────────────────────────────────────────────────────────────────────
   Status by SHAPE first — a filled disc, a tick, a pointed wedge, an open square — and by colour
   second, never colour alone. Running work is UNSTAMPED: an open job with nothing stamped on it is
   the oldest "in progress" signal there is, and it saves the loud marks for what wants looking at.
*/

.sp-stamp {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 4px 2px;
  border: 2px solid currentColor;
  color: var(--stamp, var(--sp-dim));
  --mark: currentColor;
  font-size: 9px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: .11em;
  text-transform: uppercase;
  transform: rotate(-7deg);
  opacity: .92;
}
.sp-stamp svg { display: block; }
.sp-stamp[data-kind="done"] { --stamp: var(--wp-ok); }
.sp-stamp[data-kind="error"] { --stamp: var(--wp-bad); opacity: 1; }
.sp-stamp[data-kind="foreign"], .sp-stamp[data-kind="held"] { --stamp: var(--sp-dim); }

.sp-lamp { --mark: var(--wp-ok); line-height: 0; }
.sp-lamp svg { display: block; animation: sp-pulse calc(var(--beat) / 3) ease-in-out infinite; }

.sp-out { line-height: 0; --pod: var(--accent, var(--wp-h1)); }
.sp-out svg { display: block; animation: sp-flag var(--beat) ease-in-out infinite; transform-origin: 0 50%; }

.sp-snooze { line-height: 0; --mark: var(--sp-dim); }
.sp-snooze svg { display: block; }

/* The curl a slip takes when nobody has been back to it. Sits on the outside corner of the paper,
   so it reads as the sheet lifting rather than as an icon printed on it. */
.sp-ear { position: absolute; right: 0; bottom: 0; line-height: 0; pointer-events: none; }
/* A buried slip has no room to curl — its sleep mark already carries the reading, and an ear here
   lands straight on top of the cost. */
.sp-slip[data-fold="slim"] .sp-ear { display: none; }
.sp-ear svg { display: block; }

/* The staple that holds a report onto its lead. Lives in the binding gutter, which is exactly
   where a real one would be. */
.sp-staple { position: absolute; left: -13px; top: 7px; line-height: 0; }
.sp-staple svg { display: block; }

/* A job that died is TORN. The tear is generated so the zigzag stays even at any width, and it is
   the status you read before any colour or any word. */
.sp-slip[data-torn="1"] { padding-bottom: 12px; }
/* The tear paints the PANEL, not the paper: the notches are where the sheet is missing, so what
   shows through them is whatever is behind the work order. Clipped to a generated sawtooth. */
.sp-tear {
  position: absolute;
  left: -18px; right: -7px; bottom: 0;
  height: 8px;
  background: var(--wp-bg);
}
.sp-slip[data-torn="1"] { background: color-mix(in srgb, var(--wp-bad) 5%, transparent); }

/* Somebody else's session is flat and unowned: no face, no colour, dashed. */
.sp-slip[data-status="foreign"] { opacity: .8; }

/* ── the form's total ──────────────────────────────────────────────────────────────────────── */

.sp-total {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
  padding: 3px 0 4px;
  border-top: 1px solid var(--sp-rule);
  font-size: 9px;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--sp-dim);
}
.sp-proj { color: var(--accent, var(--wp-h1)); font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sp-sum { margin-left: auto; font-variant-numeric: tabular-nums; letter-spacing: 0; }
/* A lone worker keeps only the project stamp — the strip is still there so the sheet has a foot,
   but it stops repeating a figure that is already one line above it. */
.sp-total-solo { padding: 2px 0 3px; }

.sp-empty {
  position: relative;
  z-index: 1;
  margin-left: 22px;
  padding: 18px 0;
  color: var(--sp-dim);
  font-style: italic;
}

/* ── the slip you are writing ──────────────────────────────────────────────────────────────
   The composer is the last piece of paper on the same spike. This is the answer to two panels that
   do not belong to each other: not a shared colour scheme, a shared PIECE OF HARDWARE. */

.sp-compose {
  position: relative;
  z-index: 1;
  /* Pushed to the floor of the panel. What opens up above it is BARE ROD, which is the argument
     this whole direction rests on: the paperwork and the thing you type into are on one spike. */
  margin-top: auto;
  padding: 6px 8px 8px 22px;
  background: var(--sp-paper);
  border: 1px solid var(--sp-edge);
  box-shadow: 2px 2px 0 0 var(--sp-shadow);
}
.sp-compose-tag {
  font-size: 9px;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--sp-dim);
}
.sp-compose-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: 3px;
  padding-top: 4px;
  border-top: 1px dashed var(--sp-rule);
}
.sp-caret { color: var(--wp-ok); font-weight: 700; }
.sp-compose-ph { color: var(--sp-dim); font-style: italic; }

/* ── the people ────────────────────────────────────────────────────────────────────────────
   Imported whole from the workplace: the same grids, the same deterministic face per run id, the
   same pod colour on the shirt. Not a lookalike — the same rectangles. */

.sp-sprite { display: block; }
.sp-slip {
  --c-shirt: var(--accent, var(--wp-h1));
  --c-badge: color-mix(in srgb, var(--accent, var(--wp-h1)) 42%, var(--wp-ink));
  --c-eye: var(--wp-ink);
  --c-mouth: color-mix(in srgb, var(--wp-ink) 62%, #a8564a);
  --c-ghost: color-mix(in srgb, var(--wp-dim) 55%, var(--wp-bg));
  --c-ghost-ink: color-mix(in srgb, var(--wp-dim) 92%, var(--wp-bg));
}
.vscode-light .sp-slip,
.vscode-high-contrast-light .sp-slip {
  --c-shirt: color-mix(in srgb, var(--accent, var(--wp-h1)) 60%, var(--wp-tint));
}

/* Two frames, one asset, flipped on the shared beat — the same mechanism and the same tempo the
   building uses, so a person at the desk and a person on the board are working at one speed. */
/* The frame groups are named by the shared engine (drawFrames emits wp-f0/wp-f1), so these
   selectors are the workplace's, not this file's — which is the point. */
.wp-f0 { opacity: 1; }
.wp-f1 { opacity: 0; }
.sp-slip[data-status="running"][data-stalled="0"] .wp-f0 { animation: sp-fa var(--gait) steps(1, end) infinite; }
.sp-slip[data-status="running"][data-stalled="0"] .wp-f1 { animation: sp-fb var(--gait) steps(1, end) infinite; }
/* A stalled worker STOPS MOVING. Absence of motion is the reading — louder and cheaper than a
   timestamp, and the building already says it this way. */

@keyframes sp-fa {
  0%   { opacity: 1; animation-timing-function: steps(1, end); }
  50%  { opacity: 0; animation-timing-function: steps(1, end); }
  100% { opacity: 1; }
}
@keyframes sp-fb {
  0%   { opacity: 0; animation-timing-function: steps(1, end); }
  50%  { opacity: 1; animation-timing-function: steps(1, end); }
  100% { opacity: 0; }
}
@keyframes sp-pulse {
  0%   { opacity: .45; transform: scale(.86); animation-timing-function: cubic-bezier(.4, 0, .2, 1); }
  50%  { opacity: 1;   transform: scale(1);   animation-timing-function: cubic-bezier(.4, 0, .2, 1); }
  100% { opacity: .45; transform: scale(.86); }
}
@keyframes sp-flag {
  0%   { transform: skewY(0deg);   animation-timing-function: cubic-bezier(.45, 0, .55, 1); }
  50%  { transform: skewY(-7deg);  animation-timing-function: cubic-bezier(.45, 0, .55, 1); }
  100% { transform: skewY(0deg); }
}

@media (prefers-reduced-motion: reduce) {
  .sp-lamp svg, .sp-out svg, .sp-f0, .sp-f1 { animation: none !important; }
  .sp-f1 { opacity: 0; }
}

/* ── narrow ────────────────────────────────────────────────────────────────────────────────
   A side bar the user has squeezed. The gutter and the mug stay (they are the object), the
   typography tightens, and the parts of the foot that repeat information already on screen go. */

@container (max-width: 252px) {
  .sp { padding: 8px 6px 15px 3px; }
  .sp-order { padding-left: 20px; padding-right: 5px; }
  .sp-plate { margin-left: 20px; gap: 5px; }
  .sp-hole { left: 5px; }
  .sp-name { font-size: 11px; }
  .sp-said { font-size: 10px; -webkit-line-clamp: 3; }
  .sp-role, .sp-foot { font-size: 9px; }
  .sp-foot { gap: 6px; }
  .sp-slip[data-depth="1"] { margin-left: 6px; }
  .sp-staple { left: -11px; }
  .sp-total { gap: 6px; }
  .sp-slip[data-fold="slim"] .sp-stamp b { display: none; }
  .sp-slip[data-fold="slim"] .sp-stamp { padding: 2px 3px; }
  .sp-slip[data-fold="slim"]:hover .sp-stamp b,
  .sp-slip[data-fold="slim"]:focus-visible .sp-stamp b { display: inline; }
}
`;
