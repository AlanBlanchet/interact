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
import { readForeignActivity } from "./foreignSession";
import { livenessOf } from "./runStatus";

/** One supervised run. Mirrors Python's `AgentRun`; unknown fields are ignored so a newer
 *  writer never breaks an older reader. */
export interface AgentRun {
  run_id: string;
  provider: string;
  name: string;
  task?: string;
  cwd?: string;
  /** The repo/package this run belongs to, derived by Python from the repo root — NOT the working
   *  directory's own name, which splits one project across several groups. */
  project?: string;
  status: "running" | "done" | "failed" | "crashed" | "stopped" | "foreign"
    /** Declared in the company file, never yet asked for anything — a synthetic entry the panel
     *  makes so the whole roster stands in the world ("some other agents exist but aren't used"). */
    | "declared";
  pid?: number | null;
  /** The DEFINITION this run is — resolves to the file holding its system prompt. */
  agent?: string | null;
  /** Where that definition's system prompt actually lives, resolved by Python THROUGH the
   *  provider at registration — so the link works for a CLI that does not keep its definitions
   *  where Claude Code does. Absent on runs registered before it was tracked. */
  definition_path?: string | null;
  /** The autonomy this run was started under, when somebody chose one. Absent means nobody did,
   *  so the CLI's own configured default applied — which is not the same as unrestricted. */
  permission_mode?: string | null;
  /** Cumulative token use: how much CONTEXT it has consumed, which a cost figure alone hides. */
  input_tokens?: number | null;
  output_tokens?: number | null;
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

/** Did this run's own stream reach an end? Read from the normalised mirror, so it costs one small
 *  read and needs no knowledge of any vendor's dialect. */
function streamEnded(runId: string): boolean {
  return readAgentActivity(runId, 4).some((a) => a.kind === "done" || a.kind === "error");
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
      // Liveness is the one field the file cannot vouch for. The agent's own stream is consulted
      // too: a detached run's exit code is written by nobody, so the probe alone called every
      // finished agent a crash at the moment it succeeded.
      run.status = livenessOf(
        run.status,
        run.pid,
        typeof run.pid === "number" ? alive(run.pid) : false,
        run.status === "running" ? streamEnded(run.run_id) : false,
        // Did it ever say anything? A vanished run that wrote a transcript finished; one that
        // wrote nothing is what a crash looks like. Only consulted when the stream cannot tell.
        Boolean(run.last) || Boolean(run.output_tokens),
      );
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
  /** The vendor's tool_use id, on the call AND its result — the stable key that opens the FULL
   *  input/output for one call out of the raw stream (the summary above is clipped by design). */
  tool_id?: string;
  /** For a message: who sent it and who received it. "operator" is a person; anything else is
   *  another agent — which is the difference between you talking to it and a TEAM talking. */
  from_run?: string | null;
  to_run?: string | null;
  /** When interact FIRST OBSERVED this line — the vendor writes no timestamp, but interact
   *  watches the stream, so this is the honest clock. It is what tells a view that an agent is
   *  working rather than stopped, and what lets a message fire once at the right moment. Absent
   *  on records written before stamping existed. */
  at?: number | null;
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
          tool_id: typeof raw.tool_id === "string" ? raw.tool_id : "",
          // Who a message is from — without it every message reads as yours, so an agent
          // talking to another agent looked exactly like you talking to it.
          from_run: raw.from_run ?? null,
          to_run: raw.to_run ?? null,
          // WHEN interact observed this line. Declared and documented on AgentActivity from the
          // start, and never copied out here — so `lastObservedAt` always returned null, every
          // run's idle time computed as 0, and HELD became a state that exists, is styled, is in
          // the shared vocabulary, and could not once be reached. A field the type promises and
          // the reader drops is invisible to the compiler and to every UI test.
          at: typeof raw.at === "number" ? raw.at : null,
        });
      }
    } catch {
      continue;
    }
  }
  return out.slice(-Math.max(1, limit));
}

/** A run's activity, whichever kind of run it is: interact's own normalised stream, or — for a
 *  session interact did not start — the provider's transcript, mapped. One call site, one rule. */
export function activityOf(run: AgentRun, limit = 40): AgentActivity[] {
  return run.status === "foreign"
    ? readForeignActivity(run, limit)
    : readAgentActivity(run.run_id, limit);
}

/** Where the child wrote its OWN stream, verbatim — full tool inputs and outputs live here.
 *  Mirrors Python's `raw_events_path`. */
export function rawEventsPath(runId: string): string {
  return path.join(agentsDir(), `${runId}.raw.jsonl`);
}

/** One agent addressing another. Written by Python to `<run_id>.messages.jsonl` on BOTH sides,
 *  so this dedupes — the same exchange appears in the sender's file and the recipient's. */
export interface AgentMessage {
  from_run: string;
  to_run: string;
  text: string;
  /** When the exchange was recorded. Absent on messages written before it was stamped. */
  at?: number | null;
}

/** Every recorded exchange, in file order. These are the edges a sequence view draws; without
 *  them the panel can only show monologues side by side. */
export function readAgentMessages(): AgentMessage[] {
  const dir = agentsDir();
  let names: string[];
  try {
    names = fs.readdirSync(dir).filter((n) => n.endsWith(".messages.jsonl"));
  } catch {
    return [];
  }
  const seen = new Set<string>();
  const out: AgentMessage[] = [];
  for (const name of names.sort()) {
    let text: string;
    try {
      text = fs.readFileSync(path.join(dir, name), "utf8");
    } catch {
      continue;
    }
    for (const line of text.split("\n")) {
      if (!line.trim()) continue;
      try {
        const raw = JSON.parse(line);
        if (!raw?.from_run || !raw?.to_run) continue;
        const key = `${raw.from_run} ${raw.to_run} ${raw.text ?? ""}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ from_run: raw.from_run, to_run: raw.to_run, text: String(raw.text ?? "") });
      } catch {
        continue;
      }
    }
  }
  return out;
}
