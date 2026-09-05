/** Agents and conversations are DIFFERENT THINGS. This module is where that distinction lives.
 *
 *  Alan: "an agent is different than a conversation with an agent... When i click on an agent, i
 *  should be able to view the conversations is had, and go back to the parent if there is one."
 *
 *  An AGENT is a role — `tester`, `visual-critic`, `researcher` — defined by a file holding its
 *  system prompt. It is not a thing that runs; it is a thing you can start. A CONVERSATION is one
 *  engagement WITH that role: it has its own transcript, its own status, its own cost, and it may
 *  have been spawned BY another conversation. One agent, many conversations, arranged in a tree.
 *
 *  The panel used to flatten all of that into a single list of runs, which is why every row said
 *  "claude" and why there was no way in. The data already carried what was needed — `agent` names
 *  the role, `parent_run_id` names the caller — so this is a modelling gap, not a data gap.
 *
 *  Pure and host-free on purpose: no `vscode` import, so it is unit-testable and so the panel can
 *  be re-skinned without touching the meaning of anything here.
 */

export type Run = {
  run_id: string;
  name?: string;
  agent?: string | null;
  task?: string;
  provider?: string;
  status?: string;
  parent_run_id?: string | null;
  project?: string;
  model?: string | null;
};

/** A role you can hold a conversation with, plus every conversation it has had. */
export type Agent = {
  /** The definition name (`tester`), or the provider when a run carries no definition. */
  id: string;
  /** What to call it on screen. */
  label: string;
  /** True when this is a bare CLI with no definition file behind it — worth showing differently,
   *  because "claude" is not a colleague, it is whoever you happened to ask. */
  plain: boolean;
  conversations: Run[];
};

/** How long a task may run as a conversation title before it stops being scannable. */
const TITLE_MAX = 60;

/** A conversation's display name.
 *
 *  The old rule was `run.name || run_id.slice(0,8)`, and since Python records `name` as the
 *  PROVIDER when no definition applies, a screen full of real work all read "claude" — which is
 *  what Alan meant by "the names are not correct". A conversation is best identified by what it is
 *  DOING, so the task wins; the role is a fallback; the id is a last resort.
 */
export function conversationTitle(run: Run): string {
  const task = (run.task ?? "").replace(/\s+/g, " ").trim();
  if (task) return task.length > TITLE_MAX ? task.slice(0, TITLE_MAX - 1).trimEnd() + "…" : task;
  const named = (run.name ?? "").trim();
  const role = (run.agent ?? "").trim();
  // A name that merely repeats the CLI identifies nothing when twenty rows share it.
  if (named && named !== run.provider) return named;
  if (role) return role;
  // Nothing to go on: no task, and a name that only repeats the CLI. A bare id-slice reads as a
  // typo ("run-fore") rather than an identifier, so say what it is and keep just enough of the id
  // to tell two of them apart.
  return `untitled · ${run.run_id.slice(0, 6)}`;
}

/** What the company knows: who coordinates, and which names are just a vendor's binary.
 *
 *  Read from `org.json`, which the prompt repo generates. Optional throughout — interact must work
 *  for someone with no prompt repo at all, and then the provider is genuinely all we know. */
export type Company = {
  coordinator: { id: string; title: string };
  /** The CLI tokens a definition-less run gets recorded under (`claude`, `codex`, …). */
  binaries: string[];
};

/** The role a run was held with.
 *
 *  A run with no `agent` used to fall back to the provider, so a screen of unrelated work all read
 *  "claude" — the vendor's binary standing in for a colleague. The company file now says that the
 *  definition-less case IS the coordinator (its system prompt is `instructions.md`, a real file),
 *  so when the recorded name is merely the CLI's own token, this resolves it there instead.
 *
 *  Only a KNOWN binary is treated that way: a run someone named themselves keeps its name.
 */
export function roleOf(run: Run, company?: Company): { id: string; plain: boolean } {
  const role = (run.agent ?? "").trim();
  if (role) return { id: role, plain: false };
  const named = (run.name ?? run.provider ?? "").trim();
  if (company && named && company.binaries.includes(named)) {
    return { id: company.coordinator.id, plain: false };
  }
  // A name someone CHOSE outranks the vendor's; only a bare repeat of the provider is uninformative.
  const provider = (run.provider ?? "").trim();
  const own = named && named !== provider ? named : provider;
  return { id: own || "agent", plain: true };
}

/** What to CALL that role on screen — the coordinator's own title when it is the coordinator. */
export function agentLabel(run: Run, company?: Company): string {
  const { id } = roleOf(run, company);
  if (company && id === company.coordinator.id) return company.coordinator.title;
  return id;
}

/** Group runs into the agents that held them, most-recently-seen first within each agent.
 *  Order is stable and defined by the caller's run order, so the panel can sort once and trust it. */
export function agentsFrom(runs: Run[]): Agent[] {
  const by = new Map<string, Agent>();
  for (const run of runs) {
    const { id, plain } = roleOf(run);
    let a = by.get(id);
    if (!a) {
      a = { id, label: id, plain, conversations: [] };
      by.set(id, a);
    }
    a.conversations.push(run);
  }
  return [...by.values()];
}

/** The chain from a conversation up to its root, nearest parent first.
 *
 *  Guards against a cycle rather than trusting the data: these ids come from a registry written by
 *  several processes, and a panel that hangs on a malformed parent link is worse than one that
 *  shows a short chain.
 */
export function ancestry(runId: string, runs: Run[]): Run[] {
  const index = new Map(runs.map((r) => [r.run_id, r]));
  const chain: Run[] = [];
  const seen = new Set<string>([runId]);
  let cur = index.get(runId)?.parent_run_id ?? null;
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    const parent = index.get(cur);
    if (!parent) break; // the parent is outside this scope — stop rather than invent a row
    chain.push(parent);
    cur = parent.parent_run_id ?? null;
  }
  return chain;
}

/** The conversations this one spawned. */
export function childrenOf(runId: string, runs: Run[]): Run[] {
  return runs.filter((r) => r.parent_run_id === runId);
}
