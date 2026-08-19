/** What the team is costing, and the open agent's share.
 *
 *  The chat reported one agent's tokens and cost and nothing about the whole, which is the wrong
 *  half for someone who owns the budget: the actionable numbers are what the team is spending and
 *  whether the agent in front of you is a large part of it.
 *
 *  Cost here is API-EQUIVALENT, as everywhere else in interact: on a subscription run it is not
 *  money billed again, and any surface showing it has to say so rather than imply fresh spend.
 */
import type { AgentRun } from "./agents";

export interface TeamSpend {
  total: number;
  agents: number;
  running: number;
  /** The open agent's share, or null when its own cost is not known — `null` is unknown, not
   *  zero, and reporting 0% would assert that this agent is free. */
  sharePercent: number | null;
}

export function teamSpend(runs: readonly AgentRun[], openRunId: string | undefined): TeamSpend {
  // A foreign run is one of the user's own editor sessions: real spend, but not this team's, and
  // counting it would deflate every share below.
  const ours = runs.filter((r) => !r.foreign && r.status !== "foreign");
  const total = ours.reduce((sum, r) => sum + (r.cost_usd ?? 0), 0);
  const open = ours.find((r) => r.run_id === openRunId);
  const share = open?.cost_usd != null && total > 0
    ? Math.round((open.cost_usd / total) * 100)
    : null;
  return {
    total,
    agents: ours.length,
    running: ours.filter((r) => r.status === "running").length,
    sharePercent: share,
  };
}
