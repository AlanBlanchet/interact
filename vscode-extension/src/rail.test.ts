/** The rail's decisions: what the panel shows at rest, and in what order.
 *
 *  Why a rail at all is measured rather than stylistic. VS Code hides a view's title actions until
 *  the pointer enters the header and CLIPS the overflow with no "…" menu, so the panel rendered
 *  ZERO buttons at rest and the team view could only be found by hovering and guessing among
 *  unlabelled glyphs. No arrangement of icons fixes that inside a `TreeView` at any width.
 *
 *  The two decisions worth pinning are the ones that make this a supervision surface rather than
 *  a list: the roster is ordered by WHO NEEDS YOU, and the destinations carry words.
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { attentionOf, brainOf, buildRail, railAction, railRoute, CHIPS, HELD_SECONDS } from "./rail.ts";
import { buildTeam } from "./teamState.ts";

const run = (over: Record<string, unknown> = {}) => ({
  run_id: "r", name: "worker", provider: "claude", status: "running", started_at: 100, ...over,
}) as never;

const rail = (runs: unknown[], idle: (r: never) => number = () => 0, asked = () => false) =>
  buildRail(runs as never[], "interact", idle as never, asked as never);

test("a run that failed outranks everything else", () => {
  const built = rail([
    run({ run_id: "ok", status: "running" }),
    run({ run_id: "done", status: "done" }),
    run({ run_id: "bad", status: "crashed" }),
  ]);
  assert.equal(built.runs[0].run.run_id, "bad");
  assert.equal(built.runs[0].attention, "error");
});

test("a running agent that has said nothing for two minutes is asking for attention", () => {
  assert.equal(attentionOf(run(), HELD_SECONDS - 1), "working");
  assert.equal(attentionOf(run(), HELD_SECONDS), "held");
});

test("a run that asked you something outranks one merely sitting quiet", () => {
  const built = rail(
    [run({ run_id: "quiet" }), run({ run_id: "asked" })],
    (r) => (r.run_id === "quiet" ? 9999 : 0),
    (r) => r.run_id === "asked",
  );
  assert.deepEqual(built.runs.map((r) => r.run.run_id), ["asked", "quiet"]);
});

test("your own editor sessions sort last, never above an agent that stopped", () => {
  // You cannot act on them from here, so they must not compete with work that needs you.
  const built = rail([run({ run_id: "mine", status: "foreign" }), run({ run_id: "bad", status: "failed" })]);
  assert.deepEqual(built.runs.map((r) => r.run.run_id), ["bad", "mine"]);
});

test("within one band the most recently started leads", () => {
  const built = rail([
    run({ run_id: "old", status: "failed", started_at: 10 }),
    run({ run_id: "new", status: "failed", started_at: 900 }),
  ]);
  assert.deepEqual(built.runs.map((r) => r.run.run_id), ["new", "old"]);
});

test("the header counts what NEEDS you, not what is merely running", () => {
  // "8 running" answers "is it busy", which is never the question a supervisor is asking.
  const built = rail(
    [run({ run_id: "a" }), run({ run_id: "b" }), run({ run_id: "c", status: "crashed" })],
  );
  assert.equal(built.header.needsYou, 1);
  assert.equal(built.header.working, 2);
});

test("every destination carries a word, and each invokes a real command", () => {
  for (const chip of CHIPS) {
    assert.ok(chip.label.trim(), `${chip.id} has no label — an icon you must hover is a guess`);
    assert.match(chip.command, /^interact\./);
  }
  assert.ok(CHIPS.some((c) => c.id === "team"), "the team must be a first-class destination");
});

test("the destinations stay few enough to fit a narrow sidebar", () => {
  // The old title bar carried seven actions and clipped the seventh at every width. The fix is
  // fewer destinations with words, not smaller glyphs.
  assert.ok(CHIPS.length <= 4, `${CHIPS.length} chips will not fit at 292px`);
});

// The webview renders agent output, so anything arriving FROM it is untrusted. Executing a
// command id because a message said so would be a real hole — the chat view already validates
// against its declared list, and the rail must not be the softer sibling.
test("only a command the rail actually offers is accepted", () => {
  assert.deepEqual(railAction({ type: "command", command: "interact.agents.team" }),
    { kind: "command", command: "interact.agents.team" });
  assert.equal(railAction({ type: "command", command: "workbench.action.terminal.new" }), null,
    "a command the rail does not offer must be refused, however real it is");
  assert.equal(railAction({ type: "command", command: "interact.agents.stop" }), null,
    "even one of OUR commands is refused unless the rail offers it");
});

test("opening a run passes the id through, and nothing else", () => {
  assert.deepEqual(railAction({ type: "open", runId: "abc" }), { kind: "open", runId: "abc" });
  assert.equal(railAction({ type: "open" }), null);
  assert.equal(railAction({ type: "open", runId: 42 }), null, "a non-string id is not an id");
});

test("junk is refused rather than guessed at", () => {
  for (const junk of [null, undefined, 0, "open", { type: "nope" }, {}]) {
    assert.equal(railAction(junk), null, `${JSON.stringify(junk)} produced an action`);
  }
});

test("a chip the rail offers runs its command", () => {
  const done: string[] = [];
  railRoute({ type: "command", command: "interact.agents.team" }, {
    run: (c) => done.push(c), open: () => {},
  });
  assert.deepEqual(done, ["interact.agents.team"]);
});

test("a command the rail does NOT offer runs nothing", () => {
  // The rail renders agent output. A postMessage naming any command id would be a real hole, so
  // "is it a real command" is not the test — "does this surface offer it" is.
  const done: string[] = [];
  for (const command of ["interact.agents.stop", "workbench.action.terminal.new", ""]) {
    railRoute({ type: "command", command }, { run: (c) => done.push(c), open: () => {} });
  }
  assert.deepEqual(done, []);
});

test("clicking a row opens that run", () => {
  const opened: string[] = [];
  railRoute({ type: "open", runId: "abc" }, { run: () => {}, open: (id) => opened.push(id) });
  assert.deepEqual(opened, ["abc"]);
});

test("junk does nothing at all", () => {
  let touched = false;
  const mark = () => { touched = true; };
  for (const junk of [null, undefined, 0, "open", {}, { type: "eval", code: "1" }]) {
    railRoute(junk, { run: mark, open: mark });
  }
  assert.equal(touched, false);
});

// The rail cannot replace the tree until it shows the COMPANY, not just a flat list: who sent
// whom, and who is at the head of it. "A lot of transparency" is that — a roster where a
// sub-agent floats loose beside its lead tells you nothing about who is driving what.
test("the brain is MARKED, and never displaces what needs you", () => {
  // Pinning it to the top was tried and reverted: this surface sorts by who needs you, and a
  // healthy orchestrator burying a crashed agent is exactly the sort the rail replaced.
  const built = buildRail([
    run({ run_id: "boss", status: "running", started_at: 100 }),
    run({ run_id: "worker", status: "failed", started_at: 900 }),
  ], "x", () => 0);
  assert.equal(built.runs[0].run.run_id, "worker", "the crash still leads");
  assert.equal(built.runs.find((r) => r.run.run_id === "boss")?.brain, true);
  assert.equal(built.runs.find((r) => r.run.run_id === "worker")?.brain, false);
});

test("a report sits under its lead, not loose beside it", () => {
  const built = buildRail([
    run({ run_id: "boss", status: "running", started_at: 100 }),
    run({ run_id: "kid", status: "running", parent_run_id: "boss", started_at: 200 }),
    run({ run_id: "other", status: "running", started_at: 300 }),
  ], "x", () => 0);
  // Adjacency is the claim, not position: leads are still ordered by who needs you, so which
  // lead comes first depends on their state. What must hold is that a report is never separated
  // from the lead that sent it.
  const order = built.runs.map((r) => `${r.run.run_id}@${r.depth}`);
  const bossAt = order.indexOf("boss@0");
  assert.ok(bossAt >= 0, `boss missing from ${order.join(" ")}`);
  assert.equal(order[bossAt + 1], "kid@1", "the report must follow its lead immediately");
});

test("a report whose lead is gone is a lead again, never lost", () => {
  // Its parent finished and was cleared. Hiding it would drop a live agent off the roster.
  const built = buildRail([
    run({ run_id: "orphan", status: "running", parent_run_id: "vanished" }),
  ], "x", () => 0);
  assert.equal(built.runs.length, 1);
  assert.equal(built.runs[0].depth, 0);
});

test("within one lead, its reports keep the attention order", () => {
  const built = buildRail([
    run({ run_id: "boss", status: "running", started_at: 100 }),
    run({ run_id: "fine", status: "running", parent_run_id: "boss", started_at: 200 }),
    run({ run_id: "broken", status: "crashed", parent_run_id: "boss", started_at: 300 }),
  ], "x", () => 0);
  assert.deepEqual(built.runs.map((r) => r.run.run_id), ["boss", "broken", "fine"]);
});

test("the rail and the workplace agree on who the brain is", () => {
  // The rule is duplicated because neither module can import the other under the test loader.
  // That is defensible only while the two answers are identical, so this pins it — if they ever
  // diverge, the panel and the building would crown different agents.
  const cases: unknown[][] = [
    [run({ run_id: "a", started_at: 100 }), run({ run_id: "b", parent_run_id: "a", started_at: 200 })],
    [run({ run_id: "late", started_at: 900 }), run({ run_id: "early", started_at: 100 })],
    [run({ run_id: "mine", status: "foreign", started_at: 1 }), run({ run_id: "ours", started_at: 500 })],
    [run({ run_id: "orphan", parent_run_id: "gone", started_at: 50 })],
    [],
  ];
  for (const runs of cases) {
    const fromRail = brainOf(runs as never[]);
    const fromWorld = buildTeam(runs as never[], () => [], 2000).workers.find((w) => w.brain);
    assert.equal(fromRail, fromWorld?.run_id ?? null,
      `disagreement on ${JSON.stringify(runs.map((r) => (r as { run_id: string }).run_id))}`);
  }
});
