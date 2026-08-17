/** The conversation view's rendering decisions, tested without VS Code.
 *
 *  A transcript is the one surface where truncation, escaping and ordering go wrong silently —
 *  so the parts that can be decided as pure functions are decided here and pinned.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { escapeHtml, renderTurn, turnClass } from "./conversationFormat.ts";

test("html in a tool result cannot break out into markup", () => {
  const html = renderTurn({ kind: "tool_result", text: "<script>alert(1)</script>" });
  assert.ok(!html.includes("<script>"), "raw script tag reached the DOM");
  assert.ok(html.includes("&lt;script&gt;"));
});

test("a tool call shows its name AND its arguments", () => {
  const html = renderTurn({ kind: "tool", tool: "Bash", tool_input: "command='ls -la'" });
  assert.ok(html.includes("Bash"));
  assert.ok(html.includes("ls -la"), "a tool call without its input is just a status line");
});

test("each kind gets its own class so the transcript reads as a conversation", () => {
  assert.notEqual(turnClass("text"), turnClass("tool"));
  assert.notEqual(turnClass("thinking"), turnClass("text"));
  assert.equal(turnClass("nonsense-kind"), turnClass("other"));
});

test("escaping covers the quote characters an attribute would break on", () => {
  assert.equal(escapeHtml(`<a href="x">&'`), "&lt;a href=&quot;x&quot;&gt;&amp;&#39;");
});
