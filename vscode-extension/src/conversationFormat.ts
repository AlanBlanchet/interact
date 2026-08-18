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
/* ── the small subset of Markdown agents actually write ────────────────────────────────────────
 *
 *  Agents write in Markdown by habit — bold for emphasis, backticks for a path, a dash list for
 *  findings — and the chat printed it literally, so a verdict arrived as a wall of asterisks.
 *
 *  SAFETY: these run on ALREADY-ESCAPED text, so by the time a rule matches there is no angle
 *  bracket or ampersand left and nothing here can produce a tag the agent chose — the rules only
 *  INSERT markup around text that is already inert. A link is the one exception that carries a
 *  value into an attribute, so its href is restricted to http(s).
 *
 *  Lives here rather than in its own module because this repo emits CommonJS from tsc while the
 *  test runner resolves ESM: a cross-file value import would need a .ts specifier that tsc
 *  rejects while emitting. Only this file uses it. */

const FENCE = /```[a-z]*\n([\s\S]*?)```/g;
const CODE = /`([^`\n]+)`/g;
const BOLD = /\*\*([^*\n]+)\*\*/g;
// The delimiter must hug its text: "2 * 3 * 4" is arithmetic, not emphasis.
const ITALIC = /(^|[\s(])[*_](\S[^*_\n]*?\S|\S)[*_](?=[\s).,;:!?]|$)/g;
const LINK = /\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g;

/** Already-escaped text in, HTML out. Never call this on raw agent output. */
export function renderInline(escaped: string): string {
  return escaped
    .replace(LINK, (_m, text, href) => `<a href="${href.replace(/"/g, "&quot;")}">${text}</a>`)
    .replace(BOLD, "<strong>$1</strong>")
    .replace(ITALIC, "$1<em>$2</em>")
    .replace(CODE, "<code>$1</code>");
}

/** Prose: bullet lists and paragraphs. Input must already be escaped. */
function renderProse(escaped: string): string {
  const out: string[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      out.push(`<ul>${list.map((li) => `<li>${renderInline(li)}</li>`).join("")}</ul>`);
    }
    list = [];
  };
  for (const line of escaped.split("\n")) {
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    if (bullet) {
      list.push(bullet[1]);
      continue;
    }
    flush();
    out.push(line.trim() ? `<p>${renderInline(line)}</p>` : "");
  }
  flush();
  return out.filter(Boolean).join("");
}

/** A whole message body: fenced blocks, then prose. Input must already be escaped.
 *
 *  Split rather than substituted. The first version swapped each fenced block for a placeholder
 *  and put it back afterwards, which needed a character that could not occur in the text — and
 *  the one I reached for was a NUL, which is legal inside a template literal, survives the
 *  compiler, passes every test, and quietly makes the whole source file BINARY to grep and to
 *  anything else that asks what type it is. `split` on a capturing regex gives alternating prose
 *  and code with nothing to smuggle. */
export function renderMarkdown(escaped: string): string {
  // Even indices are prose, odd indices are the captured contents of a fence.
  return escaped
    .split(FENCE)
    .map((seg, i) =>
      i % 2 ? `<pre class="code">${seg.replace(/\n$/, "")}</pre>` : renderProse(seg),
    )
    .join("");
}

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
  // Agents write Markdown by habit, and the chat printed it literally — a verdict arrived as a
  // wall of asterisks. Rendered only for what an agent SAYS; a tool result is machine output and
  // stays verbatim in its pre.
  const escaped = escapeHtml(clipLines(raw));
  const body = turn.kind === "tool_result" ? escaped : renderMarkdown(escaped);
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

// "about this agent" holds the session id, the working directory and the path to the system
// prompt — the first things wanted when something looks wrong. The document is rebuilt on every
// agent switch, so a <details> reopened by hand collapsed again the moment you moved to the next
// agent: one extra click, every time, for exactly the information a debugging user came for.
// Remembered across renders in the webview's own state, which survives the rebuild.
const details = document.querySelector("details.details");
if (details) {
  const state = vscode.getState() || {};
  if (state.detailsOpen) details.open = true;
  details.addEventListener("toggle", () => {
    vscode.setState({ ...(vscode.getState() || {}), detailsOpen: details.open });
  });
}

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

