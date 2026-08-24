/** The TEAM as a workplace — the shape both the data layer and the view are built to.
 *
 *  The panel so far answered "which runs exist". This answers "what is my team DOING right now":
 *  each worker stands in the ZONE matching the work in flight — out at the web, in the code, at
 *  the library — so a glance reads as a room full of people rather than a list of rows.
 *
 *  This file is the CONTRACT and nothing else: it holds no rendering and no I/O, so the view and
 *  the data that feeds it can be built at the same time without drifting.
 */

/** Where a worker is standing. Zones are places in a workplace, not tool categories: the point is
 *  that a person is AT the library, not that they called a `Read`. */
export type ZoneId =
  | "entry" // where a request arrives and where a finished worker returns
  | "managers" // orchestrating: spawning, delegating, waiting on others
  | "code" // reading and writing the source
  | "data" // the registry, caches, the stores on disk
  | "web" // out of the building: research, fetching, the world
  | "library" // the prompts, the definitions, the docs
  | "studio" // anything visual — screenshots, driving an app, judging pixels
  | "lab" // tests, measurements, verification
  | "idle"; // present but not working

export interface Zone {
  id: ZoneId;
  /** What the sign on the door says. */
  label: string;
}

/** Read in the order a workplace map should lay them out: the door first, the back rooms last. */
export const ZONES: Zone[] = [
  { id: "entry", label: "Entry" },
  { id: "managers", label: "Managers" },
  { id: "code", label: "Code" },
  { id: "data", label: "Data" },
  { id: "web", label: "Web" },
  { id: "library", label: "Library" },
  { id: "studio", label: "Studio" },
  { id: "lab", label: "Lab" },
  { id: "idle", label: "Break room" },
];

export interface Worker {
  run_id: string;
  /** The name on the badge — the agent definition where there is one. */
  name: string;
  agent: string | null;
  /** How many errands this agent was given. One body stands for all of them. */
  tasks?: number;
  status: "running" | "done" | "error" | "foreign";
  zone: ZoneId;
  /** What they are doing, in words a person would say: "reading registry.py". */
  activity: string;
  /** Who sent them. A sub-agent stands with its parent, in the parent's own context. */
  parent_run_id: string | null;
  project: string;
  cost_usd: number | null;
  input_tokens: number | null;
  /** Seconds since this worker last did anything — how the view fades the ones who have stopped. */
  idle_seconds: number;
  /** The registry's own clock, carried so no view has to invent one. Optional because a fixture
   *  or an older record may not have it — a view must not assume a clock exists. */
  started_at?: number | null;
  finished_at?: number | null;
  /** The DOMAIN of work this one belongs to — the department its definition is filed under in the
   *  company file (quality, production, research, records, wealth). The org already declared these
   *  with rooms of their own and placement ignored every one, so a finance agent stood in the same
   *  room as a code reviewer. Absent when the definition is in no department: a wrong room
   *  silently merges unrelated work, which is worse than an unplaced character. */
  department?: string;
  /** That department's room name, as the company file words it ("Wealth Desk"). */
  room?: string;
  /** The orchestrator: the first agent YOU asked for something, which then put the others to
   *  work. Exactly one per team, and never one of your own editor sessions — interact does not
   *  drive those, so crowning one would claim an authority the view does not have. Without it
   *  every character stood at the same rank, which is why the building read as a bag of sprites
   *  rather than a company. */
  brain?: boolean;
  /** What this one can actually DO, inherited from its own definition file — reads / writes /
   *  runs / sees / searches / delegates. Empty for a plain run with no definition: inventing a
   *  power for it would misreport what is loose in your workspace, which is the point of showing
   *  this at all. See `capabilities.ts`. */
  faculties?: string[];
}

/** One agent addressing another — the thing that makes a set of workers a TEAM rather than a
 *  set of processes. Drawn between the rooms the two ends are standing in. */
export interface Link {
  /** When this exchange happened. Without it a view cannot tell "they just spoke" from "they
   *  spoke an hour ago", so on a cold open it can only stay silent — which is half of "no agents
   *  talk to each other". Optional: absent on messages recorded before it was stamped. */
  at?: number | null;
  from_run_id: string;
  to_run_id: string;
  /** What was said, clipped — enough to read the exchange, not the whole message. */
  text: string;
}

export interface TeamState {
  workers: Worker[];
  /** Who has spoken to whom. Optional: a renderer may ignore it, but without it the room shows
   *  people standing in it rather than a team working together. */
  links?: Link[];
  /** Wall-clock of this snapshot, so the view can age what it draws. */
  /** SECONDS since the epoch, matching Python's `time.time()` — the unit every timestamp in this
   *  state uses (`started_at`, `finished_at`, `Link.at`, `AgentActivity.at`).
   *
   *  Spelled out because it was not, and a bare `number` cost a real bug: the view read it with
   *  `new Date(state.at)`, which wants MILLISECONDS, so the panel rendered a 1970 clock on every
   *  render. It survived a whole arc because the dev fixtures stamped `Date.UTC(...)` — already
   *  milliseconds — so the harness showed a correct time while the product showed 1970. */
  at: number;
}

/** Workers that answer to nobody — the top of each tree. */
export function leads(workers: Worker[]): Worker[] {
  const ids = new Set(workers.map((w) => w.run_id));
  return workers.filter((w) => !w.parent_run_id || !ids.has(w.parent_run_id));
}

/** Who this worker sent out. A sub-agent belongs beside its parent, not loose in the room. */
export function reportsOf(workers: Worker[], runId: string): Worker[] {
  return workers.filter((w) => w.parent_run_id === runId);
}
