#!/usr/bin/env node
/** A backtick inside a comment ends the template literal holding an embedded stylesheet or script.
 *
 *  Everything after it is then parsed as TypeScript, and tsc reports a syntax error on a line that
 *  looks like a comment — a confusing place to be told about a broken string. It has cost six
 *  build cycles in one session, so this runs FIRST and says what actually happened.
 *
 *  Two earlier versions of this guard each missed a real break:
 *
 *   - a hardcoded file list missed `webview/workplace/sim.ts`, which embeds the simulation exactly
 *     as `style.ts` embeds the stylesheet — nobody remembered to add it, so a guard written for
 *     this failure sat and watched it happen. Files carrying `String.raw` are discovered now.
 *   - scanning stopped at the first closing backtick, which missed `motion.ts` entirely: its
 *     source is CONCATENATED (a template, then SIM, then another template), so everything after
 *     the first segment went unchecked. The scan tracks template state instead of guessing.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");

/** Files whose body is an embedded stylesheet or script rather than ordinary code.
 *
 *  `String.raw` is the exact signature of that kind, so those are discovered. A file carrying a
 *  big plain-backtick sheet is still listed by hand: nothing distinguishes it from ordinary code
 *  holding an ordinary template, and guessing flagged three files that compile perfectly well.
 */
const LISTED = ["src/conversationFormat.ts"];

function rawTemplateFiles(dir, found = []) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return found;
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== "node_modules") rawTemplateFiles(full, found);
    } else if (entry.name.endsWith(".ts") && !entry.name.endsWith(".test.ts")) {
      if (fs.readFileSync(full, "utf8").includes("String.raw`")) {
        found.push(path.relative(ROOT, full));
      }
    }
  }
  return found;
}

function sheets() {
  return [...LISTED, ...["src", "webview"].flatMap((r) => rawTemplateFiles(path.join(ROOT, r)))];
}

/** Every backtick sitting inside a comment WITHIN a template literal, as 1-based line numbers.
 *
 *  A small state machine rather than line heuristics, because both previous heuristics were wrong
 *  in a way that only showed up as a broken build. It runs from byte zero: starting at the first
 *  backtick began INSIDE the module docstring — which legitimately quotes things in backticks —
 *  and every state after that was inverted, flagging six lines of a file that compiles. A backtick
 *  in a comment outside any template is prose and ignored; one inside an OPEN template is the
 *  defect, because that is where it silently ends the string.
 */
function backticksInCommentedTemplates(text) {
  const hits = [];
  let inTemplate = false;
  let comment = null; // "block" | "line" | null
  let line = 1;

  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    const pair = c + text[i + 1];
    if (c === "\n") {
      line++;
      if (comment === "line") comment = null;
      continue;
    }
    if (comment === "block") {
      if (pair === "*/") { comment = null; i++; continue; }
    } else if (comment === "line") {
      // runs to the newline handled above
    } else if (pair === "/*") {
      comment = "block"; i++; continue;
    } else if (pair === "//" && !inTemplate) {
      // Only outside a template: "//" inside CSS or a URL is not a comment.
      comment = "line"; i++; continue;
    }
    // A quoted string can hold a backtick that delimits nothing.
    if (!comment && (c === '"' || c === "'")) {
      for (i++; i < text.length; i++) {
        if (text[i] === "\\") { i++; continue; }
        if (text[i] === c || text[i] === "\n") break;
      }
      if (text[i] === "\n") line++;
      continue;
    }
    if (c === "`") {
      // A run of three or more is a markdown fence — content, not a delimiter. `FENCE` in
      // conversationFormat.ts is exactly that, and reading its regex as two template edges
      // inverted every state after it and condemned six lines of a file that compiles.
      let run = 1;
      while (text[i + run] === "`") run++;
      if (run >= 3) { i += run - 1; continue; }
      if (comment && inTemplate) hits.push(line);
      else if (!comment) inTemplate = !inTemplate;
    }
  }
  return hits;
}

module.exports = { sheets, backticksInCommentedTemplates };

if (require.main === module) {
  let bad = false;
  for (const rel of sheets()) {
    let text;
    try {
      text = fs.readFileSync(path.join(ROOT, rel), "utf8");
    } catch {
      continue;
    }
    for (const line of backticksInCommentedTemplates(text)) {
      console.error(`${rel}:${line}: a backtick inside a comment closes this file's template ` +
        `literal — everything after it is parsed as TypeScript. Use plain quotes.`);
      bad = true;
    }
  }
  process.exit(bad ? 1 : 0);
}
