/** The seam between the workplace DATA and the workplace VISUAL.
 *
 *  The pixel-art room is built separately under `webview/workplace/` — a visual is reworked far
 *  more often than the data behind it, and keeping them apart means either can change alone.
 *  This module is the adapter: it takes a `TeamState`, hands it to whichever renderer is present,
 *  and falls back to a plain, honest room so the pipeline is testable before the art exists.
 */
import { ZONES, leads, reportsOf } from "./team";
import type { TeamState, Worker } from "./team";

export function renderWorkplace(state: TeamState, nonce: string): string {
  return plainRoom(state, nonce);
}

/** Escaped once, here: a worker's name and activity are agent output. */
function esc(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function worker(w: Worker, all: Worker[]): string {
  const reports = reportsOf(all, w.run_id);
  const nested = reports.length
    ? `<div class="reports">${reports.map((r) => worker(r, all)).join("")}</div>`
    : "";
  return `<div class="worker ${esc(w.status)}">
    <div class="who">${esc(w.name)}</div>
    <div class="doing">${esc(w.activity)}</div>
    ${nested}
  </div>`;
}

function plainRoom(state: TeamState, nonce: string): string {
  const rooms = ZONES.map((zone) => {
    const here = leads(state.workers).filter((w) => w.zone === zone.id);
    return `<section class="zone"><h2>${esc(zone.label)}</h2>
      ${here.map((w) => worker(w, state.workers)).join("") || '<p class="empty">—</p>'}
    </section>`;
  }).join("");
  return `<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>
  body { margin: 0; padding: 1rem; font-family: var(--vscode-font-family);
         color: var(--vscode-foreground); background: var(--vscode-editor-background); }
  .rooms { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 1rem; }
  .zone { border: 1px solid var(--vscode-panel-border); border-radius: 6px; padding: .6rem; }
  h2 { margin: 0 0 .5rem; font-size: .8rem; text-transform: uppercase; letter-spacing: .08em;
       color: var(--vscode-descriptionForeground); }
  .worker { border-left: 2px solid var(--vscode-focusBorder); padding: .2rem .5rem; margin: .4rem 0; }
  .worker.done, .worker.foreign { border-left-color: var(--vscode-panel-border); opacity: .55; }
  .who { font-weight: 600; }
  .doing { color: var(--vscode-descriptionForeground); font-size: .9em; }
  .reports { margin-left: .8rem; }
  .empty { color: var(--vscode-descriptionForeground); margin: 0; }
</style></head>
<body><div class="rooms">${rooms}</div></body></html>`;
}
