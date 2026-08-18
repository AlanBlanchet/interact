/** Turning what an agent is DOING into where it stands.
 *
 *  The workplace only means anything if a worker's position is earned: someone in the Web room is
 *  there because they are fetching a page right now. This is the pure half of that — no I/O, no
 *  rendering — so the mapping can be argued with in tests rather than eyeballed on a canvas.
 */
import type { TeamState, Worker, ZoneId } from "./team";

/** One recorded step, as the panel already reads them. */
export interface Step {
  kind: string;
  tool?: string | null;
  tool_input?: string;
  text?: string;
}

/** Tools grouped by the ROOM they are done in, not by what they technically are. A screenshot and
 *  a click are both "studio" because judging a surface is one job done in one place. */
const ROOMS: [ZoneId, RegExp][] = [
  ["web", /^(WebFetch|WebSearch)$/],
  ["code", /^(Read|Edit|Write|Grep|Glob|NotebookEdit|MultiEdit)$/],
  ["managers", /^(Agent|Task|SendMessage|ListAgents|TaskOutput|TaskStop)$/],
  // Anything that looks at or drives a surface — interact's own tools live here.
  ["studio", /(screenshot|run_actions|review_ui|verify_ui|measure_ui|launch_app|record|get_interactive)/i],
  ["lab", /^(Bash|BashOutput|KillShell)$/],
  ["data", /(registry|cache|catalog|benchmark)/i],
  ["library", /(Skill|librarian|prompt)/i],
];

/**
 * Where a worker stands.
 *
 * Status wins over activity: a finished worker is back at the entrance whatever it was last
 * holding, and a session interact did not start is never shown mid-task — watching it work would
 * claim a supervision we do not have.
 */
export function zoneOf(step: Step | undefined, status: string): ZoneId {
  if (status === "foreign") return "idle";
  if (status !== "running") return "entry";
  if (!step) return "idle";
  if (step.kind === "spawn") return "managers";
  if (step.kind === "tool" && step.tool) {
    for (const [zone, pattern] of ROOMS) {
      if (pattern.test(step.tool)) return zone;
    }
  }
  // Thinking, speaking, or a tool nobody has taught us: still at their desk, not thrown out.
  return "managers";
}

/** The last path-looking token in a tool's arguments — what a person would name. */
function subject(input: string | undefined): string | null {
  const match = (input ?? "").match(/[\w./-]*\/([\w.-]+\.\w+)/);
  if (match) return match[1];
  const quoted = (input ?? "").match(/'([^']{3,40})'|"([^"]{3,40})"/);
  return quoted ? quoted[1] ?? quoted[2] ?? null : null;
}

/** What they would SAY they are doing. "reading registry.py", not "tool: Read". */
export function activityOf(step: Step | undefined): string {
  if (!step) return "waiting";
  if (step.kind === "tool" && step.tool) {
    const what = subject(step.tool_input);
    // With nothing to name, the verb alone reads oddly ("reading"), so fall back to the tool.
    if (!what) return `running ${step.tool}`;
    return `${VERBS[step.tool] ?? "running"} ${what}`;
  }
  if (step.kind === "spawn") return `sending out ${step.text || "a teammate"}`;
  if (step.kind === "thinking") return "thinking";
  if (step.kind === "message") return "in conversation";
  const said = (step.text ?? "").trim().replace(/\s+/g, " ");
  return said ? clip(said) : "waiting";
}

const VERBS: Record<string, string> = {
  Read: "reading",
  Edit: "editing",
  Write: "writing",
  Grep: "searching",
  Glob: "looking for",
  Bash: "running",
  WebFetch: "fetching",
  WebSearch: "searching the web for",
  Agent: "briefing",
  Task: "briefing",
  SendMessage: "messaging",
};

function clip(text: string): string {
  return text.length <= 48 ? text : `${text.slice(0, 47).trimEnd()}…`;
}


/** A run as the registry stores it — only the fields the workplace needs. */
export interface RunLike {
  run_id: string;
  name: string;
  agent?: string | null;
  status: string;
  project?: string;
  cost_usd?: number | null;
  input_tokens?: number | null;
  parent_run_id?: string | null;
  finished_at?: number | null;
  started_at?: number;
}

/**
 * The whole room, from the runs on disk plus each one's latest step.
 *
 * `latestStep` is passed in rather than read here so this stays pure: the view can be driven from
 * a fixture, and the test above does not need a registry on disk to place a researcher at the web.
 */
export function buildTeam(
  runs: RunLike[],
  latestStep: (runId: string) => Step | undefined,
  now: number = Date.now() / 1000,
): TeamState {
  const workers: Worker[] = runs.map((run) => {
    const step = latestStep(run.run_id);
    const since = run.finished_at ?? run.started_at ?? now;
    return {
      run_id: run.run_id,
      name: run.name || run.run_id.slice(0, 8),
      agent: run.agent ?? null,
      status: (run.status as Worker["status"]) ?? "done",
      zone: zoneOf(step, run.status),
      activity: activityOf(step),
      parent_run_id: run.parent_run_id ?? null,
      project: run.project ?? "",
      cost_usd: run.cost_usd ?? null,
      input_tokens: run.input_tokens ?? null,
      idle_seconds: Math.max(0, now - since),
    };
  });
  return { workers, at: now };
}
