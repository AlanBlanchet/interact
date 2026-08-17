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

test("a tool result is visually attached to the call above it", () => {
  // The critic measured the result's border at 1.16:1 — invisible — so a reader could not tell
  // which call produced which output. It now carries the SAME hue as the call it belongs to.
  const html = renderTurn({ kind: "tool_result", text: "out" });
  assert.ok(html.includes("turn-tool_result"));
  assert.ok(html.includes("result-of"), "the result is not marked as belonging to a call");
});

test("infrastructure events are not turns in the conversation", () => {
  // A 'five_hour limit: allowed' rendered BETWEEN a Bash call and its own result, breaking the
  // one sequence a reader needs unbroken.
  assert.equal(renderTurn({ kind: "rate_limit", text: "five_hour limit: allowed" }), "");
  assert.equal(renderTurn({ kind: "started", text: "session up" }), "");
});

test("a long tool result is truncated at render time, and says so", () => {
  // enableScripts:false means a collapse can never be added client-side — it must be here.
  const html = renderTurn({ kind: "tool_result", text: "line\n".repeat(400) });
  assert.ok(html.length < 4000, "an unbounded wall of output reached the panel");
  assert.ok(/more line/.test(html), "truncation must declare what it hid");
});
