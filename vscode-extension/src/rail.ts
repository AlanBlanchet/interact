/** The rail: what the panel shows at rest, decided without a `vscode` import.
 *
 *  This is the chosen replacement for the tree + chat split, and the reason it must be a webview
 *  rather than a `TreeView` is measured, not stylistic: VS Code hides a view's title actions until
 *  the pointer enters the header (`.pane-header > .actions { display: none }`) and CLIPS the
 *  overflow with no "…" menu to recover from. So a resting panel rendered ZERO buttons, and the
 *  team view — the thing most worth reaching — could only be found by hovering and guessing among
 *  unlabelled glyphs. No arrangement of icons fixes that inside a tree, at any width. A webview
 *  draws its own chrome, which can simply be visible.
 *
 *  Two decisions live here, and they are what make this a SUPERVISION surface rather than a list:
 *
 *  - the roster is ordered by WHO NEEDS YOU, not by identity. With a couple of dozen seats and ten
 *    runs, alphabetical order buries the one thing that went wrong somewhere in the middle;
 *  - the destinations are LABELLED. An icon you have to hover to identify is not a destination,
 *    it is a guess.
 */

import type { AgentRun } from "./agents";

/** How long a running agent may say nothing before it is worth your attention. The same threshold
 *  the workplace uses for a stalled worker — one number, or the two surfaces disagree about the
 *  word "stuck". */
/** Mirrors `HELD_AFTER_SECONDS` in `statusLanguage.ts`, which is the rule's home.
 *
 *  It is duplicated rather than imported for one mechanical reason: this module is loaded DIRECTLY
 *  by `node --test`, which cannot resolve an extensionless sibling import, and tsc will not emit
 *  the `.ts` specifier that loader needs. So the value is mirrored and the EQUALITY is enforced by
 *  a test — the divergence is what actually hurts (the roster calling someone stuck while the
 *  world still shows them working), not the second `const`.
 */
export const HELD_SECONDS = 120;

/** Why a run wants attention, worst first. The ORDER of this list IS the sort. */
export type Attention = "error" | "asked" | "held" | "finished" | "working" | "not-ours";

const RANK: Attention[] = ["error", "asked", "held", "finished", "working", "not-ours"];

export interface RailRun {
  run: AgentRun;
  attention: Attention;
  /** The orchestrator — the first agent you asked, which put the others to work. Marked rather
   *  than pinned to the top: this surface sorts by who NEEDS you, and a healthy boss must never
   *  bury a crashed agent. */
  brain: boolean;
  /** How many errands this row stands for. Above 1 only at the top level, where a row is an
   *  AGENT — the same unit the map draws — and the worst of its errands speaks for it. */
  tasks?: number;
  /** 0 for a lead, 1 for somebody a lead sent out. The rail cannot replace the tree until it
   *  shows the COMPANY rather than a flat list — a sub-agent floating loose beside its lead tells
   *  you nothing about who is driving what. */
  depth: number;
  /** What the row says about its state, in the reader's words rather than the registry's. */
  note: string;
}

/** What a run needs from you right now.
 *
 *  `foreign` sorts last deliberately: one of your own editor sessions is not the team's work, and
 *  you cannot act on it from here, so it must never outrank an agent that actually stopped.
 */
export function attentionOf(run: AgentRun, idleSeconds: number, awaitingReply = false): Attention {
  if (run.status === "foreign") return "not-ours";
  if (run.status === "failed" || run.status === "crashed") return "error";
  if (run.status === "running") {
    if (awaitingReply) return "asked";
    return idleSeconds >= HELD_SECONDS ? "held" : "working";
  }
  // done / stopped: finished work is worth seeing once, then it should stop competing.
  return "finished";
}

export interface RailChip {
  id: string;
  label: string;
  command: string;
}

/** The destinations — always visible, always named.
 *
 *  Deliberately few. The old title bar carried seven actions and clipped the seventh at every
 *  width; the fix is not a smaller icon, it is fewer destinations with words on them.
 */
/** Where this panel can send you.
 *
 *  Two, not four. "The sidepanel is there to view info about who we click on, and view the
 *  conversation... That's all." The dashboard and the sequence view are their own surfaces and stay
 *  in the command palette; a 299px column whose job is the roster and the reply should not spend a
 *  fifth of its header being a launcher for them. What survives is the world you watch and the way
 *  to start someone new — the two things you cannot do anywhere else.
 */
export const CHIPS: RailChip[] = [
  { id: "team", label: "Team", command: "interact.agents.team" },
  { id: "company", label: "Company", command: "interact.agents.spawn" },
];

export interface RailHeader {
  /** The workspace being shown — the answer to "whose agents are these?", which the tree only
   *  ever gave you inside a dialog you had to know to open. */
  scope: string;
  working: number;
  needsYou: number;
  finished: number;
}

