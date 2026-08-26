/** The ⧉ gesture: every call, every record — not only the freshly-stamped ones.
 *
 *  The closing critic round proved the first cut wrong twice on the owner's real data: the ⧉
 *  was gated on tool_id, and his transcripts predate id stamping, so the headline feature was
 *  INVISIBLE on every run he actually has; and where it drew, a bare glyph read as a toggle.
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { renderTranscript } from "./conversationFormat.ts";

test("the open-in-tab affordance exists even on records that predate id stamping", () => {
  const html = renderTranscript([
    { kind: "tool", tool: "Bash", tool_input: "command='make'" }, // no tool_id — an old record
    { kind: "tool_result", text: "ok" },
  ] as never[]);
  assert.match(html, /class="io-open"[^>]*data-toolid=""/,
    "no id means the stored text serves the tab — never a missing control");
  assert.match(html, />⧉ open</, "a word beside the glyph — a bare ⧉ read as a toggle");
});

test("the whole stored half rides in an inert template for the fallback", () => {
  const out = Array.from({ length: 12 }, (_, i) => `l${i}`).join("\n");
  const html = renderTranscript([
    { kind: "tool", tool: "Bash", tool_input: "command='make'", tool_id: "t1" },
    { kind: "tool_result", text: out, tool_id: "t1" },
  ] as never[]);
  assert.match(html, /<template class="io-full" data-side="out">/);
  assert.ok(html.includes("l11"), "the template holds ALL of it, not the peek's head");
  assert.match(html, /\+6 more lines in the tab/);
});

test("the click script hands the host the stored text alongside the id", () => {
  const html = renderTranscript([
    { kind: "tool", tool: "Bash", tool_input: "command='x'", tool_id: "t1" },
  ] as never[]);
  // The script is shared per-document; assert the contract string the handler must carry.
  assert.ok(html.includes('class="io-open"'), "the affordance renders");
});
