/** A team, invented but shaped like a real one, so the view can be looked at before it is wired.
 *
 *  Chosen to hit the cases that actually break a layout rather than to look tidy: two leads with
 *  the SAME name in different projects (the pod colour is the only thing telling them apart), a
 *  report three levels down, reports scattered across four rooms away from their lead, an empty
 *  room, a stalled "running" worker, an errored one, and a session interact did not start.
 */
import type { TeamState, Worker, ZoneId } from "../../../src/team";

type Seed = [
  name: string,
  agent: string | null,
  status: Worker["status"],
  zone: ZoneId,
  activity: string,
  parent: string | null,
  project: string,
  cost: number | null,
  idle: number,
];

const SEEDS: Seed[] = [
  // Pod A — a session driving this very piece of work, its people spread over four rooms.
  ["main", null, "running", "managers", "delegating the workplace view to the artist", null, "interact", 1.94, 3],
  ["artist", "artist", "running", "studio", "drawing the pixel sprites for the team room", "a", "interact", 0.61, 1],
  ["researcher", "researcher", "running", "web", "searching the web for pixel art css techniques", "a", "interact", 0.22, 0],
  ["scraper", "scraper", "running", "web", "pulling the tilemap gallery", "c", "interact", 0.08, 6],
  ["tester", "tester", "running", "lab", "running the webview suite", "a", "interact", 0.34, 12],
  ["Explore", "Explore", "done", "code", "read 14 files under webview/", "a", "interact", 0.05, 240],
  ["librarian", "librarian", "done", "library", "synced paradigms/creative.md", "a", "interact", 0.41, 320],

  // Pod B — another project entirely, same lead NAME, different colour.
  ["main", null, "running", "code", "editing crates/engine/src/kernels.rs", null, "any-compute", 0.77, 8],
  ["code-reviewer", "code-reviewer", "running", "code", "reviewing the diff against the ideology", "h", "any-compute", 0.19, 2],
  ["generalizer", "generalizer", "running", "code", "auditing the Tensor base class", "h", "any-compute", 0.16, 150],
  ["perf-critic", "perf-critic", "error", "lab", "benchmark harness died at p99", "h", "any-compute", 0.09, 61],

  // Pod C — a lead whose own parent has already been forgotten by the registry.
  ["visual-critic", "visual-critic", "running", "studio", "measuring contrast on the agents panel", null, "interact", 0.28, 4],
  ["ux-critic", "ux-critic", "running", "studio", "walking the surface graph from cold entry", "l", "interact", 0.12, 9],

  // Someone else's session, and someone who has finished and come back to the door.
  ["codex", null, "foreign", "idle", "", null, "unknown", null, 900],
  ["optimizer", "optimizer", "done", "entry", "handed the hot path back", null, "any-compute", 0.53, 44],
];

const ID = "abcdefghijklmnopqrstuvwxyz";

export function fixture(at = Date.UTC(2026, 7, 18, 14, 3, 22)): TeamState {
  const workers: Worker[] = SEEDS.map(
    ([name, agent, status, zone, activity, parent, project, cost, idle], i) => ({
      run_id: `run-${ID[i]}`,
      name,
      agent,
      status,
      zone,
      activity,
      parent_run_id: parent ? `run-${parent}` : null,
      project,
      cost_usd: cost,
      input_tokens: cost === null ? null : Math.round(cost * 42000),
      idle_seconds: idle,
    }),
  );
  // Real exchanges, both ends present. `run-a` is the first seed, `run-b` the second, and so on.
  const links = [
    { from_run_id: "run-c", to_run_id: "run-b", text: "css: use box-shadow steps for the sprite, not a png" },
    { from_run_id: "run-b", to_run_id: "run-a", text: "sprites are in — need the zone list frozen" },
    { from_run_id: "run-j", to_run_id: "run-h", text: "Tensor base re-declares device in three leaves" },
    { from_run_id: "run-k", to_run_id: "run-h", text: "harness died at p99, re-running with a smaller batch" },
    { from_run_id: "run-m", to_run_id: "run-l", text: "entry is reachable from cold, the panel is not" },
  ];
  return { workers, at, links } as TeamState;
}

/** The same team a moment later: three people have moved room and several have said something
 *  new. Rendering this straight after `fixture()` is how the walk is exercised — the view has to
 *  produce travel from the difference alone, with nothing telling it who moved. */
export function fixtureMoved(at = Date.UTC(2026, 7, 18, 14, 3, 31)): TeamState {
  const state = fixture(at);
  const move = (name: string, zone: ZoneId, activity: string) => {
    const w = state.workers.find((x) => x.name === name);
    if (w) {
      w.zone = zone;
      w.activity = activity;
      w.idle_seconds = 0;
    }
  };
  // Two exchanges that did NOT exist a moment ago: the couriers must carry exactly these, and
  // must not re-carry the five that were already on screen.
  (state as { links: { from_run_id: string; to_run_id: string; text: string }[] }).links.push(
    { from_run_id: "run-a", to_run_id: "run-l", text: "can you look at the workplace panel when it lands?" },
    { from_run_id: "run-h", to_run_id: "run-a", text: "kernels.rs is green, moving to the reduce path" },
  );
  move("researcher", "managers", "reporting back what the web had");
  move("artist", "code", "writing webview/workplace/scene.ts");
  move("tester", "entry", "done — suite is green");
  move("scraper", "data", "filing the gallery into the cache");
  const t = state.workers.find((x) => x.name === "tester");
  if (t) t.status = "done";
  return state;
}
