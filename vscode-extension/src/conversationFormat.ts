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
  /** A command the panel can run, passed IN rather than imported: this module is loaded directly
   *  by its test under --experimental-strip-types, which needs `.ts` specifiers that tsc refuses
   *  when emitting, so it stays import-free. The list lives in `chatCommands.ts`. */
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

/** How much of a long block is shown before it folds. The rest is one click away, not gone.
 *
 *  This used to CUT at 14 lines and say how many were hidden, justified by a comment claiming the
 *  panel runs with scripts disabled so expansion "can never be retrofitted". That was stale — the
 *  document carries a nonce'd script — and it was never needed anyway: `<details>` is a native
 *  disclosure that needs no script at all. Truncating a tool result to fourteen lines and offering
 *  no way to see the rest is exactly the wall it was trying to avoid.
 */
const FOLD_AFTER_LINES = 14;
/** Also fold on sheer length: a tool result is frequently ONE enormous line of JSON, which has no
 *  newlines to count and so sailed past the line check and filled the panel. */
const FOLD_AFTER_CHARS = 1200;

/** Escaped HTML for a block, folding the tail into a native disclosure when it is long. */
function foldLongOutput(text: string): string {
  const lines = text.split("\n");
  if (lines.length > FOLD_AFTER_LINES) {
    const head = escapeHtml(lines.slice(0, FOLD_AFTER_LINES).join("\n"));
    const rest = escapeHtml(lines.slice(FOLD_AFTER_LINES).join("\n"));
    const hidden = lines.length - FOLD_AFTER_LINES;
    return `${head}<details class="more"><summary>${hidden} more line${hidden > 1 ? "s" : ""}` +
      `</summary>${rest}</details>`;
  }
  if (text.length > FOLD_AFTER_CHARS) {
    const hidden = text.length - FOLD_AFTER_CHARS;
    return `${escapeHtml(text.slice(0, FOLD_AFTER_CHARS))}` +
      `<details class="more"><summary>${hidden} more characters</summary>` +
      `${escapeHtml(text.slice(FOLD_AFTER_CHARS))}</details>`;
  }
  return escapeHtml(text);
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
  const escaped = foldLongOutput(raw);
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
  /** How much this run was allowed to do on its own, in the words a person chose it by. Absent
   *  when nobody chose, which is not the same as unrestricted and must not read like it. */
  permission?: { label: string; unrestricted: boolean } | null;
}

