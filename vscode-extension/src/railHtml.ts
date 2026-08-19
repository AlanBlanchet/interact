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
export type Voice = { mark: string; word: string; phrase: string; accent: string; tinted: boolean };

export function railHtml(
  rail: Rail,
  nonce: string,
  /** How each status is spoken — the SAME vocabulary the workplace stamps. See `statusLanguage.ts`. */
  voiceOf: (attention: string) => Voice,
  /** What each row can be asked to do. Passed in rather than imported so this module keeps no
   *  runtime import — the test loader demands ".ts" specifiers that tsc refuses to emit. */
  actionsFor: (run: Rail["runs"][number]["run"]) => AgentAction[] = () => [],
): string {
  const chips = rail.chips
    .map((c) => `<button class="chip" data-command="${esc(c.command)}">${esc(c.label)}</button>`)
    .join("");

  const rows = rail.runs.map((r) => {
    const voice = voiceOf(r.attention);
    return `
      <li class="row" data-run="${esc(r.run.run_id)}" data-attention="${esc(r.attention)}"${
        r.depth ? ' data-report="1"' : ""}${r.brain ? ' data-brain="1"' : ""}
        style="--accent: var(${esc(voice.tinted ? voice.accent : "--vscode-descriptionForeground")})">
        <span class="mark">${esc(voice.mark)}</span>
        <span class="who">${esc(r.run.name || r.run.run_id.slice(0, 8))}${
          r.brain ? '<span class="brain" title="the agent you asked — it put the others to work">brain</span>' : ""}</span>
        <span class="stamp">${esc(voice.word)}</span>
        <span class="note">${esc(r.note)}</span>
        <span class="acts">${actionsFor(r.run).map((a) =>
          `<button class="act" data-action="${esc(a.id)}" data-command="${esc(a.command)}"` +
          ` title="${esc(a.label)}">${a.mark}</button>`).join("")}</span>
      </li>`;
  }).join("");

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
  grid-template-columns: 16px minmax(0, auto) auto minmax(0, 1fr);
  gap: 6px; align-items: baseline;
  padding: 3px 10px; cursor: pointer;
}
/* The same word the world stamps on paper, in the same accent — a list row cannot tilt a ribbon
   without looking silly, so it borrows the vocabulary and leaves the idiom alone. */
.stamp {
  font-size: .78em; font-weight: 700; letter-spacing: .06em;
  padding: 0 5px; border-radius: 3px; white-space: nowrap;
  color: var(--accent, var(--vscode-foreground));
  border: 1px solid color-mix(in srgb, var(--accent, var(--vscode-panel-border)) 45%, transparent);
  background: color-mix(in srgb, var(--accent, transparent) 12%, transparent);
}
.row:hover { background: var(--vscode-list-hoverBackground); }
/* Actions sit on the row itself. They are filtered to the ones that would WORK, so nothing here
   is ever a dead control — a dead menu item teaches you the whole menu is untrustworthy. */
.acts { grid-column: 1 / -1; display: flex; gap: 2px; padding: 2px 0 0 22px; }
.act {
  font: inherit; line-height: 1; padding: 1px 5px;
  border: 1px solid transparent; border-radius: 4px;
  background: transparent; color: ${DIM}; cursor: pointer;
}
.act:hover { background: var(--vscode-toolbar-hoverBackground, var(--vscode-list-hoverBackground));
  color: var(--vscode-foreground); border-color: var(--vscode-panel-border, transparent); }
.act:focus-visible { outline: 1px solid var(--vscode-focusBorder); }
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
/* Attention reads by SHAPE first; colour only reinforces it. One accent per row, supplied by the
   shared vocabulary — six near-identical rules here were how the two surfaces drifted apart. */
.mark { color: var(--accent, var(--vscode-foreground)); }
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
  document.querySelectorAll(".act").forEach((b) => {
    b.addEventListener("click", (e) => {
      // Never let an action also open the row underneath it.
      e.stopPropagation();
      api.postMessage({ type: "act", command: b.dataset.command, runId: b.closest(".row").dataset.run });
    });
  });
</script>
</body>
</html>`;
}
