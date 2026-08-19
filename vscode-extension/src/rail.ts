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
export const HELD_SECONDS = 120;

/** Why a run wants attention, worst first. The ORDER of this list IS the sort. */
export type Attention = "error" | "asked" | "held" | "finished" | "working" | "not-ours";

const RANK: Attention[] = ["error", "asked", "held", "finished", "working", "not-ours"];

export interface RailRun {
  run: AgentRun;
  attention: Attention;
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
export const CHIPS: RailChip[] = [
  { id: "team", label: "Team", command: "interact.agents.team" },
  { id: "sequence", label: "Sequence", command: "interact.agents.sequence" },
  { id: "board", label: "Board", command: "interact.openDashboard" },
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
export function buildRail(
  runs: readonly AgentRun[],
  scope: string,
  idleOf: (run: AgentRun) => number,
  awaitingReply: (run: AgentRun) => boolean = () => false,
): Rail {
  const rows: RailRun[] = runs.map((run) => {
    const attention = attentionOf(run, idleOf(run), awaitingReply(run));
    return { run, attention, note: NOTES[attention] };
  });

  rows.sort((a, b) => {
    const byRank = RANK.indexOf(a.attention) - RANK.indexOf(b.attention);
    if (byRank !== 0) return byRank;
    // Within a band, most recently started first: the newest error is the one you have not seen.
    return (b.run.started_at ?? 0) - (a.run.started_at ?? 0);
  });

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
export type RailAction =
  | { kind: "command"; command: string }
  | { kind: "open"; runId: string };

export function railAction(message: unknown): RailAction | null {
  if (!message || typeof message !== "object") return null;
  const msg = message as { type?: unknown; command?: unknown; runId?: unknown };
  if (msg.type === "command" && typeof msg.command === "string") {
    const offered = CHIPS.some((c) => c.command === msg.command);
    return offered ? { kind: "command", command: msg.command } : null;
  }
  if (msg.type === "open" && typeof msg.runId === "string" && msg.runId) {
    return { kind: "open", runId: msg.runId };
  }
  return null;
}