export interface ChatDocument {
  /** What the whole team is costing and this agent's share. Passed in for the same reason the
   *  commands are: this module stays import-free so its test can load it directly. */
  spend?: { total: number; agents: number; running: number; sharePercent: number | null };
  /** What the panel can DO, not just say. Passed in rather than imported so this module stays
   *  import-free — its test loads it directly under --experimental-strip-types, which needs `.ts`
   *  specifiers that tsc refuses when emitting. The list itself lives in `chatCommands.ts`.
   *
   *  REQUIRED, deliberately. It was optional, and the one production caller never passed it — so
   *  the "/" button opened an empty list in every state while both sides passed their own unit
   *  tests. `noUnusedLocals` cannot catch that shape: `CHAT_COMMANDS` IS imported and IS used, to
   *  validate inbound messages, just never handed to the renderer. Making it required moves the
   *  check to the compiler, where forgetting it is impossible rather than merely untested. */
  commands: {
    slash: string;
    title: string;
    detail: string;
    command: string;
    needsAgent: boolean;
  }[];
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
  { nonce, turns, name, status, awaitingReply, run, files, sentBy, commands, spend }: ChatDocument,
): string {
  const header = name
    ? `<header><span class="who">${escapeHtml(name)}</span>` +
      `<span class="status">${escapeHtml(status ?? "")}</span></header>`
    : "";
  const pending = awaitingReply
    ? `<p class="pending">${escapeHtml(name ?? "the agent")} is answering…</p>`
    : "";
  const body = name
    ? renderDetails(run, files, sentBy, spend) + renderTranscript(turns) + pending
    : `<p class="hint">${escapeHtml(CHAT_EMPTY_HINT)}</p>`;
  // The panel could only SEND. Everything else you might want to do with the agent you are
  // reading — stop it, start another, open the team, change workspace — lived in a tree context
  // menu or the command palette. All three reference tools put this behind a slash menu in the
  // panel itself, so this does too, and the same list drives the button.
  const menu = (commands ?? []).map((c) =>
    `<li role="option" data-command="${escapeHtml(c.command)}" data-slash="${escapeHtml(c.slash)}"` +
    `${c.needsAgent && !name ? ' data-needs-agent="1"' : ""}>` +
    `<b>${escapeHtml(c.slash)}</b><span>${escapeHtml(c.title)}</span>` +
    `<i>${escapeHtml(c.detail)}</i></li>`).join("");
  // ALWAYS rendered, agent or no agent. It used to appear only once you had selected somebody,
  // which meant a resting panel offered no controls whatsoever: the tree's title icons are hidden
  // until the pointer enters the header (VS Code shows `.pane-header > .actions` only on
  // hover/focus, and clips the rest — there is no overflow menu), and this half contributed
  // nothing at all. So on a cold start the whole panel had no visible way to reach the team, the
  // workspace switcher, or anything else. Thirteen labelled commands live behind this button; the
  // ones needing an agent already grey themselves out, which is a far better answer than hiding
  // the entire surface.
  const composer = `<form id="composer">
         <ul id="palette" role="listbox" aria-label="Commands" hidden>${menu}</ul>
         <textarea id="message" rows="3" ${name ? "" : "disabled "}placeholder="${
           name ? `Reply to ${escapeHtml(name)}…  (/ for commands)`
                : "Pick an agent to reply — or press / for the panel's commands"}"
                   aria-label="Message this agent"></textarea>
         <div class="controls">
           <button type="button" id="cmds" title="Commands">/</button>
           <button type="submit"${name ? "" : " disabled"}>Send</button>
         </div>
       </form>`;
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
  // The box empties optimistically — a chat that lags behind your typing feels broken — but the
  // text is KEPT until the host confirms it went. It used to be discarded on submit, so a send
  // that failed (the agent had ended, the CLI was not on PATH) left you with a toast and no
  // message: you lost what you wrote, which is the one thing a chat box must never do.
  let inFlight = "";
  const send = () => {
    const text = box.value.trim();
    if (!text) return;
    inFlight = text;
    vscode.postMessage({ type: "send", text });
    box.value = "";
    box.setAttribute("data-sending", "1");
  };
  window.addEventListener("message", (event) => {
    const msg = event.data;
    if (!msg || msg.type !== "sent") return;
    box.removeAttribute("data-sending");
    if (msg.ok) { inFlight = ""; return; }
    // Put it back exactly as written, and put the cursor where they left it, so the fix is to
    // press Enter again rather than to retype from memory.
    if (inFlight && !box.value) box.value = inFlight;
    inFlight = "";
    box.focus();
  });
  // A slash menu, driven by the same list the markup was built from. Typing "/" opens it, arrows
  // and Enter pick, Escape closes — the shape every one of the reference panels uses.
  const palette = document.getElementById("palette");
  const items = () => Array.from(palette.querySelectorAll("li")).filter((li) => !li.hidden);
  let cursor = 0;
  const paint = () => {
    items().forEach((li, i) => li.setAttribute("aria-selected", String(i === cursor)));
  };
  const openPalette = (typed) => {
    // Double-escaped on purpose: this script lives inside a template literal, so a single
    // backslash is consumed as a string escape and the regex silently becomes /s/ — which split
    // every prefix down to "/" and made the menu appear to ignore what was typed.
    const prefix = (typed || "/").trimStart().split(/\\s/)[0].toLowerCase();
    let any = false;
    palette.querySelectorAll("li").forEach((li) => {
      const match = li.dataset.slash.startsWith(prefix);
      li.hidden = !match;
      any = any || match;
    });
    palette.hidden = !any;
    cursor = 0;
    paint();
  };
  const closePalette = () => { palette.hidden = true; };
  const run = (li) => {
    if (!li || li.dataset.needsAgent) return;
    vscode.postMessage({ type: "command", command: li.dataset.command });
    box.value = "";
    closePalette();
  };
  document.getElementById("cmds").addEventListener("click", () => {
    if (palette.hidden) { openPalette("/"); box.focus(); } else closePalette();
  });
  palette.addEventListener("click", (e) => {
    const li = e.target.closest ? e.target.closest("li") : null;
    if (li) run(li);
  });
  box.addEventListener("input", () => {
    const text = box.value.trimStart();
    if (text.startsWith("/")) openPalette(text); else closePalette();
  });
  // "@" mentions a file. A webview cannot read the workspace, so it asks the extension to offer
  // one and inserts whatever comes back — the same shape all three reference panels use, and the
  // reason briefing an agent about a file no longer means typing a path from memory.
  box.addEventListener("keydown", (e) => {
    if (e.key === "@") {
      e.preventDefault();
      vscode.postMessage({ type: "pickFile" });
    }
  });
  window.addEventListener("message", (event) => {
    const msg = event.data;
    if (msg && msg.type === "insert" && typeof msg.text === "string") {
      const at = box.selectionStart ?? box.value.length;
      box.value = box.value.slice(0, at) + msg.text + box.value.slice(at);
      box.focus();
      box.selectionStart = box.selectionEnd = at + msg.text.length;
    }
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); send(); });
  // Enter sends, Shift+Enter makes a new line — the shape every chat box has.
  box.addEventListener("keydown", (e) => {
    if (!palette.hidden) {
      const list = items();
      if (e.key === "ArrowDown") { e.preventDefault(); cursor = (cursor + 1) % list.length; paint(); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); cursor = (cursor - 1 + list.length) % list.length; paint(); return; }
      if (e.key === "Escape") { e.preventDefault(); closePalette(); return; }
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(list[cursor]); return; }
    }
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
  /* On BODY, not :root. VS Code injects the live --vscode-* theme variables as an inline style
     on the body element, and :root (the html element) is body's ANCESTOR — so a var() reading them from :root never
     resolves and silently falls back. This panel was therefore permanently dark whatever theme
     the user had chosen, and it looked deliberate. workplace/style.ts scopes its tokens to a
     body DESCENDANT, which is why the same block works there. */
  body {
    --wp-bg: var(--vscode-sideBar-background, var(--vscode-editor-background, #1e1e1e));
    --wp-fg: var(--vscode-editor-foreground, #d4d4d4);
    /* NOT the raw token. VS Code's own Light theme ships descriptionForeground at #767676 on
       #f8f8f8 — 4.28:1 nominal, under the AA floor before this panel touches it — and this is the
       label saying WHO spoke, not decoration. Dark clears it comfortably, which is why it went
       unseen until the light theme first rendered. Pulled toward the foreground, the same
       treatment --wp-ink and --wp-plate already get here. */
    --wp-dim: color-mix(in srgb, var(--vscode-descriptionForeground, #9a9a9a) 70%, var(--vscode-editor-foreground, #d4d4d4));
    --wp-ink: color-mix(in srgb, var(--wp-fg) 62%, var(--wp-bg));
    --wp-line: color-mix(in srgb, var(--wp-fg) 26%, var(--wp-bg));
    --wp-wall: color-mix(in srgb, var(--wp-fg) 7%, var(--wp-bg));
    /* Carries background-coloured text, so it is light enough to read against the background. */
    /* 90%, not 82%: the plate carries BACKGROUND-coloured letters at 10-11px, and at 82% the
       pair measured 7.3:1 nominal — which is a good deal less than that once anti-aliasing is
       counted, on text this small. Lighter plate, same device, comfortably readable. */
    --wp-plate: color-mix(in srgb, var(--wp-fg) 90%, var(--wp-bg));
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
  /* No opacity. The header is a light plate carrying background-coloured letters, so fading the
     word composites it toward the plate it sits on — the same way the workplace nameplate and
     three of the sidebar's devices lost their contrast. Said quieter with size and weight, which
     cost nothing legible; see plateContrast.test.ts. */
  /* 11px at 600. Removing the opacity was necessary and not sufficient: at 500/10px the glyphs
     never reach solid ink, so the composited reading stayed near 2.4:1 however good the colour
     pair was. Weight and size are what get a small label over the line. */
  .status { font-size: 11px; font-weight: 600; letter-spacing: .04em; }
  /* An explicit focus ring rather than the UA's outline:auto, whose rendering against a dark
     webview background could not be settled from a static harness — ambiguity is not a thing to
     ship on a keyboard path. */
  textarea:focus-visible, button:focus-visible {
    outline: 2px solid var(--vscode-focusBorder, #4f9cf5); outline-offset: 1px; }

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
  /* Machine detail RECEDES. It used to wear the same wall-and-ink panel as a spoken message, so
     a tool call and something you actually said were four identical grey plates — and the
     assistant's own prose, which carries no plate at all, was the quietest thing on a screen whose
     whole job is the conversation. The hierarchy was upside down: loudest for the machine,
     nothing for the voice. Now a tool is a quiet inset with a rule down its left, prose is the
     unadorned primary flow, and a spoken turn is the only thing that gets a plate. */
  .turn-tool, .turn-tool_result { font-family: var(--vscode-editor-font-family);
           font-size: .92em; color: var(--wp-dim);
           border-left: 2px solid var(--wp-line); padding: .15em 0 .15em .6em;
           white-space: pre-wrap; overflow-wrap: break-word; }
  .turn-tool .who, .turn-tool_result .who { font-size: 9px; }
  /* A call and its result are ONE thing. The markup has said so since it was written — the result
     carries a result-of class — but no rule ever targeted it, so the two sat a full inter-turn gap apart
     with a broken rule between them, reading as two unrelated blocks. Closing the gap and running
     the rule through is the whole of what the comment always claimed. */
  .turn-tool { margin-bottom: 0; }
  .turn.result-of { margin-top: 0; padding-top: 0; }
  .turn.result-of .who { padding-top: .25em; }
  /* The container's pre-wrap is INHERITED, and the UA stylesheet's own pre{white-space:pre}
     beats an inherited value on the element itself — so a <pre> inside these blocks kept running
     off the panel. At a 300px side bar that cuts a tool's path or result mid-word, which is the
     one surface the tools are here to show. */
  .turn-tool pre, .turn-tool_result pre, .turn .body pre, pre.args {
           white-space: pre-wrap; overflow-wrap: break-word; margin: 0; }
  /* An error is the one turn most worth noticing, and it had nothing but a hue shift on the body
     text — its label stayed the same dim grey as every other label, so it read as ordinary prose.
     Given the same weight as a voice, in the error colour rather than the accent. */
  .turn-error { color: var(--vscode-errorForeground);
           background: color-mix(in srgb, var(--vscode-errorForeground, #e06c75) 9%, var(--wp-bg));
           border: 1px solid color-mix(in srgb, var(--vscode-errorForeground, #e06c75) 38%, var(--wp-bg));
           border-left-width: 3px; padding: .4em .6em; }
  .turn-error .who { color: var(--vscode-errorForeground); }
  /* A VOICE — you, or another agent talking to this one. The one thing on this surface that is
     somebody speaking, so it is the one thing that gets a plate, and it carries the accent down
     its edge so it cannot be mistaken for a machine panel at a glance. */
  .turn-message, .turn-prompt {
           background: color-mix(in srgb, var(--vscode-focusBorder, #4f9cf5) 10%, var(--wp-bg));
           border: 1px solid color-mix(in srgb, var(--vscode-focusBorder, #4f9cf5) 34%, var(--wp-bg));
           border-left-width: 3px;
           box-shadow: 2px 2px 0 0 var(--wp-ink); padding: .4em .6em; }
  .turn-message .who, .turn-prompt .who {
           color: color-mix(in srgb, var(--vscode-focusBorder, #4f9cf5) 62%, var(--wp-fg)); }
  /* The fold on a long block: a quiet control, not another plate. */
  .more > summary { cursor: pointer; color: var(--wp-dim); font-size: .92em; padding: .1em 0; }
  .more[open] > summary { margin-bottom: .2em; }

  /* The command menu. Above the box rather than below it: the composer sits at the bottom of the
     panel, so a list that opened downward would be off-screen. */
  #composer { position: relative; }
  .controls { display: flex; gap: .4em; align-self: flex-end; align-items: stretch; }
  #cmds { min-width: 34px; padding: .6em .7em; font-weight: 700;
          background: var(--wp-wall); color: var(--wp-fg); }
  #palette { position: absolute; bottom: 100%; left: 0; right: 0; margin: 0 0 .4em; padding: .2em;
             list-style: none; z-index: 5; max-height: 46vh; overflow-y: auto;
             background: var(--wp-bg); border: 1px solid var(--wp-ink);
             box-shadow: 2px 2px 0 0 var(--wp-ink); }
  #palette li { display: grid; grid-template-columns: auto 1fr; gap: 0 .5em; padding: .3em .45em;
                cursor: pointer; align-items: baseline; }
  #palette li b { font-family: var(--vscode-editor-font-family); color: var(--wp-fg); }
  #palette li span { font-weight: 600; }
  #palette li i { grid-column: 2; font-style: normal; font-size: .88em; color: var(--wp-dim); }
  #palette li[aria-selected="true"], #palette li:hover {
             background: var(--vscode-list-activeSelectionBackground, var(--wp-wall)); }
  /* An action that needs an agent, with none open, is shown and disabled rather than hidden — a
     menu whose contents change shape is harder to learn than one with a greyed row. */
  #palette li[data-needs-agent] { opacity: .45; cursor: not-allowed; }

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
  /* Measured at 55x19px, which is under every published hit-target floor. A mouse-driven desktop
     surface makes that low-stakes rather than harmless — it is still the control this panel exists
     to be used through. */
  button { align-self: flex-end; font: inherit; cursor: pointer; border: 1px solid var(--wp-ink);
           box-shadow: 2px 2px 0 0 var(--wp-ink); padding: .6em 1.2em; min-height: 32px;
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
  spend?: { total: number; agents: number; running: number; sharePercent: number | null },
): string {
  if (!run) return "";
  const rows: [string, string][] = [];
  if (run.agent) rows.push(["definition", run.agent]);
  // What the TEAM is costing, not only this one. The budget question is never about a single
  // agent, and this panel is where somebody watching the team actually looks. Equivalent spend,
  // as everywhere in interact: on a subscription run it is not billed again.
  if (spend && spend.agents > 0) {
    const share = spend.sharePercent != null ? ` · this one ${spend.sharePercent}%` : "";
    rows.push(["team", `~$${spend.total.toFixed(2)} over ${spend.agents} agent` +
      `${spend.agents > 1 ? "s" : ""}${spend.running ? `, ${spend.running} still running` : ""}${share}`]);
  }
  // Why this one stops to ask and that one just does it — the question a watcher asks about an
  // agent in flight, unanswerable from the record until it was written down. Silence when nobody
  // chose: "default" would state a policy that was never selected.
  if (run.permission) {
    rows.push(["autonomy", run.permission.unrestricted
      ? `${run.permission.label} — acts without asking`
      : run.permission.label]);
  }
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
  return `<details class="details" open><summary>about this agent</summary>
    <div class="grid">${table}</div>${brief}${links}</details>`;
}
