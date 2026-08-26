/** "find a way that we could easily chose what models are ran for what."
 *
 *  Which model an agent runs on is declared in the company file — which is GENERATED from the
 *  prompt repo, so anything the UI wrote there would be erased by the next sync. A choice made in
 *  the editor lives in the agents POLICY (`~/.interact/agents.json`), the one file the spawn
 *  reads: in its `agents` map, beside the profiles, toolsets and provider switches written by hand
 *  or by the CLI. One fact, one file — the choice the panel writes IS the choice the spawn uses.
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { mkdtempSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  adoptLegacyChoices, chooseModel, chosenModels, clearChoice, modelChosenFor, profilesIn,
} from "./agentModels.ts";

const scratch = () => join(mkdtempSync(join(tmpdir(), "am-")), "agents.json");
const policy = (body: object) => { const p = scratch(); writeFileSync(p, JSON.stringify(body)); return p; };
const fileOf = (p: string) => JSON.parse(readFileSync(p, "utf8")) as Record<string, unknown>;

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

test("a choice lands in the policy's agents map and leaves the rest of the policy alone", () => {
  /* Profiles, toolsets and provider switches are written by hand or by the CLI; the panel edits
     ONE map in that file and must not flatten, drop or reshape what it did not write. */
  const p = policy({
    profiles: { eyes: "cap.vlm and price.in < 10" }, toolsets: { vision: ["screenshot"] },
    providers: { codex: false },
  });
  chooseModel("researcher", "a/one", p);
  assert.deepEqual(fileOf(p), {
    profiles: { eyes: "cap.vlm and price.in < 10" }, toolsets: { vision: ["screenshot"] },
    providers: { codex: false }, agents: { researcher: "a/one" },
  });
  clearChoice("researcher", p);
  assert.deepEqual(fileOf(p).providers, { codex: false }, "clearing a choice must not clear a switch");
});

test("a rule written by hand shows as the choice — a profile or a criterion, not only an id", () => {
  const p = policy({ profiles: { eyes: "cap.vlm" }, agents: { "visual-critic": "@eyes", librarian: "aa.intelligence >= 30" } });
  assert.equal(modelChosenFor("visual-critic", p), "@eyes");
  assert.equal(modelChosenFor("librarian", p), "aa.intelligence >= 30");
});

test("a profile can be chosen, but only one the policy defines", () => {
  /* `@ghost` would be caught by Python at the next spawn of the one agent wearing it — at 3am.
     The picker only offers profiles that exist, and refuses one that does not. */
  const p = policy({ profiles: { eyes: "cap.vlm" } });
  assert.deepEqual(profilesIn(p), { eyes: "cap.vlm" });
  assert.equal(chooseModel("visual-critic", "@eyes", p), true);
  assert.equal(chooseModel("visual-critic", "@ghost", p), false);
  assert.equal(modelChosenFor("visual-critic", p), "@eyes");
});

test("a corrupt policy does not take the panel down — and is never overwritten by a click", () => {
  /* This file is hand-edited and lives outside the repo; it WILL be malformed one day. It holds
     profiles and toolsets somebody typed, so "recover by rewriting" would destroy their work for
     the sake of one picker click: read as empty, refuse the write, leave it theirs to fix. */
  const p = scratch();
  writeFileSync(p, "{ not json at all");
  assert.deepEqual(chosenModels(p), {});
  assert.equal(chooseModel("researcher", "a/one", p), false);
  assert.equal(readFileSync(p, "utf8"), "{ not json at all");
});

test("only a plausible model id is stored", () => {
  /* The id ends up as a vendor `--model` and, provider-prefixed, selects an endpoint. Storing a
     newline or a flag-shaped string here would be a real hole. */
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

test("choices made before the policy existed are carried over once, then the old file is gone", () => {
  /* v0.38 kept choices in `agent-models.json`; a choice made there must not vanish from the
     panel the day the store moved. Carried over WITHOUT overriding what the policy already says
     — the policy is the newer word. */
  const dir = mkdtempSync(join(tmpdir(), "am-"));
  const legacy = join(dir, "agent-models.json");
  const p = join(dir, "agents.json");
  writeFileSync(legacy, JSON.stringify({ "web-researcher": "ollama/deepseek-v4-pro:cloud", scraper: "old/one" }));
  writeFileSync(p, JSON.stringify({ agents: { scraper: "new/one" }, providers: { codex: false } }));
  assert.equal(adoptLegacyChoices(legacy, p), 1, "one carried, one already decided by the policy");
  assert.deepEqual(fileOf(p), {
    agents: { scraper: "new/one", "web-researcher": "ollama/deepseek-v4-pro:cloud" }, providers: { codex: false },
  });
  assert.equal(existsSync(legacy), false, "the old file must not linger to be read again");
  assert.equal(adoptLegacyChoices(legacy, p), 0, "running again is a no-op");
});
