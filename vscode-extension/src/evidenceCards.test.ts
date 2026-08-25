/** One visual language for everything an agent SHOWS you.
 *
 *  His words: "We can see the full code piece that was changed in the conversation... instead, how
 *  others do it is they show a box, and when we click on it it opens the code diff in the file...
 *  You have to check how it is also for other things like when screenshots are taken / shown, or
 *  even the 'thinking'... We globally need to have a theme and unique way of showing info."
 *
 *  So every non-speech event is the SAME kind of card: a glyph, a one-line headline, a payload
 *  that is collapsed or lives behind a click — never a wall of source dumped into the transcript.
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { renderTranscript, chatDocument } from "./conversationFormat.ts";

const edit = (path: string, extra = "") => ({
  kind: "tool", tool: "Edit",
  tool_input: `file_path='${path}' replace_all=False old_string='const a = 1' new_string='const a = 2'${extra}`,
});

test("a file edit is a card, never the code dumped inline", () => {
  const html = renderTranscript([edit("/home/alan/dev/interact/src/interact/models.py")] as never[]);
  assert.ok(html.includes("models.py"), "the card must name the file");
  assert.ok(!html.includes("const a = 1"), "the change's contents do not belong in the transcript");
  assert.ok(!html.includes("old_string"), "nor the tool's raw argument soup");
});

test("clicking the file card opens the file", () => {
  const html = renderTranscript([edit("/home/alan/x/y.ts")] as never[]);
  assert.match(html, /data-open="\/home\/alan\/x\/y\.ts"/, "the card must carry where to go");
});

test("write and read get the same card, with their own verb", () => {
  const w = renderTranscript([{ kind: "tool", tool: "Write",
    tool_input: "file_path='/tmp/a.md' content='# hello world this is long content'" }] as never[]);
  assert.ok(w.includes("a.md") && !w.includes("hello world"), "Write dumps nothing inline");
  const r = renderTranscript([{ kind: "tool", tool: "Read",
    tool_input: "file_path='/tmp/b.md'" }] as never[]);
  assert.ok(r.includes("b.md"));
});

test("an edit and its result stay ONE card, result folded in quietly", () => {
  const html = renderTranscript([
    edit("/x/a.ts"),
    { kind: "tool_result", text: "The file /x/a.ts has been updated. Here is the result of running `cat -n` on a snippet..." },
  ] as never[]);
  const cards = html.match(/class="turn turn-tool/g) ?? [];
  assert.equal(cards.length, 1, "a card and its acknowledgement are one unit");
  assert.ok(!html.includes("cat -n"), "a mechanical acknowledgement is noise, not evidence");
});

test("thinking is folded to a whisper, not a wall", () => {
  const words = Array.from({ length: 120 }, (_, i) => `word${i}`).join(" ");
  const html = renderTranscript([{ kind: "thinking", text: words }] as never[]);
  assert.match(html, /<details class="turn turn-thinking"/, "thought collapses by default");
  assert.ok(!/<details[^>]*open/.test(html), "collapsed means collapsed");
  assert.ok(html.includes("word3"), "but the full thought is there when you want it");
});

test("a screenshot in a result becomes an image card you can open", () => {
  const html = renderTranscript([
    { kind: "tool", tool: "Bash", tool_input: "interact screenshot" },
    { kind: "tool_result", text: "Saved capture to /tmp/shots/panel-dark.png (1600x1000)" },
  ] as never[]);
  assert.match(html, /data-open="\/tmp\/shots\/panel-dark\.png"/, "the capture must be openable");
  assert.ok(html.includes("panel-dark.png"), "and named");
});

test("a bash command keeps its IN and OUT box", () => {
  const html = renderTranscript([
    { kind: "tool", tool: "Bash", tool_input: "ls -la" },
    { kind: "tool_result", text: "total 8" },
  ] as never[]);
  assert.match(html, />IN</);
  assert.match(html, />OUT</);
});

test("file paths from outside are escaped like everything else", () => {
  const html = renderTranscript([edit(`/tmp/"onmouseover="alert(1)`)] as never[]);
  assert.ok(!html.includes('"onmouseover="'), "a hostile path must not break out of the attribute");
});

test("thinking the vendor withheld still leaves a trace", () => {
  /* His real streams carry thinking blocks with EMPTY content — the vendor persists a signature,
     not the words. Rendering nothing made reasoning invisible ("3 in data, 0 rendered"); the
     honest render is a quiet marker: it happened, there is nothing more to show. */
  const html = renderTranscript([{ kind: "thinking", text: "" }] as never[]);
  assert.ok(html.includes("thought for a moment"));
  assert.ok(!html.includes("<details"), "there is nothing to expand, so nothing must pretend to");
});

test("long output folds behind its count — one truncation rule, not four", () => {
  const out = Array.from({ length: 30 }, (_, i) => `line ${i}`).join("\n");
  const html = renderTranscript([
    { kind: "tool", tool: "Bash", tool_input: "make" }, { kind: "tool_result", text: out },
  ] as never[]);
  assert.match(html, /<summary>25 more lines<\/summary>/);
  assert.ok(html.includes("line 4") && html.includes("line 29"), "nothing is thrown away");
});

test("a harness injection folds as machinery, never as something HE said", () => {
  const html = renderTranscript([
    { kind: "message", from_run: "operator", text: "Stop hook feedback: [Review the turn...]" },
  ] as never[]);
  assert.ok(html.includes("harness"), "machinery must be named as machinery");
  assert.ok(!/>YOU</i.test(html), "and never attributed to him");
});

test("the empty panel is a door, not a caption about a missing list", () => {
  const html = chatDocument({ nonce: "n", turns: [], commands: [] });
  assert.ok(!html.includes("list above"), "the list it pointed at no longer exists there");
  assert.match(html, /id="openTeam"/, "an empty state must lead somewhere");
});
