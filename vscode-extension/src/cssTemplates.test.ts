/** A backtick inside a CSS comment silently ends the template literal that holds the stylesheet,
 *  and everything after it is then parsed as TypeScript. I have done this twice in one session —
 *  once in the workplace stylesheet, once in the chat's — and both times the build failed with a
 *  message about an unexpected token hundreds of lines further down, pointing at code that was
 *  fine. Cheaper to name the real cause here than to rediscover it a third time.
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));

// Files whose bodies are largely CSS inside a template literal.
const SHEETS = [
  join(here, "..", "webview", "workplace", "style.ts"),
  join(here, "conversationFormat.ts"),
];

test("no CSS comment inside a stylesheet literal contains a backtick", () => {
  for (const file of SHEETS) {
    const lines = readFileSync(file, "utf8").split("\n");
    // Only INSIDE the literal. A JSDoc header above it may use backticks freely — they are
    // ordinary prose there, and flagging them would make this guard something to switch off.
    const opens = lines.findIndex((l) => /=\s*(String\.raw)?`/.test(l));
    assert.notEqual(opens, -1, `${file}: found no template literal to check`);
    for (let i = opens + 1; i < lines.length; i++) {
      const line = lines[i];
      if (/^\s*`/.test(line)) break; // the literal closed
      const comment = /\/\*(.*)$|^\s*\*(?!\/)(.*)$/.exec(line);
      if (comment && (comment[1] ?? comment[2] ?? "").includes("`")) {
        assert.fail(`${file}:${i + 1} — a backtick here ends the stylesheet literal; use quotes`);
      }
    }
  }
});

test("the guard would actually catch one", () => {
  const line = "  /* use `anywhere` here */";
  const comment = /\/\*(.*)$/.exec(line);
  assert.ok((comment?.[1] ?? "").includes("`"), "the pattern must see a backtick in a CSS comment");
});
