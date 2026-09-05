/** The rail, rendered.
 *
 *  Everything here exists at REST — no hover, no focus, no agent selected. That is the entire
 *  reason this surface is a webview rather than a `TreeView`: VS Code shows a view's title actions
 *  only while the pointer is inside the header and clips the overflow with no "…" menu, so the
 *  panel it replaces rendered zero buttons until you happened to move the mouse over it.
 *
 *  Two host facts this file is shaped by, both learned the hard way:
 *   - the theme variables are injected onto `<body>`, never `:root`, so a `:root` token block
 *     silently never resolves;
 *   - a `<script>` without the CSP nonce is dropped without a word, taking every behaviour with it.
 */

import type { Rail, RailHeader } from "./rail";
import type { AgentAction } from "./agentActions";

/** Kept in step with `themeTokens.ts` DIM_FOREGROUND, and inlined rather than imported so this
 *  module stays runtime-import-free for the test loader. `--vscode-descriptionForeground` is
 *  #767676 on Light+'s #f8f8f8 — 4.28:1, under AA before a panel touches it — so the raw token is
 *  never used for text. Measured here: 4.3:1 raw, 5.4:1 pulled toward the foreground. */
const DIM = "color-mix(in srgb, var(--vscode-descriptionForeground, #9a9a9a) 70%, " +
  "var(--vscode-editor-foreground, #d4d4d4))";

/** The header as one line of prose — presentation, so it lives here rather than in `rail.ts`.
 *  That also keeps this module free of any RUNTIME import: the type above is erased, which is what
 *  lets the test loader resolve it (it demands ".ts" specifiers that tsc refuses to emit).
 *
 *  An empty team reads as a sentence rather than "0 · 0 · 0", which looks like a fault instead of
 *  a quiet morning.
 */
export function headerLine(header: RailHeader): string {
  const bits: string[] = [];
  if (header.needsYou) bits.push(`${header.needsYou} need${header.needsYou === 1 ? "s" : ""} you`);
  if (header.working) bits.push(`${header.working} working`);
  if (header.finished) bits.push(`${header.finished} done`);
  return bits.length ? bits.join(" · ") : "nobody working yet";
}

