#!/usr/bin/env node
/** A backtick inside a CSS comment ends the template literal holding the stylesheet.
 *
 *  Everything after it is then parsed as TypeScript, and tsc reports a syntax error on a line that
 *  looks like a comment — which is a confusing place to be told about a broken string. It has cost
 *  five build cycles in one session, so the check runs FIRST and says what actually happened.
 */
const fs = require("fs");
const path = require("path");

const SHEETS = [
  "src/conversationFormat.ts",
  "webview/workplace/style.ts",
  "webview/sidebar-proto/style.ts",
];

let bad = false;
for (const rel of SHEETS) {
  const file = path.join(__dirname, "..", rel);
  let lines;
  try {
    lines = fs.readFileSync(file, "utf8").split("\n");
  } catch {
    continue;
  }
  const opens = lines.findIndex((l) => /=\s*(String\.raw)?`/.test(l));
  if (opens === -1) continue;
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
      if (chunk.includes("`")) {
        console.error(`${rel}:${i + 1}: a backtick inside a CSS comment closes the stylesheet's ` +
          `template literal — everything after it is parsed as TypeScript. Use plain quotes.`);
        bad = true;
      }
      if (close === -1) break;
      rest = rest.slice(close + 2);
      inComment = false;
    }
  }
}
process.exit(bad ? 1 : 0);
