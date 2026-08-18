import { strict as assert } from "node:assert";
import { test } from "node:test";

import { activityOf, zoneOf } from "./teamState.ts";

// A worker stands where the WORK is. The zone has to come from what the agent is actually doing
// right now, or the workplace is just a list with sprites on it.

test("reading or writing source puts you in the code room", () => {
  for (const tool of ["Read", "Edit", "Write", "Grep", "Glob"]) {
    assert.equal(zoneOf({ kind: "tool", tool }, "running"), "code");
  }
});

test("reaching the web takes you out of the building", () => {
  for (const tool of ["WebFetch", "WebSearch"]) {
    assert.equal(zoneOf({ kind: "tool", tool }, "running"), "web");
  }
});

test("spawning or messaging a teammate is management", () => {
  for (const tool of ["Agent", "Task", "SendMessage", "ListAgents"]) {
    assert.equal(zoneOf({ kind: "tool", tool }, "running"), "managers");
  }
  assert.equal(zoneOf({ kind: "spawn" }, "running"), "managers");
});

test("driving or looking at a screen is studio work", () => {
  for (const tool of ["mcp__interact__screenshot", "mcp__interact__run_actions", "review_ui"]) {
    assert.equal(zoneOf({ kind: "tool", tool }, "running"), "studio");
  }
});

test("a shell command is the lab — that is where things get run and measured", () => {
  assert.equal(zoneOf({ kind: "tool", tool: "Bash" }, "running"), "lab");
});

test("thinking with no tool in hand is the managers' room, not limbo", () => {
  assert.equal(zoneOf({ kind: "thinking" }, "running"), "managers");
});

test("a finished worker has gone back to the entrance", () => {
  assert.equal(zoneOf({ kind: "tool", tool: "Read" }, "done"), "entry");
});

test("an editor session interact did not start is idle, never mid-task", () => {
  assert.equal(zoneOf({ kind: "tool", tool: "Read" }, "foreign"), "idle");
});

test("an unknown tool does not throw a worker out of the building", () => {
  assert.equal(zoneOf({ kind: "tool", tool: "SomeFutureTool" }, "running"), "managers");
});

// The activity line is what a person would SAY they are doing, not the tool's name.

test("activity names the file, not the verb", () => {
  assert.match(activityOf({ kind: "tool", tool: "Read", tool_input: "file_path='/a/b/reg.py'" }),
    /reg\.py/);
});

test("a tool with no readable argument still says something useful", () => {
  assert.equal(activityOf({ kind: "tool", tool: "Bash", tool_input: "" }), "running Bash");
});

test("plain speech is quoted back, clipped", () => {
  assert.match(activityOf({ kind: "text", text: "I have finished the review of the diff" }),
    /finished the review/);
});

test("nothing recorded reads as waiting, not as blank", () => {
  assert.match(activityOf(undefined), /waiting|idle/i);
});

// Assembling the whole room from what the registry holds.

import { buildTeam } from "./teamState.ts";

const RUNS = [
  { run_id: "lead", name: "reviewer", agent: "code-reviewer", status: "running",
    project: "interact", cost_usd: 1.2, input_tokens: 90000, parent_run_id: null,
    started_at: 1000, last: "" },
  { run_id: "sub", name: "researcher", agent: "researcher", status: "running",
    project: "interact", cost_usd: 0.1, input_tokens: 5000, parent_run_id: "lead",
    started_at: 1000, last: "" },
  { run_id: "old", name: "perf", agent: null, status: "done", project: "interact",
    cost_usd: 0.5, input_tokens: 100, parent_run_id: null, started_at: 1, last: "" },
] as any[];

const STEPS: Record<string, any> = {
  lead: { kind: "tool", tool: "Read", tool_input: "file_path='/a/registry.py'" },
  sub: { kind: "tool", tool: "WebSearch", tool_input: "query='vscode webview'" },
  old: { kind: "text", text: "done" },
};

test("each worker is placed by what they are doing", () => {
  const team = buildTeam(RUNS, (id) => STEPS[id], 2000);
  const byId = Object.fromEntries(team.workers.map((w) => [w.run_id, w]));
  assert.equal(byId.lead.zone, "code");
  assert.equal(byId.sub.zone, "web", "a researcher fetching is out of the building");
  assert.equal(byId.old.zone, "entry", "finished workers come back to the door");
});

test("a sub-agent keeps its parent, so it can be drawn beside them", () => {
  const team = buildTeam(RUNS, (id) => STEPS[id], 2000);
  assert.equal(team.workers.find((w) => w.run_id === "sub")!.parent_run_id, "lead");
});

test("the activity line survives into the state", () => {
  const team = buildTeam(RUNS, (id) => STEPS[id], 2000);
  assert.match(team.workers.find((w) => w.run_id === "lead")!.activity, /registry\.py/);
});

test("idle time is measured, so the view can fade whoever stopped", () => {
  const team = buildTeam(RUNS, (id) => STEPS[id], 5000);
  assert.ok(team.workers.every((w) => w.idle_seconds >= 0));
});

test("an empty registry is an empty room, not a crash", () => {
  assert.deepEqual(buildTeam([], () => undefined, 1).workers, []);
});
