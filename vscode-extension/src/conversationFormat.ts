/** Rendering an agent's transcript — the pure half, so it is testable without VS Code.
 *
 *  This is a CONVERSATION, not a log dump: the model's turns, the tools it called with their
 *  arguments, and what came back. Reading `visual-critic` work should feel like reading the chat,
 *  which is why each kind gets its own shape rather than one uniform grey line.
 *
 *  Everything from an agent is UNTRUSTED text — a tool result can contain arbitrary bytes from a
 *  file or a web page — so it is escaped here, once, rather than at each call site.
 */

export interface Turn {
  kind: string;
  text?: string;
  tool?: string | null;
  tool_input?: string;
}

/** Escape for HTML text AND attribute contexts. The webview's CSP blocks inline scripts, but a
 *  broken-out tag would still wreck the layout — and a tool result is arbitrary bytes. */
export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** One CSS class per kind, so the eye can separate speech from machinery. An unknown kind falls
 *  back to `other` rather than going unstyled — a future provider event must still render. */
export function turnClass(kind: string): string {
  const known = ["text", "thinking", "tool", "tool_result", "started", "done", "error", "rate_limit"];
  return `turn turn-${known.includes(kind) ? kind : "other"}`;
}

/** Events that are about the RUN, not the conversation. A "five_hour limit: allowed" rendered
 *  between a tool call and its own result broke the one sequence a reader needs unbroken, so
 *  infrastructure is kept out of the turn stream entirely — it belongs in the header. */
const NOT_A_TURN = new Set(["rate_limit", "started", "done", "other"]);

/** Long output has to be cut HERE. The panel runs with scripts disabled (agent output is
 *  untrusted), so a click-to-expand can never be retrofitted — an uncut 50-line result is simply
 *  a wall the reader scrolls past. Keep the head, say what was hidden. */
const MAX_LINES = 14;

function clipLines(text: string): string {
  const lines = text.split("\n");
  if (lines.length <= MAX_LINES) return text;
  const hidden = lines.length - MAX_LINES;
  return `${lines.slice(0, MAX_LINES).join("\n")}\n… ${hidden} more line${hidden > 1 ? "s" : ""}`;
}

const LABEL: Record<string, string> = {
  text: "assistant",
  thinking: "thinking",
  tool_result: "result",
  started: "session",
  done: "finished",
  error: "error",
  rate_limit: "rate limit",
};

/** One turn as HTML. A tool call leads with its NAME and carries its arguments beneath, because
 *  the name alone ("used Bash") is the status line the tree already shows. */
export function renderTurn(turn: Turn): string {
  const cls = turnClass(turn.kind);
  if (turn.kind === "tool") {
    const name = escapeHtml(turn.tool || "tool");
    const args = turn.tool_input ? `<pre class="args">${escapeHtml(turn.tool_input)}</pre>` : "";
    return `<div class="${cls}"><div class="who">🔧 ${name}</div>${args}</div>`;
  }
  if (NOT_A_TURN.has(turn.kind)) return ""; // run infrastructure, not something the agent said
  const label = LABEL[turn.kind] ?? escapeHtml(turn.kind);
  const raw = turn.text ?? "";
  if (!raw.trim()) return "";
  const body = escapeHtml(clipLines(raw));
  const tag = turn.kind === "tool_result" ? "pre" : "div";
  // `result-of` marks the result as belonging to the call above it, so the two read as one unit
  // rather than as two unrelated blocks.
  const attach = turn.kind === "tool_result" ? " result-of" : "";
  return `<div class="${cls}${attach}"><div class="who">${label}</div><${tag} class="body">${body}</${tag}></div>`;
}

/** The whole transcript, oldest first — a conversation reads top to bottom, unlike the tree's
 *  newest-first tail. Empty turns are dropped so system noise doesn't pad it out. */
export function renderTranscript(turns: Turn[]): string {
  const html = turns.map(renderTurn).filter(Boolean).join("\n");
  return html || '<div class="turn turn-other"><div class="body">No activity recorded yet.</div></div>';
}

