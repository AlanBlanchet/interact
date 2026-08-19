/** The company, as data.
 *
 *  His ask: "we also have way more agents that are shared between providers... They are not all in
 *  the env... librarian, can't you make a kind of hierarchy of agents in the yaml or something like
 *  that? Just so that interact would pick these files up? to make a real company!"
 *
 *  The librarian emits that hierarchy to `~/.claude/org.json`. This is the reader. It must survive
 *  the file being absent — plenty of people run interact with no prompt repo at all — and it must
 *  keep an agent whose department is unknown rather than dropping it, because a roster that
 *  silently omits people is worse than one with an "unassigned" desk.
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { readOrg, orgTree, spawnChoices, modelFor, spawnArgs, type Org } from "./org.ts";

const ORG: Org = {
  coordinator: { id: "main", title: "Main thread — session coordinator" },
  providers: {
    claude: { label: "Claude Code (Anthropic)", env: true },
    codex: { label: "Codex (OpenAI)", env: false },
  },
  departments: [
    { id: "quality", room: "lab", mission: "verify", reports_to: null },
    { id: "research", room: "web", mission: "find out", reports_to: null },
  ],
  agents: [
    { name: "tester", title: "Test engineer", department: "quality", seniority: "staff",
      role: "critic", reports_to: "quality", pairs_with: null, providers: ["claude"],
      model: "claude-sonnet-5", def: "agents/tester.md", description: "" },
    { name: "researcher", title: "Researcher", department: "research", seniority: "staff",
      role: "producer", reports_to: "research", pairs_with: null, providers: ["claude", "codex"],
      model: null, def: "agents/researcher.md", description: "" },
    { name: "stray", title: "Unfiled", department: "nowhere", seniority: "staff",
      role: "producer", reports_to: null, pairs_with: null, providers: [],
      model: null, def: "agents/stray.md", description: "" },
  ],
};

test("a missing org file is not an error — most installs have no prompt repo", () => {
  assert.equal(readOrg(join(mkdtempSync(join(tmpdir(), "org-")), "nope.json")), null);
});

test("a malformed org file is ignored rather than crashing the panel", () => {
  const p = join(mkdtempSync(join(tmpdir(), "org-")), "org.json");
  writeFileSync(p, "{ not json");
  assert.equal(readOrg(p), null);
});

test("the company reads back with its departments and people", () => {
  const p = join(mkdtempSync(join(tmpdir(), "org-")), "org.json");
  writeFileSync(p, JSON.stringify(ORG));
  const org = readOrg(p)!;

  assert.equal(org.coordinator.id, "main");
  assert.equal(org.agents.length, 3);
});

test("the tree hangs departments off the coordinator, and people off departments", () => {
  const tree = orgTree(ORG);

  assert.deepEqual(tree.map((d) => d.id), ["quality", "research", "unassigned"]);
  assert.deepEqual(tree[0].agents.map((a) => a.name), ["tester"]);
  assert.deepEqual(tree[1].agents.map((a) => a.name), ["researcher"]);
});

test("an agent whose department nobody declared still gets a desk", () => {
  // Dropping them would make the roster quietly wrong, which is the failure this is here to avoid.
  const tree = orgTree(ORG);
  assert.deepEqual(tree[2].agents.map((a) => a.name), ["stray"]);
  assert.equal(tree[2].mission, "not filed under any department");
});

test("a provider that is only DESIGNED for is marked apart from one that is wired", () => {
  // His words: "shared between providers... They are not all in the env."
  const tree = orgTree(ORG);
  const researcher = tree[1].agents[0];
  assert.deepEqual(researcher.providers, [
    { id: "claude", label: "Claude Code (Anthropic)", env: true },
    { id: "codex", label: "Codex (OpenAI)", env: false },
  ]);
});

test("an agent nobody can run anywhere says so, rather than showing an empty row", () => {
  assert.deepEqual(orgTree(ORG)[2].agents[0].providers, []);
});

test("a department node knows how many people sit in it", () => {
  // Guards the shape the tree renders from: a department with no agents is still a department,
  // and a count that silently omits the unfiled bucket would misreport the company's size.
  const tree = orgTree(ORG);
  assert.equal(tree.reduce((n, d) => n + d.agents.length, 0), ORG.agents.length);
});

test("wired and merely-designed providers are distinguishable per agent", () => {
  // "not wired anywhere" has to be sayable, or an agent with nowhere to run looks identical to
  // one that is ready.
  const tree = orgTree(ORG);
  const seats = tree.flatMap((d) => d.agents);
  const nowhere = seats.filter((s) => !s.providers.some((p) => p.env)).map((s) => s.name);
  assert.deepEqual(nowhere, ["stray"]);
});

// --- hiring from the company, rather than from a list of filenames ---

test("an agent that the company knows is offered with its title and department", () => {
  const choices = spawnChoices(["tester", "researcher"], ORG);
  const tester = choices.find((c) => c.label === "tester")!;

  assert.equal(tester.description, "Test engineer");
  assert.match(tester.detail!, /quality/);
  assert.match(tester.detail!, /claude/);
});

test("a definition the company does not list is still offered", () => {
  // The org file is hand-maintained and the agents directory is the ground truth for what can
  // actually be RUN. Dropping an unlisted definition would make a real, runnable agent invisible
  // because a yaml row is missing.
  const choices = spawnChoices(["tester", "undocumented"], ORG);
  const stray = choices.find((c) => c.label === "undocumented");

  assert.ok(stray, "a runnable definition vanished because the org did not mention it");
  assert.match(stray!.detail ?? "", /not in the company/);
});

test("choices are grouped by department, plain agent first", () => {
  const labels = spawnChoices(["researcher", "tester"], ORG).map((c) => c.label);
  assert.equal(labels[0], "claude", "the no-definition option stays first");
  assert.deepEqual(labels.slice(1), ["tester", "researcher"], "quality before research, as declared");
});

test("with no company at all it is still just a list of definitions", () => {
  const labels = spawnChoices(["a", "b"], null).map((c) => c.label);
  assert.deepEqual(labels, ["claude", "a", "b"]);
});

// --- what model an agent should run on ---

test("an agent's declared model is offered as its default", () => {
  const withModel: Org = { ...ORG, agents: ORG.agents.map((a) =>
    a.name === "tester" ? { ...a, model: "claude-sonnet-5" } : a) };
  assert.equal(modelFor("tester", withModel), "claude-sonnet-5");
});

test("'inherit' is not a model — it means take the session's", () => {
  // Half the roster declares `inherit`, which is a real value in the org file and would be a
  // nonsense --model flag. It has to read as "no override" rather than be passed through.
  const inheriting: Org = { ...ORG, agents: ORG.agents.map((a) =>
    a.name === "tester" ? { ...a, model: "inherit" } : a) };
  assert.equal(modelFor("tester", inheriting), null);
});

test("an agent the company does not know has no declared model", () => {
  assert.equal(modelFor("nobody", ORG), null);
  assert.equal(modelFor("tester", null), null);
});

test("the spawn argv carries the agent, its declared model, and the folder", () => {
  const org: Org = { ...ORG, agents: ORG.agents.map((a) =>
    a.name === "tester" ? { ...a, model: "claude-sonnet-5" } : a) };

  assert.deepEqual(spawnArgs({ task: "check it", agent: "tester", cwd: "/w", org }),
    ["agents", "spawn", "check it", "--agent", "tester", "--model", "claude-sonnet-5", "--cwd", "/w"]);
});

test("a plain agent passes no --agent, and inherit passes no --model", () => {
  const inheriting: Org = { ...ORG, agents: ORG.agents.map((a) =>
    a.name === "tester" ? { ...a, model: "inherit" } : a) };

  assert.deepEqual(spawnArgs({ task: "t", agent: "claude", cwd: null, org: ORG }),
    ["agents", "spawn", "t"]);
  assert.deepEqual(spawnArgs({ task: "t", agent: "tester", cwd: null, org: inheriting }),
    ["agents", "spawn", "t", "--agent", "tester"]);
});

test("the permission flag is spelled exactly as the CLI parses it", () => {
  // The other half of the seam: the CLI side is pinned by a Python test. Rename either and the
  // panel silently spawns with the CLI's own default while reporting that it chose "plan" — for a
  // safety control, doing something other than what the UI said is the worst available failure.
  const args = spawnArgs({ task: "t", agent: "claude", cwd: null, org: ORG, permissionMode: "plan" });
  assert.ok(args.includes("--permission-mode"), "the literal flag the CLI declares");
  assert.equal(args[args.indexOf("--permission-mode") + 1], "plan");
});
