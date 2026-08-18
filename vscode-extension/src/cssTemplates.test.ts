/** A backtick inside a CSS comment silently ends the template literal that holds the stylesheet,
 *  and everything after it is then parsed as TypeScript. I have done this three times in one
 *  session, and the build fails with a message about an unexpected token hundreds of lines
 *  further down, pointing at code that is fine.
 *
 *  The first version of this guard matched a line that STARTS a comment, or continues one with a
 *  leading asterisk. CSS comments here do neither on their middle lines, so it sailed straight
 *  past a backtick on the second line of a three-line comment and the build broke anyway. It now
 *  tracks the comment BLOCK, and the synthetic cases below are what prove it — checking the real
 *  stylesheets alone only ever proves they are currently clean.
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));

/** Files whose bodies are largely CSS inside a template literal. */
const SHEETS = [
  join(here, "..", "webview", "workplace", "style.ts"),
  join(here, "conversationFormat.ts"),
];

/** Every backtick that sits inside a CSS comment within the file's template literal, as
 *  1-based line numbers. Exported shape kept simple so the synthetic cases can drive it. */
export function backticksInCssComments(lines: string[]): number[] {
  const opens = lines.findIndex((l) => /=\s*(String\.raw)?`/.test(l));
  if (opens === -1) return [];
  const hits: number[] = [];
  let inComment = false;
  for (let i = opens + 1; i < lines.length; i++) {
    let rest = lines[i];
    if (!inComment && /^\s*`/.test(rest)) break; // the literal closed
    while (rest) {
      if (!inComment) {
        const open = rest.indexOf("/*");
        if (open === -1) break;
        rest = rest.slice(open + 2);
        inComment = true;
      }
      const close = rest.indexOf("*/");
      const chunk = close === -1 ? rest : rest.slice(0, close);
      if (chunk.includes("`")) hits.push(i + 1);
      if (close === -1) break;
      rest = rest.slice(close + 2);
      inComment = false;
    }
  }
  return hits;
}

test("it catches a backtick on the MIDDLE line of a comment — the case that got through", () => {
  const lines = [
    "export const STYLE = String.raw`",
    "  /* a comment that opens here",
    "     and mentions `anywhere` on a line with no asterisk",
    "     and closes here */",
    "  .x { color: red; }",
    "`;",
  ];
  assert.deepEqual(backticksInCssComments(lines), [3]);
});

test("it catches one on the opening line too", () => {
  const lines = ["const S = `", "  /* uses `break-word` here */", "`;"];
  assert.deepEqual(backticksInCssComments(lines), [2]);
});

test("a backtick in the JSDoc header above the literal is fine", () => {
  // Ordinary prose there — flagging it would make this guard something to switch off.
  const lines = ["/** mixes `--vscode-*` tokens */", "const S = `", "  .x { color: red; }", "`;"];
  assert.deepEqual(backticksInCssComments(lines), []);
});

test("clean CSS with comments produces nothing", () => {
  const lines = ["const S = `", "  /* plain words only */", "  .x { color: red; }", "`;"];
  assert.deepEqual(backticksInCssComments(lines), []);
});

test("the shipping stylesheets are clean", () => {
  for (const file of SHEETS) {
    const hits = backticksInCssComments(readFileSync(file, "utf8").split("\n"));
    assert.deepEqual(hits, [], `${file}: backtick in a CSS comment at line(s) ${hits.join(", ")}`);
  }
});