export interface Rail {
  header: RailHeader;
  chips: RailChip[];
  runs: RailRun[];
  /** The agent whose conversations you are looking at, if you have gone into one. An agent is a
   *  ROLE — you can hold many conversations with it — so "inside tester" is a real place in this
   *  panel, and the breadcrumb is how you leave it. Absent means the whole team. */
  filter?: string;
}

const NOTES: Record<Attention, string> = {
  error: "stopped with an error",
  asked: "asked you something",
  held: "nothing for a while",
  finished: "finished",
  working: "working",
  "not-ours": "your own session",
};

/** The whole rail, from the runs in scope.
 *
 *  `idleOf` and `awaitingReply` are passed in rather than read here, so this module stays free of
 *  the filesystem and of `vscode` — the same discipline as `agentsFormat.ts`, and what lets every
 *  decision below be tested without an extension host.
 */
/** The orchestrator: the earliest ROOT run that is ours — the first agent you asked for
 *  something, which then put the others to work.
 *
 *  DUPLICATED from `teamState.ts` on purpose, and the duplication is pinned by a test that runs
 *  both against the same input. Neither module can import the other: both are loaded directly by
 *  the test runner, which demands ".ts" specifiers that tsc refuses to emit, so a shared import
 *  would make one of them untestable. Six lines copied beats a module that cannot be tested.
 */
export function brainOf(runs: readonly AgentRun[]): string | null {
  const ours = runs.filter((r) => r.status !== "foreign");
  const ids = new Set(ours.map((r) => r.run_id));
  const roots = ours.filter((r) => !r.parent_run_id || !ids.has(r.parent_run_id));
  if (!roots.length) return null;
  return roots.reduce((first, r) =>
    (r.started_at ?? Infinity) < (first.started_at ?? Infinity) ? r : first).run_id;
}

export function buildRail(
  runs: readonly AgentRun[],
  scope: string,
  idleOf: (run: AgentRun) => number,
  awaitingReply: (run: AgentRun) => boolean = () => false,
  /** Narrow to one agent's conversations. Applied FIRST, so counts, leads and reports all describe
   *  the thing you are actually looking at rather than the team behind it. */
  filter?: { agent: string; roleOf: (run: AgentRun) => string },
  /** WHO holds each run. When present and NOT drilled in, the roster GROUPS: one row per agent,
   *  exactly the unit the map draws — the cold sweep's root coherence finding was one sprite per
   *  role beside sixteen run-rows, with nothing reconciling them. */
  identify?: (run: AgentRun) => { id: string; label: string },
): Rail {
  // Your own editor windows are not conversations this panel holds: interact did not start them,
  // cannot send to them and cannot stop them, so they rendered as greyed unactionable rows in a
  // column whose whole job is what you can act on. You are already looking at those windows.
  const held = runs.filter((r) => r.status !== "foreign");
  const inScope = filter ? held.filter((r) => filter.roleOf(r) === filter.agent) : held;
  let rows: RailRun[];
  if (identify && !filter) {
    // One row per AGENT. The errand that most needs him speaks for the row (same rule as the
    // map's characters), and the count carries the rest; drilling in lists them individually.
    const byAgent = new Map<string, AgentRun[]>();
    for (const run of inScope) {
      const { id } = identify(run);
      const bucket = byAgent.get(id);
      if (bucket) bucket.push(run); else byAgent.set(id, [run]);
    }
    rows = [...byAgent.values()].map((bucket) => {
      const speaks = [...bucket].sort((a, b) => {
        const rank = (r: AgentRun) => RANK.indexOf(attentionOf(r, idleOf(r), awaitingReply(r)));
        return rank(a) - rank(b) || (b.started_at ?? 0) - (a.started_at ?? 0);
      })[0];
      const attention = attentionOf(speaks, idleOf(speaks), awaitingReply(speaks));
      return { run: speaks, attention, depth: 0, brain: false, note: NOTES[attention],
               tasks: bucket.length };
    });
  } else {
    rows = inScope.map((run) => {
      const attention = attentionOf(run, idleOf(run), awaitingReply(run));
      return { run, attention, depth: 0, brain: false, note: NOTES[attention] };
    });
  }

  const byAttention = (a: RailRun, b: RailRun) => {
    const byRank = RANK.indexOf(a.attention) - RANK.indexOf(b.attention);
    if (byRank !== 0) return byRank;
    // Within a band, most recently started first: the newest error is the one you have not seen.
    return (b.run.started_at ?? 0) - (a.run.started_at ?? 0);
  };

  // Leads first, each followed immediately by the people it sent out. A run whose lead is not in
  // the list — its parent finished and was cleared — is a lead again rather than dropped, because
  // hiding a live agent is the one thing a roster must never do.
  const present = new Set(rows.map((r) => r.run.run_id));
  const isLead = (r: RailRun) =>
    !r.run.parent_run_id || !present.has(r.run.parent_run_id);
  const reportsOf = new Map<string, RailRun[]>();
  for (const row of rows.filter((r) => !isLead(r))) {
    const under = reportsOf.get(row.run.parent_run_id!) ?? [];
    under.push(row);
    reportsOf.set(row.run.parent_run_id!, under);
  }

  const brainId = brainOf(runs);
  // Leads sort by ATTENTION, not by rank. Pinning the brain to the top was tried and reverted:
  // it contradicts what this surface is for — an agent that crashed outranks the orchestrator
  // quietly working, and burying the crash under a healthy boss is the sort this replaced. The
  // brain is MARKED instead, so you can find it without it displacing what needs you.
  const leads = rows.filter(isLead).sort(byAttention);

  const ordered: RailRun[] = [];
  for (const lead of leads) {
    ordered.push({ ...lead, brain: lead.run.run_id === brainId });
    for (const report of (reportsOf.get(lead.run.run_id) ?? []).sort(byAttention)) {
      ordered.push({ ...report, depth: 1 });
    }
  }
  rows.length = 0;
  rows.push(...ordered);

  const count = (...kinds: Attention[]) => rows.filter((r) => kinds.includes(r.attention)).length;

  return {
    header: {
      scope,
      working: count("working"),
      // What the header exists for: one number saying whether anything wants you. A count of
      // everything running answers "is it busy", which is never the question being asked.
      needsYou: count("error", "asked", "held"),
      finished: count("finished"),
    },
    chips: CHIPS,
    runs: rows,
    filter: filter?.agent,
  };
}