//: One visual language with the workplace.
//:
//: An independent critic put it plainly: the side bar was "stock VS Code tree, plain text,
//: monospace transcript" while the team tab was "vivid custom pixel art" — "two unrelated
//: products". Both derive their colour from the same `--vscode-*` variables; what differed was
//: the TREATMENT. So the chat borrows the room's own devices: signs are uppercase and letter-
//: spaced on a light plate, panels sit on a hard 2px offset shadow with a solid ink border, and
//: nothing is rounded softer than the pixel grid allows.
const STYLE = `
  :root {
    --wp-bg: var(--vscode-sideBar-background, var(--vscode-editor-background, #1e1e1e));
    --wp-fg: var(--vscode-editor-foreground, #d4d4d4);
    --wp-dim: var(--vscode-descriptionForeground, #9a9a9a);
    --wp-ink: color-mix(in srgb, var(--wp-fg) 62%, var(--wp-bg));
    --wp-line: color-mix(in srgb, var(--wp-fg) 26%, var(--wp-bg));
    --wp-wall: color-mix(in srgb, var(--wp-fg) 7%, var(--wp-bg));
    /* Carries background-coloured text, so it is light enough to read against the background. */
    --wp-plate: color-mix(in srgb, var(--wp-fg) 82%, var(--wp-bg));
  }
  body { margin: 0; display: flex; flex-direction: column; height: 100vh;
         font-family: var(--vscode-font-family); font-size: var(--vscode-font-size);
         color: var(--wp-fg); background: var(--wp-bg); }

  /* The sign over the door, exactly as a room wears it. */
  header { display: flex; align-items: center; gap: .5em; margin: .7em .8em .4em;
           padding: 3px 9px; background: var(--wp-plate); color: var(--wp-bg);
           border: 1px solid var(--wp-ink); box-shadow: 2px 2px 0 0 var(--wp-ink);
           align-self: flex-start; }
  .who { font-weight: 700; letter-spacing: .18em; font-size: 11px; text-transform: uppercase; }
  .status { font-size: 10px; opacity: .78; }

  #transcript { flex: 1; overflow-y: auto; padding: .6em .8em; }
  .hint { color: var(--wp-dim); }
  .pending { color: var(--wp-dim); font-style: italic; }
  .pending::after { content: ""; animation: blink 1.2s steps(1) infinite; }
  @keyframes blink { 50% { opacity: .4 } }

  .turn { margin: 0 0 .7em; line-height: 1.45; }
  .turn .who { font-weight: 600; letter-spacing: .1em; font-size: 10px; text-transform: uppercase;
               color: var(--wp-dim); }
  /* Rendered Markdown. Tight margins: a chat panel is narrow and every blank line costs a line
     of transcript. The symbol fallback is there because an agent's own status glyphs were
     arriving as tofu boxes in a font that has no such block. */
  .turn .body { font-family: var(--vscode-font-family), "Noto Sans Symbols 2", "Segoe UI Symbol",
                sans-serif; }
  .turn .body p { margin: 0 0 .5em; }
  .turn .body p:last-child { margin-bottom: 0; }
  .turn .body ul { margin: .2em 0 .5em; padding-left: 1.1em; }
  .turn .body li { margin: .1em 0; }
  .turn .body code { font-family: var(--vscode-editor-font-family); font-size: .92em;
                     background: var(--wp-wall); border: 1px solid var(--wp-line);
                     padding: 0 .25em; }
  .turn .body pre.code { font-family: var(--vscode-editor-font-family); white-space: pre-wrap;
                         overflow-wrap: break-word; background: var(--wp-wall);
                         border: 1px solid var(--wp-line); padding: .4em .6em; margin: .3em 0; }
  .turn .body strong { font-weight: 700; color: var(--wp-fg); }
  .turn .body a { color: var(--vscode-textLink-foreground); }
  .turn-thinking { color: var(--wp-dim); font-style: italic; }
  /* Machine surfaces sit on the wall colour with an ink edge — the room's own panels. */
  .turn-tool, .turn-tool_result { font-family: var(--vscode-editor-font-family);
           background: var(--wp-wall); border: 1px solid var(--wp-line); padding: .4em .6em;
           white-space: pre-wrap; overflow-wrap: break-word; }
  .turn-error { color: var(--vscode-errorForeground); }
  /* What YOU or another agent said: a plate, like a worker's speech in the room. */
  .turn-message, .turn-prompt { background: var(--wp-wall); border: 1px solid var(--wp-line);
           box-shadow: 2px 2px 0 0 var(--wp-ink); padding: .4em .6em; }

  .details { margin: 0 0 .8em; font-size: .95em; }
  .details summary { cursor: pointer; color: var(--wp-dim); letter-spacing: .04em; }
  /* minmax(0, ...) on both tracks, and break-word rather than 'anywhere': 'anywhere' lets a
     track's MIN-CONTENT width fall to a single character, so the moment the sidebar narrowed —
     which is what happens the instant you click a file link and an editor opens beside it — long
     paths and session ids wrapped one glyph per line. break-word still breaks a value that does
     not fit; it just does not tell the layout the column can be 1ch wide. */
  .details .grid { display: grid; grid-template-columns: minmax(0, auto) minmax(0, 1fr);
                   gap: .15em .8em; margin: .5em 0; }
  .details .k { color: var(--wp-dim); }
  .details .v { overflow-wrap: break-word; min-width: 0;
                font-family: var(--vscode-editor-font-family); }
  /* Narrower than this, two columns cannot both be readable: stack them. */
  @media (max-width: 280px) {
    .details .grid { grid-template-columns: minmax(0, 1fr); gap: 0; }
    .details .k { margin-top: .4em; font-size: 10px; text-transform: uppercase;
                  letter-spacing: .06em; }
  }
  .details .brief p { margin: .2em 0 .6em; white-space: pre-wrap; }
  .details .files { margin-top: .5em; }
  .details .file { color: var(--vscode-textLink-foreground); overflow-wrap: break-word; }

  #composer { display: flex; flex-direction: column; gap: .4em; padding: .6em .8em;
              border-top: 1px solid var(--wp-line); }
  textarea { resize: vertical; font: inherit; color: var(--vscode-input-foreground);
             background: var(--vscode-input-background);
             border: 1px solid var(--wp-line); padding: .4em; }
  button { align-self: flex-end; font: inherit; cursor: pointer; border: 1px solid var(--wp-ink);
           box-shadow: 2px 2px 0 0 var(--wp-ink); padding: .35em 1em;
           color: var(--vscode-button-foreground); background: var(--vscode-button-background);
           letter-spacing: .08em; text-transform: uppercase; font-size: 11px; font-weight: 600; }
  button:hover { background: var(--vscode-button-hoverBackground); }
  button:active { box-shadow: 0 0 0 0 var(--wp-ink); transform: translate(2px, 2px); }
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
