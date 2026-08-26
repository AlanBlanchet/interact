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

test("a file edit is a card with a preview, never the change dumped inline", () => {
  /* The design moved once he asked for colour: the card PREVIEWS a few lines of the change (that
     is what a preview is), but the raw argument soup and the full payload stay out. */
  const html = renderTranscript([edit("/home/alan/dev/interact/src/interact/models.py")] as never[]);
  assert.ok(html.includes("models.py"), "the card must name the file");
  assert.ok(!html.includes("old_string"), "the tool's raw argument soup does not belong here");
  assert.ok(!html.includes("replace_all"), "none of it");
});

test("clicking the file card opens the file", () => {
  const html = renderTranscript([edit("/home/alan/x/y.ts")] as never[]);
  assert.match(html, /data-open="\/home\/alan\/x\/y\.ts"/, "the card must carry where to go");
});

test("write and read get the same card, with their own verb", () => {
  const w = renderTranscript([{ kind: "tool", tool: "Write",
    tool_input: "file_path='/tmp/a.md' content='# hello world this is long content'" }] as never[]);
  assert.ok(w.includes("a.md"), "the card names the file");
  assert.ok(w.includes("diff-add"), "and a write previews its opening as additions");
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

test("a tool call rests as ONE row; the text lives behind it", () => {
  /* "bash isn't well shown (not enough vertical spacing, too much text shown...)" — the old box
     opened with its whole IN and half its OUT inline. The unit is a row now: what ran, on what,
     how it went; clicking peeks the heads; ⧉ opens the whole payload in a tab. */
  const out = Array.from({ length: 30 }, (_, i) => `line ${i}`).join("\n");
  const html = renderTranscript([
    { kind: "tool", tool: "Bash", tool_input: "command='make'", tool_id: "toolu_7" },
    { kind: "tool_result", text: out, tool_id: "toolu_7" },
  ] as never[]);
  assert.match(html, /class="tool-row"/);
  assert.match(html, /class="tool-gist">make</, "the command IS the row's identity");
  assert.match(html, /✓ 30 lines/, "the verdict and the size, at a glance");
  assert.match(html, /<div class="tool-peek" hidden>/, "nothing of the body renders at rest");
  const visible = html.replace(/<template[\s\S]*?<\/template>/g, "");
  assert.ok(visible.includes("line 5") && !visible.includes("line 7"),
    "the VISIBLE peek holds a head, never the wall — the template may hold it all");
  assert.match(html, /\+24 more lines in the tab/);
  assert.match(html, /data-io="out" data-toolid="toolu_7"/, "the whole thing is one click away");
});

test("a failed command wears its cross on the resting row", () => {
  const html = renderTranscript([
    { kind: "tool", tool: "Bash", tool_input: "command='make'", tool_id: "t1" },
    { kind: "tool_result", text: "ERROR: no rule to make target", tool_id: "t1" },
  ] as never[]);
  assert.match(html, /class="tool-note tool-bad">✗</, "a failure must not need the click to see");
});

test("a call still running says so instead of claiming an empty answer", () => {
  const html = renderTranscript([
    { kind: "tool", tool: "Bash", tool_input: "command='sleep 60'", tool_id: "t2" },
  ] as never[]);
  assert.match(html, /tool-live/);
  assert.ok(!html.includes('class="io"><span class="io-tag">OUT'), "no OUT until there IS one");
});

test("a harness injection folds as machinery, never as something HE said", () => {
  /* The real stream writes what a person or the harness types as kind "prompt" — "message" is
     agent-to-agent mail. The first version gated on "message" alone, so on real transcripts the
     fold never fired once; both kinds are covered and both are pinned. */
  for (const kind of ["message", "prompt"]) {
    const html = renderTranscript([
      { kind, from_run: "operator", text: "Stop hook feedback: [Review the turn...]" },
    ] as never[]);
    assert.ok(html.includes("harness"), `${kind}: machinery must be named as machinery`);
    assert.ok(!/>YOU</i.test(html), `${kind}: and never attributed to him`);
  }
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

test("an edit shows a small COLORED diff preview, not nothing and not everything", () => {
  /* "The code updated / modifications aren't in color, and show too much instead of a preview."
     The card names the file; the preview shows what changed — a few minus lines, a few plus lines,
     in the theme's own diff colours — and the click opens the real thing. */
  const html = renderTranscript([{
    kind: "tool", tool: "Edit",
    tool_input: "file_path='/x/a.ts' replace_all=False old_string='const a = 1;\\nconst b = 2;' new_string='const a = 10;\\nconst b = 20;\\nconst c = 30;'",
  }] as never[]);
  assert.match(html, /class="diff-del"/, "removed lines must read as removed");
  assert.match(html, /class="diff-add"/, "added lines must read as added");
  assert.ok(html.includes("const a = 1;"), "the preview shows the actual change");
  assert.ok(html.includes("const a = 10;"));
});

test("a long change previews only its head — the click has the rest", () => {
  const many = Array.from({ length: 30 }, (_, i) => `line ${i}`).join("\\n");
  const html = renderTranscript([{
    kind: "tool", tool: "Edit",
    tool_input: `file_path='/x/a.ts' old_string='${many}' new_string='changed'`,
  }] as never[]);
  const dels = html.match(/class="diff-del"/g) ?? [];
  assert.ok(dels.length <= 4, `${dels.length} minus lines is a dump, not a preview`);
  assert.match(html, /· \d+ more/, "and it says how much the click holds");
});

test("a write previews its opening lines as additions", () => {
  const html = renderTranscript([{
    kind: "tool", tool: "Write",
    tool_input: "file_path='/x/new.md' content='# Title\\nFirst line of the doc\\nSecond line'",
  }] as never[]);
  assert.match(html, /class="diff-add"/);
  assert.ok(html.includes("# Title"));
});

test("a read has no diff to preview and shows none", () => {
  const html = renderTranscript([{
    kind: "tool", tool: "Read", tool_input: "file_path='/x/a.ts'",
  }] as never[]);
  assert.ok(!html.includes("diff-add") && !html.includes("diff-del"));
});

test("diff preview content is escaped like everything else", () => {
  const html = renderTranscript([{
    kind: "tool", tool: "Edit",
    tool_input: "file_path='/x/a.ts' old_string='<script>bad()</script>' new_string='safe'",
  }] as never[]);
  assert.ok(!html.includes("<script>bad"));
});
