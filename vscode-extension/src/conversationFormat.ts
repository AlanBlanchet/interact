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
  /** For a message: who sent it. "operator" is a person, anything else is another agent. */
  from_run?: string | null;
  to_run?: string | null;
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
  const known = ["text", "thinking", "tool", "tool_result", "started", "done", "error",
                 "rate_limit", "message", "prompt", "spawn"];
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
  prompt: "you",
  spawn: "spawned",
};

/** Who a message is from, as the reader sees it. Unlabelled, an incoming message looked like
 *  noise — and the point of this panel is being able to tell who said what. */
function messageLabel(turn: Turn): string {
  const from = turn.from_run;
  if (!from || from === "operator") return "you";
  return `from ${from}`;
}

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
  const label = turn.kind === "message"
    ? escapeHtml(messageLabel(turn))
    : LABEL[turn.kind] ?? escapeHtml(turn.kind);
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

/** A file the panel can open for you — the point of a link rather than a path you copy out. */
export interface ChatFile {
  label: string;
  path: string;
}

/** What a run IS, as opposed to what it has said. */
export interface ChatRun {
  run_id: string;
  provider?: string;
  model?: string | null;
  agent?: string | null;
  task?: string;
  cwd?: string;
  pid?: number | null;
  cost_usd?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
}

export interface ChatDocument {
  /** Per-render nonce: the CSP admits only scripts carrying it, so injected markup cannot run. */
  nonce: string;
  turns: Turn[];
  name: string | undefined;
  status: string | undefined;
  /** The run behind the transcript — its definition, brief, context size and identity. Without
   *  it the panel says what an agent SAID and nothing about what it IS. */
  run?: ChatRun;
  /** Files worth opening: the system prompt, the raw stream, the transcript. */
  files?: ChatFile[];
  /** Who sent this agent out, by name. Half of "its own context" is knowing whose errand it is. */
  sentBy?: string | null;
  /** A message has been delivered and nothing has come back yet. Without this the panel looks
   *  identical whether the agent is thinking or the send silently failed — a reviewer read the
   *  silence as a broken button while the reply was on its way. */
  awaitingReply?: boolean;
}

/** Just the transcript, for patching into a live view.
 *
 *  The panel used to be re-rendered by replacing the whole document, which threw away the scroll
 *  position and anything half-typed in the composer every time the registry changed — the exact
 *  moments you are watching. The document is built once; this is what gets swapped after.
 */
export function transcriptFragment(
  { turns, name, awaitingReply }: { turns: Turn[]; name: string | undefined; awaitingReply?: boolean },
): string {
  const pending = awaitingReply
    ? `<p class="pending">${escapeHtml(name ?? "the agent")} is answering…</p>`
    : "";
  return renderTranscript(turns) + pending;
}

