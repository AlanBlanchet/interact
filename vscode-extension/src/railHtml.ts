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

/** A mark per attention band. Shape first, colour second — colour alone is unreadable to a good
 *  share of people and invisible in a screenshot taken at a glance. */
const MARK: Record<string, string> = {
  error: "✕",
  asked: "✉",
  held: "⏸",
  finished: "✓",
  working: "●",
  "not-ours": "○",
};

export function railHtml(rail: Rail, nonce: string): string {
  const chips = rail.chips
    .map((c) => `<button class="chip" data-command="${esc(c.command)}">${esc(c.label)}</button>`)
    .join("");

  const rows = rail.runs.map((r) => `
      <li class="row" data-run="${esc(r.run.run_id)}" data-attention="${esc(r.attention)}"${
        r.depth ? ' data-report="1"' : ""}${r.brain ? ' data-brain="1"' : ""}>
        <span class="mark">${MARK[r.attention] ?? "●"}</span>
        <span class="who">${esc(r.run.name || r.run.run_id.slice(0, 8))}${
          r.brain ? '<span class="brain" title="the agent you asked — it put the others to work">brain</span>' : ""}</span>
        <span class="note">${esc(r.note)}</span>
      </li>`).join("");

  const empty = rail.runs.length
    ? ""
    : `<p class="empty">Nothing here yet — start someone with <b>Company</b>.</p>`;

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>
/* Tokens hang off body: VS Code injects --vscode-* there, and a :root block never resolves. */
body {
  margin: 0;
  font-family: var(--vscode-font-family);
  font-size: var(--vscode-font-size, 13px);
  color: var(--vscode-foreground);
  background: var(--vscode-sideBar-background, var(--vscode-editor-background));
}
.rail {
  position: sticky; top: 0; z-index: 2;
  padding: 8px 10px 6px;
  background: inherit;
  border-bottom: 1px solid var(--vscode-panel-border, transparent);
}
.scope { font-weight: 600; }
.counts { color: ${DIM}; margin-left: 6px; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
.chip {
  font: inherit;
  padding: 3px 9px;
  border-radius: 11px;
  cursor: pointer;
  color: var(--vscode-foreground);
  background: var(--vscode-button-secondaryBackground, transparent);
  border: 1px solid var(--vscode-panel-border, var(--vscode-descriptionForeground));
}
.chip:hover { background: var(--vscode-list-hoverBackground); }
.chip:focus-visible { outline: 1px solid var(--vscode-focusBorder); outline-offset: 1px; }
ul.runs { list-style: none; margin: 0; padding: 4px 0; }
.row {
  display: grid;
  grid-template-columns: 16px minmax(0, auto) minmax(0, 1fr);
  gap: 6px; align-items: baseline;
  padding: 3px 10px; cursor: pointer;
}
.row:hover { background: var(--vscode-list-hoverBackground); }
.who { font-weight: 500; overflow-wrap: break-word; }
/* A report is indented under the lead that sent it, so the roster reads as a company rather than
   a flat list — you can see who is driving what. */
.row[data-report] { padding-left: 26px; }
.row[data-report] .mark { opacity: .75; }
/* The orchestrator is MARKED, never pinned to the top: this list sorts by who needs you, and a
   healthy boss must not bury a crashed agent. */
.brain {
  margin-left: 6px; padding: 0 5px;
  font-size: .85em; border-radius: 8px;
  color: var(--vscode-foreground);
  border: 1px solid var(--vscode-panel-border, var(--vscode-descriptionForeground));
}
.note { color: ${DIM}; overflow-wrap: break-word; }
/* Attention reads by SHAPE first; colour only reinforces it. */
.row[data-attention="error"] .mark { color: var(--vscode-charts-red); }
.row[data-attention="asked"] .mark { color: var(--vscode-charts-blue); }
.row[data-attention="held"] .mark { color: var(--vscode-charts-yellow); }
.row[data-attention="finished"] .mark { color: var(--vscode-charts-green); }
.row[data-attention="working"] .mark { color: var(--vscode-charts-blue); }
.row[data-attention="not-ours"] .mark { color: var(--vscode-charts-purple); }
.empty { color: ${DIM}; padding: 10px; }
</style>
</head>
<body>
<div class="rail">
  <div><span class="scope">${esc(rail.header.scope || "all workspaces")}</span><span
    class="counts">${esc(headerLine(rail.header))}</span></div>
  <div class="chips">${chips}</div>
</div>
${empty}
<ul class="runs">${rows}</ul>
<script nonce="${nonce}">
  const api = acquireVsCodeApi();
  document.querySelectorAll(".chip").forEach((b) => {
    b.addEventListener("click", () => api.postMessage({ type: "command", command: b.dataset.command }));
  });
  document.querySelectorAll(".row").forEach((r) => {
    r.addEventListener("click", () => api.postMessage({ type: "open", runId: r.dataset.run }));
  });
</script>
</body>
</html>`;
}