function esc(text: string): string {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/** How a status is spoken. Shape first, colour second — colour alone is unreadable to a good share
 *  of people and invisible in a screenshot taken at a glance.
 *
 *  This used to be a local table, and that was the defect: the world stamped "DONE" on tilted paper
 *  while this row said a green tick and lowercase "finished". Same five states, two products —
 *  which visual-critic called out twice and tied to "the environment is weird". The vocabulary now
 *  lives in `statusLanguage.ts` and is PASSED IN rather than imported, because this module must stay
 *  free of runtime imports for the test loader. Required, not optional: a default here would let a
 *  caller quietly reintroduce a second source of truth, and the compiler is a better guard than a
 *  comment asking nicely.
 */
export type Voice = { mark: string; word: string; phrase: string; accent: string; tinted: boolean; quiet?: boolean };

export function railHtml(
  rail: Rail,
  nonce: string,
  /** How each status is spoken — the SAME vocabulary the workplace stamps. See `statusLanguage.ts`. */
  voiceOf: (attention: string) => Voice,
  /** What to CALL a conversation. Passed in (this module stays runtime-import-free) from
   *  `conversation.ts`, which names a conversation by what it is DOING — the old rule fell back to
   *  the provider, so twenty unrelated engagements all rendered as "claude". */
  titleOf: (run: Rail["runs"][number]["run"]) => string,
  /** Which AGENT held a conversation — its stable `id` (what the filter matches on) and its
   *  `label` (what a person reads). Two fields, because the coordinator's id is "main" while its
   *  label is its title: posting the label as the filter key would match nothing. From
   *  `roster.ts`; passed in, never imported. */
  roleOf: (run: Rail["runs"][number]["run"]) => { id: string; label: string },
  /** What each row can be asked to do. Passed in rather than imported so this module keeps no
   *  runtime import — the test loader demands ".ts" specifiers that tsc refuses to emit. */
  actionsFor: (run: Rail["runs"][number]["run"]) => AgentAction[] = () => [],
): string {
  return railDocument(nonce, railStyle(), railBody(rail, voiceOf, titleOf, roleOf, actionsFor));
}

/** The rail's stylesheet, on its own so a HOST document can embed the roster.
 *
 *  The roster's home is the big editor panel, beside the world — "they should be in the big main
 *  panel somewhere". A side-bar view renders a whole document; an editor panel needs a FRAGMENT it
 *  can place next to the room. Splitting document from fragment is what lets one roster serve both
 *  without a second implementation drifting away from this one.
 */
export function railStyle(): string {
  return `/* THE STAFF BOARD ON THE OFFICE WALL.
   The world beside this column is vivid Kenney pixel art; a native VS Code list bolted to it read
   as two products. So the roster is built from the world's own kit: its ink (#14101c), its hard
   2px-offset shadows, its plate-and-plaque signage, its press-into-the-shadow buttons, its stamp
   (2px rule, tracked uppercase, the error plate with the alarm halo, on the same 2.4s beat), and
   the atlas's own measured hues — lawn teal #38cbab / #21837c, terracotta #c66527, furniture wood
   #8f673f. Literal tones are mixed toward theme ink/paper (never toward the page), so the same
   plate holds AA in Dark+ and Light+ — every pairing below was measured, not eyeballed.
   Tokens hang off body: VS Code injects --vscode-* there, and a :root block never resolves. */
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0;
  font-family: var(--vscode-font-family);
  font-size: var(--vscode-font-size, 13px);
  color: var(--vscode-foreground);
  background: var(--vscode-sideBar-background, var(--vscode-editor-background));

  /* The board's palette, sampled from the world's own atlas + style. Namespaced --bd-* so the
     embedded fragment never collides with the workplace's --wp-* set on the same page. */
  --bd-beat: 2.4s;                                  /* the ONE beat everything ambient shares */
  --bd-ink: #14101c;                                /* the world's ink — every hard shadow */
  --bd-teal: #38cbab;                               /* the lawn, bright */
  --bd-deep: #21837c;                               /* the lawn, in shade */
  --bd-terra: #c66527;                              /* roofs and furniture */
  --bd-wood: #8f673f; --bd-wood-hi: #b98b5e;        /* the desks */
  --bd-paper: #f3efe4;                              /* the world's paper stock */
  --bd-bg: var(--vscode-editor-background, #1f1f1f);
  --bd-fg: var(--vscode-foreground, #cccccc);
  --bd-line: color-mix(in srgb, var(--bd-fg) 26%, var(--bd-bg));      /* --wp-line's recipe */
  --bd-chrome: color-mix(in srgb, var(--bd-bg) 92%, var(--bd-fg));    /* --wp-chrome's recipe */
  --bd-shadow: color-mix(in srgb, var(--bd-ink) 78%, transparent);
  /* Plates mix the hue toward INK, never toward the page: a teal plate mixed toward white died at
     1.9-3.1:1 in Light+, while these hold in both themes because they barely move. Measured:
     paper-on-teal-plate 6.8:1, paper-on-wood-plate 6.2:1, both themes. */
  --bd-plate: color-mix(in srgb, var(--bd-deep) 65%, var(--bd-ink));
  --bd-woodplate: color-mix(in srgb, var(--bd-wood) 75%, var(--bd-ink));
  --bd-papertext: color-mix(in srgb, var(--bd-paper) 92%, var(--bd-bg));
  /* The header's teal wash and the cap-light on it. 26% keeps DIM at 5.4:1 in dark; Light+ drops
     to 18% below because 26% took DIM to 4.2 — under the floor. */
  --bd-wash: color-mix(in srgb, var(--bd-deep) 26%, var(--bd-bg));
  --bd-cap: color-mix(in srgb, var(--bd-teal) 40%, transparent);
  --bd-grid: color-mix(in srgb, var(--bd-fg) 5%, transparent);
  --bd-hover: color-mix(in srgb, var(--bd-deep) 15%, var(--bd-bg));

  /* The floor's own tile grid, as a whisper — texture, never noise behind body text. */
  background-image:
    linear-gradient(var(--bd-grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--bd-grid) 1px, transparent 1px);
  background-size: 16px 16px;
}
body.vscode-light, body.vscode-high-contrast-light {
  --bd-wash: color-mix(in srgb, var(--bd-deep) 18%, var(--bd-bg));    /* DIM 4.68:1, measured */
  --bd-cap: color-mix(in srgb, var(--bd-deep) 35%, transparent);      /* bright teal is 2:1 on white */
  --bd-grid: color-mix(in srgb, var(--bd-fg) 6%, transparent);
}
/* Inside the split document the host paints .wp-list with a bare background shorthand; the tag
   qualifiers out-rank it so the board surface and its 2px frame seam survive there too. */
div.wp-split > div.wp-list {
  background-color: var(--bd-bg);
  background-image:
    linear-gradient(var(--bd-grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--bd-grid) 1px, transparent 1px);
  background-size: 16px 16px;
  border-left: 2px solid var(--bd-plate);
}
/* The board scrolls behind a square rail, not a rounded native thumb. The ROOT scroller's
   pseudo-elements resolve variables against <html>, which the body-scoped tokens never reach —
   so the root gets var-free neutrals and any scroller INSIDE body gets the board's own inks. */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-corner { background: transparent; }
::-webkit-scrollbar-thumb {
  background: rgba(125, 125, 125, .4);
  border: 2px solid transparent; background-clip: padding-box;
}
body ::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, var(--bd-fg) 24%, var(--bd-bg));
  border: 2px solid var(--bd-bg); background-clip: border-box;
}
body ::-webkit-scrollbar-thumb:hover {
  background: color-mix(in srgb, var(--bd-deep) 55%, var(--bd-bg));
}
::selection { background: color-mix(in srgb, var(--bd-teal) 35%, var(--bd-bg)); }
/* The board's painted top rail: teal wash, a cap-light along its top edge (the world lights every
   wall cap), and the deep-teal foot it stands on. Opaque, because the list scrolls under it. */
.rail {
  position: sticky; top: 0; z-index: 2;
  padding: 9px 10px 8px;
  background-color: var(--bd-wash);
  border-bottom: 2px solid var(--bd-plate);
  box-shadow: inset 0 2px 0 var(--bd-cap);
}
/* The scope is the answer to "whose agents are these?" — so it is also the way to change it.
   It is the board's routed WOOD nameplate: the one wooden thing here, like the desks are there.
   Paper text on the wood plate measures 6.2:1 in both themes. */
.scope {
  font: inherit; font-weight: 700; cursor: pointer;
  padding: 2px 8px; border-radius: 0;
  color: var(--bd-papertext);
  background: var(--bd-woodplate);
  /* A routed edge: lit on top/left, in shade below — the pixel bevel every Kenney prop carries. */
  border: 1px solid;
  border-color: color-mix(in srgb, var(--bd-wood-hi) 55%, var(--bd-woodplate))
    color-mix(in srgb, var(--bd-ink) 45%, var(--bd-woodplate))
    color-mix(in srgb, var(--bd-ink) 45%, var(--bd-woodplate))
    color-mix(in srgb, var(--bd-wood-hi) 55%, var(--bd-woodplate));
  box-shadow: 2px 2px 0 var(--bd-shadow);
}
.scope::after { content: " ⌄"; opacity: .8; font-size: .85em; }
.scope:hover { background: color-mix(in srgb, var(--bd-wood) 88%, var(--bd-ink)); }
.scope:active { transform: translate(1px, 1px); box-shadow: 1px 1px 0 var(--bd-shadow); }
.scope:focus-visible { outline: 1px solid var(--vscode-focusBorder); outline-offset: 1px; }
/* Stronger than DIM: this line sits ON the header's teal wash, which eats ~0.3 of ratio —
   measured 4.2:1 in Light+ with the plain DIM mix, under the 4.5 floor. 85% toward the
   foreground clears it in both themes while still reading quieter than the scope. */
.counts { color: color-mix(in srgb, var(--vscode-foreground, #cccccc) 85%, ` +
  `var(--vscode-descriptionForeground, #9a9a9a)); margin-left: 7px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
/* The world's own latch button (.wp-cam-wide): square, hard ink shadow, and a press that moves
   the button INTO its shadow — the one depth cue pixel art allows itself. */
.chip {
  font: inherit;
  padding: 3px 10px;
  border-radius: 0;
  cursor: pointer;
  color: var(--bd-fg);
  background: var(--bd-chrome);
  border: 1px solid var(--bd-line);
  box-shadow: 2px 2px 0 var(--bd-shadow);
}
.chip:hover {
  background: color-mix(in srgb, var(--bd-deep) 22%, var(--bd-bg));
  border-color: color-mix(in srgb, var(--bd-deep) 55%, var(--bd-line));
}
.chip:active { transform: translate(1px, 1px); box-shadow: 1px 1px 0 var(--bd-shadow); }
.chip:focus-visible { outline: 1px solid var(--vscode-focusBorder); outline-offset: 1px; }
/* A slot cut into the board: square, grooved by an inset ink shadow rather than a native well. */
.seek {
  font: inherit; width: 100%; margin-top: 9px; padding: 4px 9px; border-radius: 0;
  color: var(--vscode-input-foreground, var(--bd-fg));
  background: color-mix(in srgb, var(--bd-fg) 5%, var(--bd-bg));
  border: 1px solid var(--bd-line);
  box-shadow: inset 2px 2px 0 color-mix(in srgb, var(--bd-ink) 20%, transparent);
}
.seek::placeholder { color: ${DIM}; opacity: 1; }
.seek::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }
.seek:focus { border-color: color-mix(in srgb, var(--bd-deep) 70%, var(--bd-fg)); }
.seek:focus-visible { outline: 1px solid var(--vscode-focusBorder); }
.crumbs { display: flex; align-items: baseline; gap: 5px; margin-top: 7px; font-size: .92em; }
.crumb {
  font: inherit; cursor: pointer; padding: 0 5px; border-radius: 0;
  color: var(--bd-teal); background: transparent; border: 1px solid transparent;
}
.crumb:hover { background: var(--bd-hover); border-color: var(--bd-line); }
/* Bright teal is a dark-theme colour; on paper it drops to the lawn's shade tone (4.6:1). */
body.vscode-light .crumb, body.vscode-high-contrast-light .crumb { color: var(--bd-deep); }
.crumbSep { color: ${DIM}; }
.crumbNow { font-weight: 700; }
/* The role a conversation was held with. Quiet, but a real control: it is how you get from one
   engagement to every other engagement with the same colleague. */
.role {
  font: inherit; font-size: .82em; cursor: pointer;
  padding: 0 5px; border-radius: 0; white-space: nowrap;
  color: ${DIM}; background: transparent;
  border: 1px solid var(--bd-line);
}
.role:hover { color: var(--bd-fg); background: var(--bd-hover); }
.role:focus-visible { outline: 1px solid var(--vscode-focusBorder); }
/* The ×N task counter used to render as a BARE NATIVE BUTTON — the loudest "IDE widget" on the
   whole board, and no rule here ever addressed it. A small pixel counter chip now. */
.tasks {
  font: inherit; font-size: .78em; line-height: 1.2; cursor: pointer;
  margin-left: 5px; padding: 0 4px; border-radius: 0;
  color: var(--bd-fg); background: var(--bd-chrome);
  border: 1px solid var(--bd-line);
  box-shadow: 1px 1px 0 var(--bd-shadow);
}
.tasks:hover { background: color-mix(in srgb, var(--bd-deep) 22%, var(--bd-bg)); }
.tasks:active { transform: translate(1px, 1px); box-shadow: none; }
ul.runs { list-style: none; margin: 0; padding: 4px 0; }
/* FLEX, not grid, and deliberately so. This row was a 4-track grid; the round that added a stamp
   and a role chip took it to six children, so .note landed in the 16px mark column and broke one
   letter-pair per line ("st/op/pe/d/wi/th"). A grid whose track count must be kept in sync by hand
   with a template's child count is a trap that renders perfectly in every unit test and is
   unreadable on screen. Flex wrapping cannot fall out of step: children take the room they need,
   and the two full-width rows say so themselves. */
.row {
  display: flex; flex-wrap: wrap; align-items: baseline;
  gap: 3px 6px;
  padding: 3px 10px; cursor: pointer;
  /* The anchor for the hover-revealed actions. */
  position: relative;
}
.mark { flex: none; width: 16px; text-align: center; }
.stamp, .role { flex: none; }
/* The explanation owns a line, indented past the mark so the row reads as one block. */
.note { flex: 1 1 100%; padding-left: 22px; }
/* The same STAMP the world presses: the fixed 2px rule, the tracked uppercase, a slight tilt —
   ink pressed into the board, so no shadow and nothing behind it (that is how a desk mounts it;
   only the placard in the building throws a shadow). -3deg, not the placard's -7: a dense row
   grants about a pixel of overhang, and the tilt only has to say "pressed by hand". */
.stamp {
  display: inline-flex; align-items: center;
  font-size: .78em; font-weight: 700; letter-spacing: .11em; line-height: 1.1;
  padding: 1px 4px 2px; border-radius: 0; white-space: nowrap;
  color: var(--accent, var(--bd-fg));
  border: 2px solid currentColor;
  background: transparent;
  transform: rotate(-3deg);
}
/* Chart accents are dark-theme colours; on paper they thin out (yellow measured 2.9:1), so the
   light themes pull every accent toward the foreground — the DIM discipline, applied to hue. */
body.vscode-light .stamp, body.vscode-high-contrast-light .stamp {
  color: color-mix(in srgb, var(--accent, var(--bd-fg)) 58%, var(--bd-fg));
}
body.vscode-light .mark, body.vscode-high-contrast-light .mark {
  color: color-mix(in srgb, var(--accent, var(--bd-fg)) 65%, var(--bd-fg));
}
.row:hover { background: var(--bd-hover); }
/* The two states that want a person carry the room-rim's device: an accent edge on the row. */
.runs .row[data-attention="error"], .runs .row[data-attention="asked"] {
  box-shadow: inset 3px 0 0 var(--accent);
}
/* ERROR is the world's filled plate — white on near-black red, the one pairing that holds in both
   themes — with the same alarm halo, on the same beat, that pulses over a crashed head next door. */
.runs .row[data-attention="error"] .stamp {
  color: #fff;
  background: color-mix(in srgb, var(--accent) 58%, #1a0508);
  border-color: color-mix(in srgb, var(--accent) 58%, #1a0508);
  animation: bd-alarm calc(var(--bd-beat) * 2 / 3) ease-in-out infinite;
}
@keyframes bd-alarm {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 65%, transparent); }
  50% { box-shadow: 0 0 0 5px color-mix(in srgb, var(--accent) 0%, transparent); }
}
@media (prefers-reduced-motion: reduce) {
  .runs .row[data-attention="error"] .stamp { animation: none; }
}
/* Machinery behind intent: outcomes at rest, the buttons only when the hand (or the keyboard)
   arrives. An overlay, not a second line — a resting row is ONE line, and revealing must not
   make the list jump. Opacity rather than display so the keyboard can still reach a button:
   tabbing into an invisible control fires :focus-within, which is what reveals it. Filtered to
   the actions that would WORK, so nothing here is ever a dead control. */
.acts {
  display: flex; gap: 2px;
  opacity: 0; pointer-events: none;
  position: absolute; right: 4px; top: 50%; transform: translateY(-50%);
  padding: 1px 3px; border-radius: 0;
  /* A little tool tray that arrives with the hand: chrome stock, hard ink shadow, like the
     survey instruments in the corner of the room next door. */
  background: var(--bd-chrome);
  border: 1px solid var(--bd-line);
  box-shadow: 2px 2px 0 var(--bd-shadow);
}
.row:hover .acts, .row:focus-within .acts { opacity: 1; pointer-events: auto; }
.act {
  font: inherit; line-height: 1; padding: 1px 5px;
  border: 1px solid transparent; border-radius: 0;
  background: transparent; color: ${DIM}; cursor: pointer;
}
.act:hover { background: color-mix(in srgb, var(--bd-deep) 26%, var(--bd-bg));
  color: var(--bd-fg); border-color: color-mix(in srgb, var(--bd-deep) 45%, var(--bd-line)); }
.act:focus-visible { outline: 1px solid var(--vscode-focusBorder); }
/* ONE line. A task is a sentence and a sentence is a paragraph in a 300px column — the owner's
   panel read as walls of "Reply with exactly: ..." because titles were allowed to wrap. Clipped
   with an ellipsis; the row opens for the rest. */
.who {
  font-weight: 500; min-width: 0; flex: 1 1 auto;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.when, .cost { flex: none; color: ${DIM}; font-size: .85em; }
/* The grouped row's second line: what the speaking errand is about, clipped the same way. */
.oneliner {
  flex: 1 1 100%; padding-left: 22px; color: ${DIM}; font-size: .9em;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
/* Band headings are PLAQUES — the signs the building hangs on every department, pressed onto the
   board with a terracotta pushpin. Deep-teal plate mixed toward ink so paper text holds 6.8:1 in
   both themes; the same hard shadow every sign in the building throws. */
.staffHead, details.staffBox > summary.staffHead {
  display: inline-block; position: relative;
  margin: 12px 10px 4px; padding: 3px 8px 3px 17px;
  color: var(--bd-papertext); background: var(--bd-plate);
  font-size: .74em; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
  box-shadow: 2px 2px 0 var(--bd-shadow);
}
/* The pin: a terracotta head with a glint on its lit shoulder and shade under it — the same
   one-light rule every tile in the scene obeys. */
.staffHead::before, .empty::before {
  content: ""; position: absolute; left: 6px; top: 50%; margin-top: -3px;
  width: 6px; height: 6px; background: var(--bd-terra);
  box-shadow: inset 1px 1px 0 color-mix(in srgb, var(--bd-paper) 55%, transparent),
    inset -1px -1px 0 color-mix(in srgb, var(--bd-ink) 45%, transparent);
}
details.ledger, details.staffBox { margin: 6px 0 0; }
details.ledger > summary, details.staffBox > summary {
  cursor: pointer; padding: 4px 10px; color: ${DIM}; font-size: .9em;
  list-style: none;
}
details.ledger > summary::-webkit-details-marker,
details.staffBox > summary::-webkit-details-marker { display: none; }
/* The disclosure mark is drawn in this board's own pixels — a stepped triangle cut with the same
   clip-path quantisation the world's cast shadows use, never the native marker. Opening gives it
   the quarter turn the world gives a body lying down onto the couch. */
details.ledger > summary::before, details.staffBox > summary.staffHead::after {
  content: ""; display: inline-block; width: 6px; height: 10px;
  background: currentColor;
  clip-path: polygon(0 0, 2px 0, 2px 2px, 4px 2px, 4px 4px, 6px 4px, 6px 6px, 4px 6px,
    4px 8px, 2px 8px, 2px 10px, 0 10px);
  vertical-align: -1px;
}
details.ledger > summary::before { margin-right: 8px; }
details.staffBox > summary.staffHead::after { margin-left: 8px; }
details.ledger[open] > summary::before,
details.staffBox[open] > summary.staffHead::after { transform: rotate(90deg); }
details.ledger > summary:hover { background: var(--bd-hover); color: var(--bd-fg); }
details.staffBox > summary.staffHead:hover {
  background: color-mix(in srgb, var(--bd-deep) 78%, var(--bd-ink));
}
.runs.aged .row, .runs.staff .row { opacity: .85; }
/* A report is indented under the lead that sent it, so the roster reads as a company rather than
   a flat list — you can see who is driving what. */
.row[data-report] { padding-left: 26px; }
.row[data-report] .mark { opacity: .75; }
/* The orchestrator is MARKED, never pinned to the top: this list sorts by who needs you, and a
   healthy boss must not bury a crashed agent. Amber, because the world crowns the brain in the
   lamp's own --wp-h3 ring. */
.brain {
  margin-left: 6px; padding: 0 4px;
  font-size: .8em; border-radius: 0;
  color: color-mix(in srgb, var(--vscode-charts-yellow, #d7ba7d) 55%, var(--bd-fg));
  border: 1px solid color-mix(in srgb, var(--vscode-charts-yellow, #d7ba7d) 55%, var(--bd-bg));
  background: color-mix(in srgb, var(--vscode-charts-yellow, #d7ba7d) 12%, var(--bd-bg));
}
.note { color: ${DIM}; overflow-wrap: anywhere; }
/* Attention reads by SHAPE first; colour only reinforces it. One accent per row, supplied by the
   shared vocabulary — six near-identical rules here were how the two surfaces drifted apart. */
.mark { color: var(--accent, var(--vscode-foreground)); }
/* Nothing to read is a NOTE pinned to the board — paper stock, ink writing, hung by hand. */
.empty {
  display: inline-block; position: relative;
  margin: 16px 12px; padding: 9px 12px 9px 20px;
  color: color-mix(in srgb, var(--bd-ink) 86%, var(--bd-paper));
  background: color-mix(in srgb, var(--bd-paper) 90%, var(--bd-bg));
  box-shadow: 2px 2px 0 var(--bd-shadow);
  transform: rotate(-1deg);
}
.empty::before { left: 7px; }`;
}

/** The roster itself: header, chips, breadcrumb, rows. No document, no script — a fragment. */
/** "3h ago", "just now" — WHEN is the one fact a professional expects instantly and nothing
 *  showed: durations everywhere, dates nowhere. Relative and terse; the tooltip has nothing more
 *  because the registry stores seconds, not stories. */
function agoOf(startedAt: number | null | undefined): string {
  if (!startedAt) return "";
  const s = Math.max(0, Date.now() / 1000 - startedAt);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 129600) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function railBody(
  rail: Rail,
  voiceOf: (attention: string) => Voice,
  titleOf: (run: Rail["runs"][number]["run"]) => string,
  roleOf: (run: Rail["runs"][number]["run"]) => { id: string; label: string },
  actionsFor: (run: Rail["runs"][number]["run"]) => AgentAction[] = () => [],
): string {
  const chips = rail.chips
    .map((c) => `<button class="chip" data-command="${esc(c.command)}">${esc(c.label)}</button>`)
    .join("");

  // At team level a row is a COLLEAGUE: the name leads (the same name the world's plaque
  // carries — "visual-critic" here and "Visual QA authority" there was three names for one
  // entity), the errand is the quiet second line. Inside a drill-in a row is a CONVERSATION,
  // so the title leads — you already know who you are visiting.
  const drilled = Boolean(rail.filter);
  const rowHtml = (r: Rail["runs"][number]): string => {
    const voice = voiceOf(r.attention);
    // One of YOUR sessions: titled by the project it is building — the fact you recognise it
    // by — never by a task field discovery does not fill.
    const mine = r.attention === "not-ours";
    const who = mine ? (r.run.project || r.run.name)
      : drilled ? titleOf(r.run) : roleOf(r.run).label;
    const errand = !mine && !drilled && (r.run.task ?? "").trim() ? titleOf(r.run) : "";
    const bill = r.cost ?? r.run.cost_usd;
    return `
      <li class="row" data-run="${esc(r.run.run_id)}" data-attention="${esc(r.attention)}"${
        r.depth ? ' data-report="1"' : ""}${r.brain ? ' data-brain="1"' : ""}
        style="--accent: var(${esc(voice.tinted ? voice.accent : "--vscode-descriptionForeground")})">
        <span class="mark">${esc(voice.mark)}</span>
        <span class="who">${esc(who)}${
          (r.tasks ?? 1) > 1 ? `<button class="tasks" data-agent="${esc(roleOf(r.run).id)}" title="Show all ${r.tasks} tasks">×${r.tasks}</button>` : ""}${
          r.brain ? '<span class="brain" title="the agent you asked — it put the others to work">brain</span>' : ""}</span>
        ${voice.quiet || mine ? "" : `<span class="stamp">${esc(voice.word)}</span>`}
        ${errand ? `<span class="oneliner">${esc(errand)}</span>` : ""}
        <span class="when">${esc(agoOf(r.run.started_at))}</span>
        ${r.attention !== "ready" && bill != null ? `<span class="cost">$${bill.toFixed(2)}</span>` : ""}
        <span class="acts">${actionsFor(r.run).map((a) =>
          `<button class="act" data-action="${esc(a.id)}" data-command="${esc(a.command)}"` +
          ` title="${esc(a.label)}">${a.mark}</button>`).join("")}</span>
      </li>`;
  };

  const rows = rail.runs.map(rowHtml).join("");

  // Your own sessions — the work this machine is doing right now, newest first, each a real
  // place to go. Above the ledger: live outranks history.
  const yours = (rail.yours ?? []).length
    ? `<div class="staffHead">Your sessions</div><ul class="runs yours">${
        (rail.yours ?? []).map(rowHtml).join("")}</ul>`
    : "";

  // History is ONE line that opens — never seven rows competing with the living team. The
  // header stops double-counting it too: its "done" is only the recent finishes above.
  const ledger = rail.ledger
    ? (() => {
        const l = rail.ledger;
        const bits: string[] = [];
        if (l.done) bits.push(`${l.done} done`);
        if (l.stopped) bits.push(`${l.stopped} stopped`);
        if (l.failed) bits.push(`${l.failed} failed`);
        if (l.cost > 0) bits.push(`$${l.cost.toFixed(2)}`);
        return `<details class="ledger"><summary>History — ${esc(bits.join(" · "))}</summary>` +
          `<ul class="runs aged">${l.runs.map(rowHtml).join("")}</ul></details>`;
      })()
    : "";

  // The company at rest. Folded: the world beside this column already SHOWS every colleague;
  // the roster names them on demand without spending forty rows on quiet desks.
  const staff = (rail.staff ?? []).length
    ? `<details class="staffBox"><summary class="staffHead">On staff — ${rail.staff!.length}</summary>` +
      `<ul class="runs staff">${rail.staff!.map(rowHtml).join("")}</ul></details>`
    : "";

  const empty = rail.runs.length || (rail.yours ?? []).length || rail.ledger
      || (rail.staff ?? []).length
    ? ""
    : `<p class="empty">Nothing here yet — start someone with <b>+ New</b>.</p>`;

  return `<div class="rail">
  <div><button class="scope" data-command="interact.agents.workspace"
    title="Show agents from another project">${esc(rail.header.scope || "all workspaces")}</button><span
    class="counts">${esc(headerLine(rail.header))}</span></div>
  <div class="chips">${chips}</div>
  <input class="seek" id="seek" type="search" placeholder="Filter agents and tasks"
    aria-label="Filter the roster" />
  ${rail.filter ? `<div class="crumbs"><button class="crumb" data-agent="">‹ Everyone</button>` +
    `<span class="crumbSep">/</span><span class="crumbNow">${esc(rail.filter)}</span></div>` : ""}
</div>
${empty}
<ul class="runs">${rows}</ul>
${yours}${ledger}${staff}`;
}

/** What the roster's buttons DO. Shared by both hosts for the same reason as the style. */
export function railScript(): string {
  return `const api = (window.__wpApi ||
    (typeof acquireVsCodeApi === "function" ? acquireVsCodeApi() : null));
  function bindRail() {
  document.querySelectorAll(".chip, .scope").forEach((b) => {
    b.addEventListener("click", () => api.postMessage({ type: "command", command: b.dataset.command }));
  });
  document.querySelectorAll(".row").forEach((r) => {
    r.addEventListener("click", () => api.postMessage({ type: "open", runId: r.dataset.run }));
  });
  {
    // The filter a professional reaches for before scrolling. Client-side, over what the row SAYS,
    // because that is what the person is matching on too.
    const seek = document.getElementById("seek");
    if (seek) seek.addEventListener("input", () => {
      const q = seek.value.trim().toLowerCase();
      document.querySelectorAll(".row").forEach((row) => {
        row.style.display = !q || row.textContent.toLowerCase().includes(q) ? "" : "none";
      });
      // A match buried in a CLOSED fold is a silent miss — searching opens the folds, and
      // clearing the filter re-folds them to their resting state.
      document.querySelectorAll("details").forEach((d) => { d.open = Boolean(q); });
    });
  }
  document.querySelectorAll(".tasks, .crumb").forEach((b) => {
    b.addEventListener("click", (e) => {
      e.stopPropagation();  // going to the agent must not also open the conversation under it
      api.postMessage({ type: "agent", id: b.dataset.agent });
    });
  });
  document.querySelectorAll(".act").forEach((b) => {
    b.addEventListener("click", (e) => {
      // Never let an action also open the row underneath it.
      e.stopPropagation();
      api.postMessage({ type: "act", command: b.dataset.command, runId: b.closest(".row").dataset.run });
    });
  });  }
  bindRail();
  // The panel MOUNTS once and is updated by message thereafter — rebuilding the document would
  // kill every running animation in the room next door. So the roster is replaced in place and
  // re-bound, exactly as the room is.
  window.addEventListener("message", function (e) {
    var m = e && e.data;
    if (!m || m.type !== "roster" || typeof m.html !== "string") return;
    var host = document.querySelector(".wp-list");
    if (!host) return;
    host.innerHTML = m.html;
    bindRail();
  });
`;
}

export function railDocument(nonce: string, style: string, body: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>
${style}
</style>
</head>
<body>
${body}
<script nonce="${nonce}">
${railScript()}
</script>
</body>
</html>`;
}
