import { strict as assert } from "node:assert";
import { test } from "node:test";

import { chatDocument, CHAT_EMPTY_HINT } from "./conversationFormat.ts";

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
