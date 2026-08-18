import * as path from "path";

import type { AgentRun } from "./agents";

export interface ChatFile {
  label: string;
  path: string;
}

/** The files behind a run: what it IS, and everything it wrote.
 *
 *  The system prompt's location belongs to the PROVIDER — Claude Code keeps definitions in
 *  `~/.claude/agents/<name>.md`, another CLI will not — so Python resolves it through the provider
 *  at registration and records it on the run. Rebuilding that path here hard-coded one vendor's
 *  layout into a panel that is meant to show runs from several, which meant a non-Claude agent got
 *  a link to a file that does not exist, and therefore no link at all.
 *
 *  The old guess stays as a fallback so runs registered before the path was tracked keep theirs.
 *
 *  Only files that exist are offered: a button that opens nothing is worse than no button.
 */
export function chatFiles(
  run: AgentRun,
  dir: string,
  home: string,
  exists: (p: string) => boolean,
): ChatFile[] {
  const definition = run.definition_path
    ?? (run.agent ? path.join(home, ".claude", "agents", `${run.agent}.md`) : null);
  const candidates: ChatFile[] = [
    ...(definition ? [{ label: "system prompt", path: definition }] : []),
    { label: "transcript", path: path.join(dir, `${run.run_id}.jsonl`) },
    { label: "raw stream", path: path.join(dir, `${run.run_id}.raw.jsonl`) },
    { label: "messages", path: path.join(dir, `${run.run_id}.messages.jsonl`) },
  ];
  return candidates.filter((f) => exists(f.path));
}
