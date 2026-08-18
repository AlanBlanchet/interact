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


/** Max characters a row's description may occupy.
 *
 *  The side bar is narrow, so anything past roughly this is clipped by VS Code with no say in
 *  WHERE — which is how every row ended up reading "→ 2b7642ee: Reply wit…". Clipping here
 *  instead means the cut lands on a word boundary and the ellipsis is ours.
 */
const ROW_WIDTH = 72;

/** What a run's row says beside its name.
 *
 *  The last thing that happened gets the whole width when there IS one: elapsed time and cost are
 *  already on the hover and on the dashboard, and competing with them for a narrow row meant the
 *  interesting half — what the agent actually did — was the half that got cut.
 */
export function rowDescription(run: {
  last?: string | null;
  status: string;
  cost_usd?: number | null;
}): string {
  const said = (run.last ?? "").trim();
  if (!said) return `${run.status} · ${formatCost(run.cost_usd)}`;
  if (said.length <= ROW_WIDTH) return said;
  const cut = said.slice(0, ROW_WIDTH);
  const lastSpace = cut.lastIndexOf(" ");
  return `${(lastSpace > ROW_WIDTH / 2 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}
