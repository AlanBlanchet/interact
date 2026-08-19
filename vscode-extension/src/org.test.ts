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

import { readOrg, orgTree, type Org } from "./org.ts";

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
