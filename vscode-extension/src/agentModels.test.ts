/** "find a way that we could easily chose what models are ran for what."
 *
 *  Which model an agent runs on is declared in the company file — which is GENERATED from the
 *  prompt repo, so anything the UI wrote there would be erased by the next sync. A choice made in
 *  the editor has to live somewhere the generator does not own.
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { mkdtempSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chosenModels, modelChosenFor, chooseModel, clearChoice } from "./agentModels.ts";

const scratch = () => join(mkdtempSync(join(tmpdir(), "am-")), "agent-models.json");

test("nothing chosen yet is not an error", () => {
  const p = join(mkdtempSync(join(tmpdir(), "am-")), "missing.json");
  assert.deepEqual(chosenModels(p), {});
  assert.equal(modelChosenFor("researcher", p), null);
});

test("a choice survives being written and read back", () => {
  const p = scratch();
  chooseModel("researcher", "ollama/deepseek-v4-pro:cloud", p);
  assert.equal(modelChosenFor("researcher", p), "ollama/deepseek-v4-pro:cloud");
  assert.deepEqual(chosenModels(p), { researcher: "ollama/deepseek-v4-pro:cloud" });
});

test("choosing again replaces rather than accumulates", () => {
  const p = scratch();
  chooseModel("researcher", "a/one", p);
  chooseModel("researcher", "b/two", p);
  assert.deepEqual(chosenModels(p), { researcher: "b/two" });
});

test("clearing hands the agent back to the company file", () => {
  const p = scratch();
  chooseModel("researcher", "a/one", p);
  clearChoice("researcher", p);
  assert.equal(modelChosenFor("researcher", p), null, "a cleared choice must not linger");
  assert.deepEqual(chosenModels(p), {});
});

test("a corrupt file does not take the panel down with it", () => {
  /* This file is hand-editable and lives outside the repo; it WILL be malformed one day. Losing a
     model preference is survivable, a panel that will not render is not. */
  const p = scratch();
  writeFileSync(p, "{ not json at all");
  assert.deepEqual(chosenModels(p), {});
  chooseModel("researcher", "a/one", p);
  assert.equal(modelChosenFor("researcher", p), "a/one", "and it recovers on the next write");
});

test("only a plausible model id is stored", () => {
  /* The id becomes an argv `--model` and, for a provider-prefixed id, selects an endpoint. Storing
     a newline or a flag-shaped string here would be a real hole. */
  const p = scratch();
  for (const bad of ["", "  ", "--dangerous", "a/one\nb", "x".repeat(200)]) {
    assert.equal(chooseModel("researcher", bad, p), false, `accepted ${JSON.stringify(bad)}`);
  }
  assert.deepEqual(chosenModels(p), {});
  assert.equal(chooseModel("researcher", "ollama/deepseek-v4-pro:cloud", p), true);
});

test("an agent name is not a path", () => {
  const p = scratch();
  assert.equal(chooseModel("../../etc/passwd", "a/one", p), false);
  assert.equal(chooseModel("", "a/one", p), false);
});

test("the file it writes is readable by a person", () => {
  /* He edits his own config by hand; a one-line blob would be hostile. */
  const p = scratch();
  chooseModel("researcher", "ollama/deepseek-v4-pro:cloud", p);
  const text = readFileSync(p, "utf8");
  assert.ok(text.includes("\n"), "written as an unreadable single line");
  assert.ok(existsSync(p));
});
