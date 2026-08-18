/** The team on the board, taken from the building's own team.
 *
 *  This file used to invent its people. It looked harmless — the same names, the same projects, the
 *  same shape of graph — and it was not: a pod's colour is `hash(run_id)` resolved against the other
 *  leads on screen, so inventing the ids invented the colours. `main · any-compute` was `run-d` here
 *  and `run-h` in the building, which is why it came out gold on one panel and green on the other.
 *  Since the pod hue is the ONLY thing tying a report standing three rooms away back to its lead,
 *  the two panels were disagreeing about who is on whose team.
 *
 *  So there is one fixture now and it lives with the workplace. This one SELECTS from it — the runs
 *  that put the panel's own hard cases on screen — and adds the one thing the building genuinely
 *  does not have.
 *
 *  What is selected, and why each is here: a lead with three reports of which one is out at the web,
 *  a second lead with the SAME NAME in another project (the colour is all that separates them), a
 *  report that has finished, one that died, one nobody has touched in over two minutes, a lead on
 *  its own, a lead that has finished, and a session interact did not start.
 *
 *  Every lead in the building is kept even when its reports are not, because the hue allocator is
 *  greedy: it resolves clashes against the whole SET of leads, so dropping one CAN move another.
 *  Keeping the lead set identical is what makes the colours on this board the colours in the
 *  building — the point of the exercise.
 */
import type { Worker } from "../../src/team";
import { fixture as building } from "../workplace/dev/fixture";

/** What one slip needs.
 *
 *  `Worker` is the workplace's view model and carries no clock: a building shows you WHERE somebody
 *  is, so it never needed to say how long they have been there. A board of work orders does — so
 *  this adds the two timestamps the registry already writes (`AgentRun.started_at` /
 *  `finished_at`) and the workplace simply never asked for. Wiring this for real is two fields in
 *  `TeamState`, not a new writer.
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

/** The clock, per run: seconds before the snapshot that it began, and that it ended — or null while
 *  it is still going, which is also what a run that died before the registry could stamp it looks
 *  like. This table is the ONLY thing this file invents, and it invents it because the field exists
 *  in the registry and stops at the workplace's view model.
 *
 *  Ordered as the board should read it: a lead, its reports, the next lead, its reports.
 */
const CLOCK: [runId: string, ago: number, ended: number | null][] = [
  ["run-a", 2_460, null], // main · interact — the session driving this work
  ["run-b", 1_320, null], //   artist · studio
  ["run-c", 372, null], //     researcher · out at the web
  ["run-f", 3_910, 3_480], //  Explore · finished, and pressed down the spike

  ["run-h", 4_355, null], // main · any-compute — same name, different project, different colour
  ["run-j", 5_200, null], //   generalizer · nobody has been back to it, so it is HELD
  ["run-k", 2_040, 726], //    perf-critic · died, so its slip is torn

  ["run-l", 8_050, null], // visual-critic · a lead on its own
  ["run-o", 1_500, 44], //  optimizer · a lead that has finished
  ["run-n", 5_600, null], // codex · somebody else's session
];

export function fixture(at = Date.UTC(2026, 7, 18, 14, 3, 22)): Board {
  const now = Math.floor(at / 1000);
  const people = new Map(building(at).workers.map((w) => [w.run_id, w]));
  const dockets: Docket[] = [];
  for (const [runId, ago, ended] of CLOCK) {
    const w = people.get(runId);
    // A clock line naming a run the building no longer has is a stale fixture, not a slip to draw.
    if (!w) continue;
    dockets.push({ ...w, started_at: now - ago, finished_at: ended === null ? null : now - ended });
  }
  return { at, dockets };
}

/** The state the panel is actually in most of the time: ONE session with one report out.
 *
 *  Worth its own page because it is the case that judges the bottom half of the design. A full
 *  board hides the question — the pile reaches the composer and there is nothing to look at below
 *  it. A quiet board is two inches of paper and then the rest of the panel, and whatever that rest
 *  is has to be as deliberate as the part with the work on it. It was not, which is what the desk
 *  is for.
 */
export function quietBoard(at = Date.UTC(2026, 7, 18, 14, 3, 22)): Board {
  const live = new Set(["run-a", "run-b"]);
  return { at, dockets: fixture(at).dockets.filter((d) => live.has(d.run_id)) };
}

/** The other state a panel has to survive: nothing running at all. */
export function emptyBoard(at = Date.UTC(2026, 7, 18, 14, 3, 22)): Board {
  return { dockets: [], at };
}