/* ── The chat panel ──────────────────────────────────────────────────────────────────────────
 *
 *  The tree answers "what is running" and the conversation tab answers "what happened". Neither
 *  let you SAY anything: the panel was a window, not a conversation. This is the surface that
 *  talks back — the same transcript with a composer under it, living in the side bar beside the
 *  agent list rather than as an editor tab you have to summon.
 *
 *  It lives here, beside the renderer it uses, because the escaping rule must be shared: an
 *  agent's name, its output, and a tool result are all arbitrary bytes from a file or a web page.
 */

/** Shown when nothing is selected — a blank panel reads as broken rather than as ready. */
export const CHAT_EMPTY_HINT = "Pick an agent in the list above to read and reply to it";

export interface ChatDocument {
  /** Per-render nonce: the CSP admits only scripts carrying it, so injected markup cannot run. */
  nonce: string;
  turns: Turn[];
  name: string | undefined;
  status: string | undefined;
}

export function chatDocument({ nonce, turns, name, status }: ChatDocument): string {
  const header = name
    ? `<header><span class="who">${escapeHtml(name)}</span>` +
      `<span class="status">${escapeHtml(status ?? "")}</span></header>`
    : "";
  const body = name
    ? renderTranscript(turns)
    : `<p class="hint">${escapeHtml(CHAT_EMPTY_HINT)}</p>`;
  const composer = name
    ? `<form id="composer">
         <textarea id="message" rows="3" placeholder="Reply to ${escapeHtml(name)}…"
                   aria-label="Message this agent"></textarea>
         <button type="submit">Send</button>
       </form>`
    : "";
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>${STYLE}</style>
</head>
<body>
${header}
<main id="transcript">${body}</main>
${composer}
<script nonce="${nonce}">
const vscode = acquireVsCodeApi();
const form = document.getElementById("composer");
if (form) {
  const box = document.getElementById("message");
  const send = () => {
    const text = box.value.trim();
    if (!text) return;
    vscode.postMessage({ type: "send", text });
    box.value = "";
  };
  form.addEventListener("submit", (e) => { e.preventDefault(); send(); });
  // Enter sends, Shift+Enter makes a new line — the shape every chat box has.
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
}
const main = document.getElementById("transcript");
if (main) main.scrollTop = main.scrollHeight;
</script>
</body>
</html>`;
}

//: Themed entirely from VS Code's own variables so the panel belongs to whatever theme is set.
const STYLE = `
  body { margin: 0; display: flex; flex-direction: column; height: 100vh;
         font-family: var(--vscode-font-family); font-size: var(--vscode-font-size);
         color: var(--vscode-foreground); background: var(--vscode-sideBar-background); }
  header { display: flex; align-items: baseline; gap: .5em; padding: .6em .8em;
           border-bottom: 1px solid var(--vscode-panel-border); }
  .who { font-weight: 600; }
  .status { color: var(--vscode-descriptionForeground); font-size: .9em; }
  #transcript { flex: 1; overflow-y: auto; padding: .6em .8em; }
  .hint { color: var(--vscode-descriptionForeground); }
  .turn { margin: 0 0 .7em; line-height: 1.45; }
  .turn-thinking { color: var(--vscode-descriptionForeground); font-style: italic; }
  .turn-tool, .turn-tool_result { font-family: var(--vscode-editor-font-family);
           background: var(--vscode-textCodeBlock-background); border-radius: 4px; padding: .4em .6em;
           white-space: pre-wrap; overflow-wrap: anywhere; }
  .turn-error { color: var(--vscode-errorForeground); }
  #composer { display: flex; flex-direction: column; gap: .4em; padding: .6em .8em;
              border-top: 1px solid var(--vscode-panel-border); }
  textarea { resize: vertical; font: inherit; color: var(--vscode-input-foreground);
             background: var(--vscode-input-background);
             border: 1px solid var(--vscode-input-border, transparent); border-radius: 4px;
             padding: .4em; }
  button { align-self: flex-end; font: inherit; cursor: pointer; border: none; border-radius: 4px;
           padding: .35em 1em; color: var(--vscode-button-foreground);
           background: var(--vscode-button-background); }
  button:hover { background: var(--vscode-button-hoverBackground); }
`;
