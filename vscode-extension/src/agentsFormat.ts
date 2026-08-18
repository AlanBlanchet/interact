/** The Agents panel's pure decisions — no `vscode` import, so they are unit-testable.
 *
 *  Same discipline as `paths.ts`: anything that can be decided without the extension host lives
 *  here and is pinned by `agentsFormat.test.ts`, because the panel's whole job is to tell the
 *  truth at a glance and those are exactly the judgements that go quietly wrong.
 */
import * as path from "path";

import type { AgentRun } from "./agents";

export type GroupBy = "project" | "provider" | "model" | "flat";



/** API-EQUIVALENT value: a subscription run already paid for it. `null` is UNKNOWN and renders an
 *  em dash — "$0.00" would claim the run was free, which is a different and wrong fact. */
export function formatCost(cost: number | null | undefined): string {
  return cost == null ? "—" : `~$${cost.toFixed(4)}`;
}

/** Time on the clock: counting up while it runs, frozen at its end once it has one. */
export function formatElapsed(run: AgentRun): string {
  const start = (run.started_at ?? 0) * 1000;
  if (!start) return "";
  const end = run.finished_at ? run.finished_at * 1000 : Date.now();
  const s = Math.max(0, Math.floor((end - start) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function groupKeyFor(run: AgentRun, by: GroupBy): string {
  // Prefer the project Python derived (the repo root). Falling back to the directory name keeps
  // records written before that field existed grouping sensibly rather than vanishing.
  if (by === "project") {
    return run.project || (run.cwd ? path.basename(run.cwd) : "(no project)");
  }
  if (by === "provider") return run.provider || "(unknown)";
  if (by === "model") return run.model || "(default model)";
  return "";
}

/** Live work first. A sidebar you must scroll to find the running agent in has failed at its one
 *  job; ties fall back to name so the order is stable between refreshes. */
export function orderGroups(groups: [string, AgentRun[]][]): [string, AgentRun[]][] {
  const live = (rs: AgentRun[]) => rs.filter((r) => r.status === "running").length;
  return [...groups].sort((a, b) => live(b[1]) - live(a[1]) || a[0].localeCompare(b[0]));
}

