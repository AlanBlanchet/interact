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
 *      panel.webview.html = renderWorkplace(state, nonce)                    // once
 *      panel.webview.postMessage({ type: "team", html: renderScene(state) }) // every refresh
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

export { renderScene } from "./scene";
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

export function renderWorkplace(state: TeamState, nonce: string): string {
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
</head>
<body>
<div id="wp-mount">${renderScene(state)}</div>
<script nonce="${n}">${SCRIPT}</script>
</body>
</html>`;
}