export function chatDocument(
  { nonce, turns, name, status, awaitingReply, run, files, sentBy }: ChatDocument,
): string {
  const header = name
    ? `<header><span class="who">${escapeHtml(name)}</span>` +
      `<span class="status">${escapeHtml(status ?? "")}</span></header>`
    : "";
  const pending = awaitingReply
    ? `<p class="pending">${escapeHtml(name ?? "the agent")} is answering…</p>`
    : "";
  const body = name
    ? renderDetails(run, files, sentBy) + renderTranscript(turns) + pending
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
// A webview cannot open a workspace file itself, so a file button asks the extension to.
// Delegated from the document: the transcript is re-rendered on every registry change, and
// per-node listeners attached at load are lost the moment that happens.
document.addEventListener("click", (event) => {
  const target = event.target;
  const button = target && target.closest ? target.closest(".file") : null;
  if (!button) return;
  event.preventDefault();
  vscode.postMessage({ type: "open", path: button.getAttribute("data-path") });
});
const main = document.getElementById("transcript");
// Stick to the bottom only while the reader IS at the bottom: yanking someone back down while
// they are reading further up is worse than not following at all.
function atBottom() {
  return !main || main.scrollHeight - main.scrollTop - main.clientHeight < 40;
}
function follow(wasAtBottom) {
  if (main && wasAtBottom) main.scrollTop = main.scrollHeight;
}
// Later turns arrive as a PATCH, not a reload — a reload would discard the scroll position and
// whatever is half-typed in the composer, which is exactly when you are watching.
window.addEventListener("message", (event) => {
  const msg = event.data;
  if (!msg || msg.type !== "transcript" || !main) return;
  const wasAtBottom = atBottom();
  main.innerHTML = msg.html;
  follow(wasAtBottom);
});
follow(true);
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
  .pending { color: var(--vscode-descriptionForeground); font-style: italic; }
  .details { margin: 0 0 .8em; font-size: .95em; }
  .details summary { cursor: pointer; color: var(--vscode-descriptionForeground); }
  .details .grid { display: grid; grid-template-columns: auto 1fr; gap: .15em .8em; margin: .5em 0; }
  .details .k { color: var(--vscode-descriptionForeground); }
  .details .v { overflow-wrap: anywhere; font-family: var(--vscode-editor-font-family); }
  .details .brief p { margin: .2em 0 .6em; white-space: pre-wrap; }
  .details .files { margin-top: .5em; }
  .details .file { color: var(--vscode-textLink-foreground); overflow-wrap: anywhere; }
  .pending::after { content: ""; animation: blink 1.2s steps(1) infinite; }
  @keyframes blink { 50% { opacity: .4 } }
  .turn { margin: 0 0 .7em; line-height: 1.45; }
  .turn-thinking { color: var(--vscode-descriptionForeground); font-style: italic; }
  .turn-tool, .turn-tool_result { font-family: var(--vscode-editor-font-family);
           background: var(--vscode-textCodeBlock-background); border-radius: 4px; padding: .4em .6em;
           white-space: pre-wrap; overflow-wrap: anywhere; }
  .turn-error { color: var(--vscode-errorForeground); }
  /* What YOU (or another agent) said — set apart from the agent's own turns, so a conversation
     reads as two sides rather than one voice. */
  .turn-message, .turn-prompt { background: var(--vscode-textBlockQuote-background);
           border-left: 2px solid var(--vscode-textBlockQuote-border, var(--vscode-focusBorder));
           border-radius: 3px; padding: .4em .6em; }
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


/** Whether a message has been delivered with nothing back yet.
 *
 *  Derived from the transcript rather than from a flag the send sets, so it survives a reload and
 *  is true for a message sent from anywhere — the composer, the row icon, another agent, the CLI.
 */
export function isAwaitingReply(turns: Turn[]): boolean {
  for (let i = turns.length - 1; i >= 0; i--) {
    if (turns[i].kind === "message") return true;
    // Anything the agent itself produced after the message means it is already answering.
    if (["text", "thinking", "tool", "tool_result", "done", "error"].includes(turns[i].kind)) {
      return false;
    }
  }
  return false;
}

/** A real link that opens the file.
 *
 *  A `command:` URI is VS Code's own mechanism for this and needs no message plumbing — the
 *  earlier attempt posted a message from a click handler, and the handler never fired for reasons
 *  the markup and the compiled bundle both denied. This is documented, and it is also literally
 *  what was asked for: a file link.
 */
function fileLink(file: ChatFile): string {
  const args = encodeURIComponent(JSON.stringify([`file://${file.path}`]));
  // The PATH is shown, not just the label: it is what was actually asked for, it survives a
  // link the workbench declines to follow, and it can be copied into a terminal.
  return (
    `<div class="k">${escapeHtml(file.label)}</div>` +
    `<div class="v"><a class="file" href="command:vscode.open?${args}">` +
    `${escapeHtml(file.path)}</a></div>`
  );
}

/** Compact token counts — "120k" reads at a glance where "120000" does not. */
function tokens(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
}

/** What the agent IS, above what it has said: its definition, its brief, how much context it has
 *  consumed, and the identity you need to find the process. Collapsed by default — the
 *  conversation is what you came for; this is what you open when you want to know why it behaves
 *  the way it does.
 *
 *  Files are BUTTONS, not links: a webview cannot open a workspace file itself, so each posts a
 *  message and the extension opens it in an editor.
 */
export function renderDetails(
  run: ChatRun | undefined,
  files: ChatFile[] | undefined,
  sentBy?: string | null,
): string {
  if (!run) return "";
  const rows: [string, string][] = [];
  if (run.agent) rows.push(["definition", run.agent]);
  if (sentBy) rows.push(["sent by", sentBy]);
  rows.push(["provider", [run.provider, run.model].filter(Boolean).join(" · ") || "—"]);
  rows.push([
    "context",
    `${tokens(run.input_tokens)} in · ${tokens(run.output_tokens)} out` +
      (run.cost_usd != null ? ` · ~$${run.cost_usd.toFixed(4)}` : ""),
  ]);
  if (run.cwd) rows.push(["working dir", run.cwd]);
  rows.push(["process", run.pid ? String(run.pid) : "not running"]);
  rows.push(["session", run.run_id]);

  const table = rows
    .map(([k, v]) => `<div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(v)}</div>`)
    .join("");
  const brief = run.task
    ? `<div class="brief"><div class="k">brief</div><p>${escapeHtml(run.task)}</p></div>`
    : "";
  const links = (files ?? []).length
    ? `<div class="grid files">${(files ?? []).map(fileLink).join("")}</div>`
    : "";
  return `<details class="details"><summary>about this agent</summary>
    <div class="grid">${table}</div>${brief}${links}</details>`;
}
