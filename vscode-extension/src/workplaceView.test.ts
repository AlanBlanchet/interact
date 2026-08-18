import { strict as assert } from "node:assert";
import { test } from "node:test";

import { createRequire } from "node:module";

import { ZONES } from "./team.ts";

// Loaded from the COMPILED output rather than the source: `workplaceView.ts` imports `./team`
// without an extension (tsc emits, so extension-ful imports are not allowed), which node's
// type-stripping loader cannot resolve. Testing the built artifact is also closer to what ships.
const { plainRoom } = createRequire(import.meta.url)("../out/workplaceView.js");

// The plain room is the fallback when the pixel-art bundle is missing or throws. A code-reviewer
// run on this diff flagged that neither branch was covered, and that a bare catch would degrade
// silently for the life of a session with nothing saying why.

const STATE = {
  at: 1000,
  workers: [
    { run_id: "a", name: "reviewer", agent: "code-reviewer", status: "running" as const,
      zone: "code" as const, activity: "reading registry.py", parent_run_id: null,
      project: "interact", cost_usd: 1, input_tokens: 100, idle_seconds: 1 },
    { run_id: "b", name: "researcher", agent: "researcher", status: "running" as const,
      zone: "web" as const, activity: "searching the web", parent_run_id: "a",
      project: "interact", cost_usd: 0, input_tokens: 10, idle_seconds: 0 },
  ],
};

test("every zone gets a room, so nobody can be placed nowhere", () => {
  const html = plainRoom(STATE, "n1");
  for (const zone of ZONES) assert.ok(html.includes(zone.label), `no room for ${zone.label}`);
});

test("a worker stands in its own zone", () => {
  const html = plainRoom(STATE, "n1");
  const code = html.slice(html.indexOf("Code"), html.indexOf("Data"));
  assert.match(code, /reviewer/);
});

test("a sub-agent is drawn inside its parent, not loose in the room", () => {
  const html = plainRoom(STATE, "n1");
  const parent = html.indexOf("reviewer");
  assert.ok(html.indexOf("researcher") > parent, "the report follows the lead it belongs to");
});

test("every worker carries the run id the click-through needs", () => {
  const html = plainRoom(STATE, "n1");
  assert.match(html, /data-run-id="a"/);
  assert.match(html, /data-run-id="b"/);
});

test("an agent's name and activity are escaped — both are agent output", () => {
  const html = plainRoom(
    { at: 1, workers: [{ ...STATE.workers[0], name: "<img src=x>", activity: "</div><script>" }] },
    "n1",
  );
  assert.ok(!html.includes("<img src=x"));
  assert.ok(!html.includes("<script>"));
});

test("an empty team renders a building, not a blank page", () => {
  const html = plainRoom({ at: 1, workers: [] }, "n1");
  assert.match(html, /Entry/);
  assert.match(html, /<html/);
});
