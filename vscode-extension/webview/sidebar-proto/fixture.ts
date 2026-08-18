/** A team, invented but shaped like a real one, so the direction can be judged before it is wired.
 *
 *  Every field here exists in the REGISTRY today (`src/agents.ts`, `AgentRun`) — name, the `agent`
 *  definition, status, `last`, `started_at`/`finished_at`, `cost_usd`, `parent_run_id`, `run_id`.
 *  Nothing on this board is a field somebody would have to invent a writer for. The one gap is
 *  named in `Docket` below.
 *
 *  Chosen to hit the states that break a narrow panel rather than to look tidy: a lead with two
 *  reports, one worker finished, one gone out to the web, one that died, one nobody has touched in
 *  two hours, two leads sharing a NAME in different projects (the pod colour is the only thing
 *  telling them apart), and a session interact did not start.
 */
import type { Worker } from "../../src/team";

/** What one slip needs.
 *
 *  `Worker` is the workplace's view model and carries no clock: a building shows you WHERE somebody
 *  is, so it never needed to say how long they have been there. A board of work orders does — so
 *  this adds the two timestamps the registry already writes and the workplace simply never asked
 *  for. Wiring this for real is two fields in `TeamState`, not a new writer.
 */
export interface Docket extends Worker {
  /** Epoch seconds. Absent on a record written before it was tracked. */
  started_at?: number;
  /** Epoch seconds, or null for a run still going — and ALSO for one that died before the registry
   *  could stamp it, which is why elapsed renders an open end rather than assuming "now". */
  finished_at?: number | null;
}

export interface Board {
  dockets: Docket[];
  /** Wall clock of the snapshot, so elapsed is computed against a fixed instant and a screenshot
   *  taken twice is byte-identical. */
  at: number;
}

type Seed = [
  id: string,
  name: string,
  agent: string | null,
  status: Worker["status"],
  zone: Worker["zone"],
  activity: string,
  parent: string | null,
  project: string,
  cost: number | null,
  idle: number,
  /** Seconds before the snapshot that this run began. */
  ago: number,
  /** Seconds before the snapshot that it ended, or null while it is still going. */
  ended: number | null,
];

const SEEDS: Seed[] = [
  // ── Pod A: the session writing this very panel. A lead and its two reports, one of them out.
  [
    "a", "main", null, "running", "managers",
    "delegating the sidebar direction to the artist",
    null, "interact", 1.9412, 3, 2_460, null,
  ],
  [
    "b", "artist", "artist", "running", "studio",
    "drawing the docket sprites and stamping the statuses",
    "a", "interact", 0.6102, 1, 1_320, null,
  ],
  [
    // Out of the building — the state the workplace draws by putting a person under the sky.
    "c", "researcher", "researcher", "running", "web",
    "reading the CSS masking reference on developer.mozilla.org",
    "a", "interact", 0.221, 0, 372, null,
  ],

  // ── Pod B: another project, a lead with the SAME name. Only the colour separates the two.
  [
    "d", "main", null, "running", "code",
    "editing crates/engine/src/kernels.rs",
    null, "any-compute", 0.7734, 8, 4_355, null,
  ],
  [
    // Finished, and pushed down the spike.
    "e", "Explore", "Explore", "done", "code",
    "read 14 files under crates/engine and answered",
    "d", "any-compute", 0.0483, 240, 3_910, 3_480,
  ],
  [
    // Died. Still needs a person, so it keeps its full height while the finished one does not.
    "f", "perf-critic", "perf-critic", "error", "lab",
    "benchmark harness died at p99 — no baseline was recorded",
    "d", "any-compute", 0.0912, 61, 2_040, 726,
  ],

  // ── A lead on its own that nobody has been back to for two hours.
  [
    "g", "visual-critic", "visual-critic", "running", "studio",
    "measuring contrast on the agents panel",
    null, "interact", 0.2841, 7_412, 8_050, null,
  ],

  // ── Somebody else's session: visible, not ours, and drawn flat because of it.
  [
    "h", "codex", null, "foreign", "idle",
    "",
    null, "unknown", null, 903, 5_600, null,
  ],
];

export function fixture(at = Date.UTC(2026, 7, 18, 14, 3, 22)): Board {
  const now = Math.floor(at / 1000);
  return {
    at,
    dockets: SEEDS.map(
      ([id, name, agent, status, zone, activity, parent, project, cost, idle, ago, ended]) => ({
        run_id: `run-${id}`,
        name,
        agent,
        status,
        zone,
        activity,
        parent_run_id: parent ? `run-${parent}` : null,
        project,
        cost_usd: cost,
        input_tokens: null,
        idle_seconds: idle,
        started_at: now - ago,
        finished_at: ended === null ? null : now - ended,
      }),
    ),
  };
}

/** The other state a panel has to survive: nothing running at all. */
export function emptyBoard(at = Date.UTC(2026, 7, 18, 14, 3, 22)): Board {
  return { dockets: [], at };
}
