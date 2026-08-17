/** Reading the agent-run registry that the Python side writes.
 *
 *  This process only ever READS: `interact agents` (or an agent calling the MCP tools) owns
 *  spawning and stopping. The panel is a window onto that, which is why a run's status here is
 *  whatever Python derived from the live pid — the extension never guesses liveness itself.
 *
 *  Mirrors `interact.agents.registry` (src/interact/agents/registry.py); tests/test_paths.py
 *  binds the directory the two agree on.
 */
import * as fs from "fs";
import * as path from "path";

import { agentsDir } from "./paths";

/** One supervised run. Mirrors Python's `AgentRun`; unknown fields are ignored so a newer
 *  writer never breaks an older reader. */
export interface AgentRun {
  run_id: string;
  provider: string;
  name: string;
  task?: string;
  cwd?: string;
  status: "running" | "done" | "failed" | "crashed" | "stopped" | "foreign";
  pid?: number | null;
  /** The model the run was launched with, when the spawner knew it (Python records it). */
  model?: string | null;
  parent_run_id?: string | null;
  started_at?: number;
  /** Epoch seconds the run ended. Absent for a run still going — and ALSO for one that died
   *  before the registry could stamp it, which is why the board draws an unknown end rather
   *  than assuming "now". */
  finished_at?: number | null;
  exit_code?: number | null;
  /** API-EQUIVALENT cost. On a subscription run this value is already paid for by the plan — it
   *  must never be presented as fresh spend. `null`/absent means unknown, which is NOT zero. */
  cost_usd?: number | null;
  last?: string;
  foreign?: boolean;
}

/** Is that pid still there?
 *
 *  Node documents signal 0 as an existence probe that sends nothing — the check the Python side
 *  makes with the same intent. It only ever DOWNGRADES a claim: a record saying "running" whose
 *  process is gone is reported crashed. It never promotes anything, so a permission error (EPERM
 *  — the process exists but belongs to another user) correctly counts as alive.
 */
function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return (err as NodeJS.ErrnoException).code === "EPERM";
  }
}

/** Every run record on disk, oldest first. A corrupt record is skipped rather than hiding the
 *  rest — a half-written file during a crash must not blank the whole panel. */
export function readAgentRuns(): AgentRun[] {
  const dir = agentsDir();
  let names: string[];
  try {
    names = fs.readdirSync(dir).filter((n) => n.endsWith(".json"));
  } catch {
    return []; // no registry yet — nothing has been spawned
  }
  const runs: AgentRun[] = [];
  for (const name of names) {
    try {
      const raw = JSON.parse(fs.readFileSync(path.join(dir, name), "utf8"));
      if (!raw || typeof raw.run_id !== "string") continue;
      const run = raw as AgentRun;
      // Liveness is the one field the file cannot vouch for: a crash leaves "running" behind
      // with nothing to correct it, and a row that spins forever is worse than no row.
      if (run.status === "running" && typeof run.pid === "number" && !alive(run.pid)) {
        run.status = "crashed";
      }
      runs.push(run);
    } catch {
      continue;
    }
  }
  return runs.sort((a, b) => (a.started_at ?? 0) - (b.started_at ?? 0));
}

/** Totals for the status line: how many are live, and the API-equivalent value consumed. */
export function summarise(runs: AgentRun[]): { live: number; cost: number } {
  return {
    live: runs.filter((r) => r.status === "running").length,
    cost: runs.reduce((sum, r) => sum + (r.cost_usd ?? 0), 0),
  };
}

/** Indent each run under the one that spawned it, so a cross-provider team reads as a tree.
 *  Depth is capped so a cycle in malformed data can't loop forever. */
export function withDepth(runs: AgentRun[]): { run: AgentRun; depth: number }[] {
  const byId = new Map(runs.map((r) => [r.run_id, r]));
  return runs.map((run) => {
    let depth = 0;
    let cursor = run.parent_run_id;
    const seen = new Set<string>([run.run_id]);
    while (cursor && byId.has(cursor) && !seen.has(cursor) && depth < 8) {
      seen.add(cursor);
      depth += 1;
      cursor = byId.get(cursor)!.parent_run_id;
    }
    return { run, depth };
  });
}

/** One thing an agent did, as the panel needs it: when, and what.
 *
 *  The vendor's raw stream is a provider-specific dialect, so this reads the NORMALISED events
 *  the Python side writes. Anything it cannot parse is skipped rather than throwing — a
 *  half-written line during a crash must not blank a run's history.
 */
export interface AgentActivity {
  kind: string;
  text: string;
  tool?: string | null;
  /** The tool's arguments, already summarised by Python. "used Bash" without the command is a
   *  status line; with it, it is a transcript. */
  tool_input?: string;
}

/** A run's recent activity, oldest last. Bounded by `limit` because a long run's transcript is
 *  unbounded and the panel only ever shows a tail — reading it all to display ten lines would
 *  make every refresh scale with the longest-running agent. */
export function readAgentActivity(runId: string, limit = 40): AgentActivity[] {
  const file = path.join(agentsDir(), `${runId}.jsonl`);
  let text: string;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch {
    return []; // no normalised stream for this run (yet)
  }
  const out: AgentActivity[] = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    try {
      const raw = JSON.parse(line);
      if (raw && typeof raw.kind === "string") {
        out.push({
          kind: raw.kind,
          text: String(raw.text ?? ""),
          tool: raw.tool ?? null,
          tool_input: String(raw.tool_input ?? ""),
        });
      }
    } catch {
      continue;
    }
  }
  return out.slice(-Math.max(1, limit));
}