/** What the webview asked for, or null.
 *
 *  The rail renders agent output, so every message arriving FROM it is untrusted. A command is
 *  accepted only if the rail actually OFFERS it — not merely because it is one of ours and not
 *  because it exists: running an arbitrary command id because a message named it is a real hole,
 *  and the chat view already validates the same way. Anything unrecognised produces null, which
 *  the caller ignores; guessing at a malformed message is how a webview becomes an exec surface.
 */
/** The commands a ROW may run. Mirrors `agentActions.ts` and is pinned to it by a test — the two
 *  cannot import each other under the test loader, and an allowlist that drifts from the buttons
 *  either breaks a control or admits one nobody offered. */
const ROW_COMMANDS = new Set([
  "interact.agents.send",
  "interact.agents.show",
  "interact.agents.openConversation",
  "interact.agents.showEvents",
  "interact.agents.stop",
]);

export type RailAction =
  | { kind: "command"; command: string }
  | { kind: "open"; runId: string }
  /** A per-row action: run this command AGAINST this agent. Carries the run id because the
   *  commands it names all operate on one agent, and the panel must not act on whichever
   *  happened to be selected. */
  | { kind: "act"; command: string; runId: string }
  /** Go to an agent's conversations, or back to the whole team when the id is empty. */
  | { kind: "agent"; id: string | null };

/** Changing which project you are looking at. Not a destination chip — the chips are capped to
 *  what fits a narrow sidebar, and this belongs on the scope label itself, which is the thing that
 *  states the answer it changes. Allow-listed here so the webview can ask for it by name. */
export const SCOPE_COMMAND = "interact.agents.workspace";

export function railAction(message: unknown): RailAction | null {
  if (!message || typeof message !== "object") return null;
  const msg = message as { type?: unknown; command?: unknown; runId?: unknown };
  if (msg.type === "agent") {
    const id = typeof (msg as { id?: unknown }).id === "string" ? (msg as { id: string }).id : "";
    return { kind: "agent", id: id || null };
  }
  if (msg.type === "command" && typeof msg.command === "string") {
    const offered = CHIPS.some((c) => c.command === msg.command) || msg.command === SCOPE_COMMAND;
    return offered ? { kind: "command", command: msg.command } : null;
  }
  if (msg.type === "open" && typeof msg.runId === "string" && msg.runId) {
    return { kind: "open", runId: msg.runId };
  }
  if (msg.type === "act" && typeof msg.command === "string" && typeof msg.runId === "string"
      && msg.runId) {
    // Checked against what a row may offer — the same rule as the chips, for the same reason:
    // this surface renders agent output, so "it is a real command" is not the test.
    return ROW_COMMANDS.has(msg.command)
      ? { kind: "act", command: msg.command, runId: msg.runId } : null;
  }
  return null;
}

/** What to do with a message from the webview.
 *
 *  Lives here beside the validation rather than in the provider, so the part that can silently
 *  execute the wrong thing is testable without an extension host — the provider imports `vscode`
 *  and cannot be loaded by the test runner at all.
 */
export interface RailHandlers {
  run: (command: string) => void;
  open: (runId: string) => void;
  act: (command: string, runId: string) => void;
  /** Go to one agent's conversations, or back to the whole team when null. Optional so a host that
   *  does not offer the drill-in simply does not wire it, rather than crashing on a message. */
  agent?: (id: string | null) => void;
}

export function railRoute(message: unknown, handlers: RailHandlers): void {
  const action = railAction(message);
  if (!action) return;
  if (action.kind === "command") handlers.run(action.command);
  else if (action.kind === "act") handlers.act(action.command, action.runId);
  else if (action.kind === "agent") handlers.agent?.(action.id);
  else handlers.open(action.runId);
}
