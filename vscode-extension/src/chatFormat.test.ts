import { strict as assert } from "node:assert";
import { test } from "node:test";

import { chatDocument, CHAT_EMPTY_HINT, isAwaitingReply, transcriptFragment, turnClass } from "./conversationFormat.ts";

// "We have the configuration panel for interact, but not a seperate chat panel !!!!" — the
// transcript existed, but only as a read-only EDITOR tab. A chat panel lives in the side bar
// beside the agent list and lets you TALK to the agent, not just read it.

test("with no agent selected it says what to do rather than rendering blank", () => {
  const html = chatDocument({ nonce: "n1", turns: [], name: undefined, status: undefined });
  assert.match(html, new RegExp(CHAT_EMPTY_HINT));
});

test("the selected agent's name and status head the panel", () => {
  const html = chatDocument({ nonce: "n1", turns: [], name: "reviewer", status: "running" });
  assert.match(html, /reviewer/);
  assert.match(html, /running/);
});

test("the composer is present so the panel can be TALKED to, not only read", () => {
  const html = chatDocument({ nonce: "n1", turns: [], name: "reviewer", status: "done" });
  assert.match(html, /<textarea/);
});

test("a script may only run under the given nonce", () => {
  const html = chatDocument({ nonce: "abc123", turns: [], name: "r", status: "done" });
  assert.match(html, /Content-Security-Policy/);
  assert.match(html, /nonce-abc123/);
  assert.ok(!/<script(?![^>]*nonce="abc123")/.test(html), "every script must carry the nonce");
});

test("an agent name containing markup cannot break out of the header", () => {
  const html = chatDocument({
    nonce: "n1", turns: [], name: '<img src=x onerror="alert(1)">', status: "done",
  });
  assert.ok(!html.includes("<img src=x"), "the name is agent-controlled text, so it is escaped");
  assert.match(html, /&lt;img/);
});

test("a tool result full of markup is escaped too", () => {
  const html = chatDocument({
    nonce: "n1",
    turns: [{ kind: "tool_result", text: "</textarea><script>evil()</script>" }],
    name: "r",
    status: "done",
  });
  assert.ok(!html.includes("<script>evil()"), "tool output is arbitrary bytes from a file or page");
});

// An independent critic sent a message, saw nothing happen for 80s, and reported the composer
// broken. The message HAD been delivered and the reply DID arrive — but with no in-flight state,
// "working" and "broken" look identical, so the panel was lying by omission.

test("while the agent is answering, the panel says so", () => {
  const html = chatDocument({
    nonce: "n1", name: "reviewer", status: "done",
    turns: [{ kind: "message", text: "check the error paths", to_run: "r1" }],
    awaitingReply: true,
  });
  assert.match(html, /answering|waiting/i);
});

test("with no reply pending there is no waiting state", () => {
  const html = chatDocument({
    nonce: "n1", name: "reviewer", status: "done",
    turns: [{ kind: "text", text: "done" }],
    awaitingReply: false,
  });
  assert.ok(!/answering|waiting/i.test(html));
});

test("a delivered message with nothing after it means a reply is pending", () => {
  assert.equal(isAwaitingReply([{ kind: "text", text: "hi" }, { kind: "message", text: "go" }]), true);
});

test("an assistant turn after the message ends the pending state", () => {
  assert.equal(
    isAwaitingReply([{ kind: "message", text: "go" }, { kind: "text", text: "done" }]),
    false,
  );
});

test("tool activity after the message also counts as answering, not silence", () => {
  assert.equal(
    isAwaitingReply([{ kind: "message", text: "go" }, { kind: "tool", tool: "Read" }]),
    false,
  );
});

test("an empty transcript is not pending", () => {
  assert.equal(isAwaitingReply([]), false);
});

// A message rendered with no label and the generic "other" style — present in the data, but
// visually indistinguishable from noise. The whole point of the chat is that you can see who
// said what.

test("a message from a person reads as yours", () => {
  const html = chatDocument({
    nonce: "n", name: "reviewer", status: "done",
    turns: [{ kind: "message", from_run: "operator", to_run: "r1", text: "check the tests" }],
  });
  assert.match(html, /you/i);
  assert.match(html, /check the tests/);
});

test("a message from another agent names that agent", () => {
  const html = chatDocument({
    nonce: "n", name: "reviewer", status: "done",
    turns: [{ kind: "message", from_run: "perf", to_run: "r1", text: "numbers look fine" }],
  });
  assert.match(html, /perf/);
});

