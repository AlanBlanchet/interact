import { strict as assert } from "node:assert";
import { test } from "node:test";

import { chatDocument, CHAT_EMPTY_HINT, isAwaitingReply, turnClass } from "./conversationFormat.ts";

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
