/** The Agents sidebar's pure logic, tested without VS Code.
 *
 *  The tree itself needs the `vscode` module (only available inside the extension host), so the
 *  grouping / labelling / formatting decisions live as exported pure functions and are pinned
 *  here. Run with: node --experimental-strip-types --test src/agentsView.test.ts
 *
 *  These exist because the panel's whole job is to tell the truth at a glance: an unknown cost
 *  rendered as "$0.00" claims a run was free, and a group that hides live work defeats the point
 *  of a sidebar.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import type { AgentRun } from "./agents.ts";
import { formatCost, formatElapsed, groupKeyFor, orderGroups } from "./agentsFormat.ts";

function run(over: Partial<AgentRun> = {}): AgentRun {
  return {
    run_id: "r1",
    provider: "claude",
    name: "worker",
    status: "running",
    cwd: "/home/alan/dev/interact",
    started_at: 1_000,
    ...over,
  } as AgentRun;
}

test("unknown cost is an em dash, never $0.00", () => {
  assert.equal(formatCost(null), "—");
  assert.equal(formatCost(undefined), "—");
  assert.equal(formatCost(0.6155), "~$0.6155");
});

test("a project group is the directory's basename, not the whole path", () => {
  assert.equal(groupKeyFor(run(), "project"), "interact");
  assert.equal(groupKeyFor(run({ cwd: "" }), "project"), "(no project)");
});

test("provider and model groups fall back to something readable", () => {
  assert.equal(groupKeyFor(run(), "provider"), "claude");
  assert.equal(groupKeyFor(run({ model: null }), "model"), "(default model)");
  assert.equal(groupKeyFor(run({ model: "claude-opus-5" }), "model"), "claude-opus-5");
});

test("groups with live work sort first", () => {
  // A sidebar you must scroll to find the running agent is a sidebar that failed.
  const idle: [string, AgentRun[]] = ["zzz-idle", [run({ status: "done" })]];
  const live: [string, AgentRun[]] = ["aaa-live", [run({ status: "running" })]];
  assert.deepEqual(orderGroups([idle, live]).map(([k]) => k), ["aaa-live", "zzz-idle"]);
});

test("elapsed counts to now while running, and freezes once finished", () => {
  const started = Date.now() / 1000 - 90;
  assert.equal(formatElapsed(run({ started_at: started })), "1m");
  assert.equal(
    formatElapsed(run({ started_at: 1_000, finished_at: 1_030, status: "done" })),
    "30s",
  );
});