test("a message kind is styled as a message, not as the unknown fallback", () => {
  assert.equal(turnClass("message"), "turn turn-message");
});

test("a spawned subagent is labelled as one", () => {
  const html = chatDocument({
    nonce: "n", name: "reviewer", status: "done",
    turns: [{ kind: "spawn", text: "run the suite" }],
  });
  assert.match(html, /spawn/i);
});

// "What i want is to be able to view an active running agent, context, system prompt (a file link
// is enough), basically everything". The panel showed a transcript and nothing about what the
// agent IS — no definition, no brief, no context size, no way to reach the files.

const RUN = {
  run_id: "abcd1234-0000-0000-0000-000000000000",
  name: "code-reviewer", provider: "claude", model: "sonnet", status: "running",
  agent: "code-reviewer", task: "Review the diff for correctness",
  cwd: "/home/alan/dev/interact", project: "interact", pid: 4242,
  cost_usd: 1.25, input_tokens: 120000, output_tokens: 8000,
} as any;

test("the system prompt is reachable as a link", () => {
  const html = chatDocument({ nonce: "n", name: "code-reviewer", status: "running", turns: [],
    run: RUN, files: [{ label: "system prompt", path: "/home/alan/.claude/agents/code-reviewer.md" }] });
  assert.match(html, /system prompt/);
  assert.match(html, /code-reviewer\.md/);
});

test("the brief it was given is shown, not just its name", () => {
  const html = chatDocument({ nonce: "n", name: "code-reviewer", status: "running", turns: [], run: RUN });
  assert.match(html, /Review the diff for correctness/);
});

test("context size is shown as tokens, not only as cost", () => {
  const html = chatDocument({ nonce: "n", name: "code-reviewer", status: "running", turns: [], run: RUN });
  assert.match(html, /120,000|120k/i);
});

test("identity a person needs to find the process is there", () => {
  const html = chatDocument({ nonce: "n", name: "code-reviewer", status: "running", turns: [], run: RUN });
  for (const fact of ["claude", "sonnet", "4242", "abcd1234"]) {
    assert.ok(html.includes(fact), `missing ${fact}`);
  }
});

test("a run with no definition does not render an empty system-prompt row", () => {
  const html = chatDocument({ nonce: "n", name: "claude", status: "done", turns: [],
    run: { ...RUN, agent: null }, files: [] });
  assert.ok(!/system prompt/.test(html));
});

test("everything in the details is escaped — a task is user text", () => {
  const html = chatDocument({ nonce: "n", name: "x", status: "done", turns: [],
    run: { ...RUN, task: "<img src=x onerror=alert(1)>" } });
  assert.ok(!html.includes("<img src=x"));
});

test("a file's PATH is shown, not hidden behind a label", () => {
  // "system prompt (a file link is enough)" — the path IS the deliverable. A chip that only says
  // "system prompt" tells you a file exists somewhere; it does not tell you where.
  const html = chatDocument({ nonce: "n", name: "g", status: "done", turns: [], run: RUN,
    files: [{ label: "system prompt", path: "/home/alan/.claude/agents/g.md" }] });
  assert.match(html, /\/home\/alan\/\.claude\/agents\/g\.md/);
});

// Watching a response arrive means the view UPDATES, not reloads. Replacing the whole document on
// every registry write threw away scroll position and whatever was half-typed in the composer.

test("the transcript can be rendered on its own, for patching in", () => {
  const html = transcriptFragment({
    turns: [{ kind: "text", text: "hello" }], name: "r", awaitingReply: false,
  });
  assert.match(html, /hello/);
  assert.ok(!/<html|<body|<script/.test(html), "a fragment, not a document");
});

test("the fragment carries the answering state too", () => {
  const html = transcriptFragment({ turns: [], name: "r", awaitingReply: true });
  assert.match(html, /answering/i);
});

test("a sub-agent says who sent it — that is half of 'its own context'", () => {
  const html = chatDocument({
    nonce: "n", name: "researcher", status: "running", turns: [],
    run: { ...RUN, name: "researcher", agent: "researcher" } as any,
    sentBy: "reviewer",
  });
  assert.match(html, /sent by/i);
  assert.match(html, /reviewer/);
});

test("a top-level run does not claim a sender it never had", () => {
  const html = chatDocument({ nonce: "n", name: "r", status: "running", turns: [], run: RUN });
  assert.ok(!/sent by/i.test(html));
});
