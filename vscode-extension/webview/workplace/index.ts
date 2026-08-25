/** The workplace view — one entry point.
 *
 *      renderWorkplace(state, nonce) -> a complete HTML document
 *
 *  Hand it a `TeamState` and the webview's nonce; assign the result to `webview.html`. Nothing
 *  else is needed: the art, the stylesheet and the one script are generated into the document, so
 *  there is no bundle to build, no asset to resolve through `asWebviewUri`, and no request that
 *  could ever leave the machine.
 *
 *  Render it ONCE, then keep it. The engine inside is a running simulation with its own clock, so
 *  the way to update it is to post the next scene rather than to reassign the document:
 *
 *      panel.webview.html = renderWorkplace(state, nonce)                     // once
 *      panel.webview.postMessage({ type: "team", html: renderActors(state) }) // every refresh
 *
 *  The engine swaps `#wp-mount`, re-binds every body by `data-run-id`, and carries positions and
 *  journeys across the swap — so somebody sent to another room is watched the whole way there.
 *  Reassigning `.html` still works and still produces a real walk (the document recovers the last
 *  snapshot from `setState`), but the clock restarts each time; see `motion.ts`.
 */
import type { TeamState } from "../../src/team";
import { renderScene } from "./scene";
import { STYLE } from "./style";
import { SCRIPT } from "./motion";

export { renderScene, renderActors, brainOf, deptsOf, worldFor, placeOf } from "./scene";
export type { Cast } from "./scene";
export { STYLE } from "./style";
// The status lexicon is part of the workplace's public surface, not a private helper: the side
// bar imports it, and anything else that ever has to name a run's state must take these words
// rather than invent a second set.
export { STAMPS, STAMP_CSS, STALL_SECONDS, WORDS, isHeld, stampFor, stampHtml } from "./status";
export type { Stamp, StampKind } from "./status";

/** A nonce ends up inside an attribute and inside a CSP header value, so it is reduced to the
 *  alphabet a nonce is allowed to use rather than trusted. A caller passing something strange
 *  gets a broken script, never a broken document. */
function safeNonce(nonce: string): string {
  const clean = String(nonce).replace(/[^A-Za-z0-9+/=_-]/g, "");
  return clean || "workplace";
}

/** An embedded panel rendered BESIDE the room — the roster, supplied by the host.
 *
 *  "Your team and agents panel are still on the left side, whereas they should be in the big main
 *  panel somewhere." The room and the roster are two views of the same company and belong in the
 *  same wide surface; the side bar is left for the one conversation you are having. The host owns
 *  the roster's markup so this module keeps knowing only about the world.
 */
export interface WorkplaceAside {
  style: string;
  body: string;
  script: string;
}

export function renderWorkplace(state: TeamState, nonce: string, aside?: WorkplaceAside): string {
  const n = safeNonce(nonce);
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; img-src 'none'; font-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${n}';">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The team</title>
<style>${STYLE}</style>
${aside ? `<style>${aside.style}
/* The company, two ways, in one surface: the room on the left, the roster on the right. The
   roster scrolls on its own so a long team never pushes the room off screen. */
.wp-split { display: flex; align-items: stretch; height: 100vh; width: 100%; }
.wp-split > .wp-room { flex: 1 1 auto; min-width: 0; position: relative; overflow: hidden; }
/* The scene sizes itself to the VIEWPORT when it owns the page; inside the split it must size to
   its half, or — measured in the stacked layout — the room runs 894px tall in a 495px slot and
   its bottom-right survey controls land ON TOP of the roster, eating its clicks while a click
   near them scrubs the zoom. That is a blocking defect an overlay earns silently. */
.wp-split .wp { height: 100%; }
.wp-split > .wp-list {
  flex: 0 0 clamp(240px, 26%, 380px); min-width: 0; overflow-y: auto; overflow-x: hidden;
  border-left: 1px solid var(--vscode-panel-border, transparent);
  background: var(--vscode-editor-background);
}
/* 560, not 720. The breakpoint applies to the EDITOR GROUP, not the window: measured live, a
   1280px laptop with both side bars open leaves roughly 630px here, so a 720px threshold stacked
   the split for most real windows and only flipped side-by-side above ~1440px. At 560 the roster
   still gets its 240px floor and the room keeps ~320px, which is a room rather than a slot. */
@media (max-width: 560px) { .wp-split { flex-direction: column; }
  .wp-split > .wp-list { flex: 0 0 auto; max-height: 45%; border-left: 0;
    border-top: 1px solid var(--vscode-panel-border, transparent); } }
</style>` : ""}
</head>
<body>
${aside
  ? `<div class="wp-split"><div class="wp-room">${renderScene(state)}</div>` +
    `<div class="wp-list">${aside.body}</div></div>`
  : renderScene(state)}
<script nonce="${n}">${SCRIPT}</script>
${aside ? `<script nonce="${n}">${aside.script}</script>` : ""}
</body>
</html>`;
}
