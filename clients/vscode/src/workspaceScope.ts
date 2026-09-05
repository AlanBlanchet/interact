/** Which workspace's agents the panel is showing.
 *
 *  The panel used to show every run on the machine, always. That is the right answer for nobody:
 *  open a folder and you want THAT folder's team, and when a team is running in another checkout
 *  you want to be able to go and look at it. So: default to where you are, switch to anywhere, or
 *  see all of them at once.
 */
import * as fs from "fs";
import * as path from "path";

import type { AgentRun } from "./agents";

export type Scope =
  | { kind: "current" }
  | { kind: "all" }
  | { kind: "project"; name: string };

/** A repo root beats any package manifest inside it. */
const REPO_MARKERS = [".git", ".hg", ".svn"];
/** Only meaningful when nothing above is version-controlled at all. */
const PACKAGE_MARKERS = ["pyproject.toml", "package.json", "Cargo.toml", "go.mod"];

/** The project a directory belongs to — the enclosing REPOSITORY, by name.
 *
 *  Deliberately the same rule as `interact.agents.registry.project_for`, which is what actually
 *  stamps `project` onto a run. If these two ever disagree, the panel filters on a name the
 *  registry never wrote and the folder you have open appears to have no agents at all.
 */
export function projectFor(dir: string): string {
  if (!dir) return "";
  let here: string;
  try {
    here = fs.realpathSync(path.resolve(dir));
  } catch {
    here = path.resolve(dir);
  }
  const chain: string[] = [];
  for (let d = here; ; d = path.dirname(d)) {
    chain.push(d);
    if (path.dirname(d) === d) break;
  }
  for (const markers of [REPO_MARKERS, PACKAGE_MARKERS]) {
    for (const candidate of chain) {
      if (markers.some((m) => fs.existsSync(path.join(candidate, m)))) {
        return path.basename(candidate);
      }
    }
  }
  return path.basename(here);
}

/** Every workspace that actually has agents, for the switcher. */
export function projectsOf(runs: readonly AgentRun[]): string[] {
  return [...new Set(runs.map((r) => r.project).filter((p): p is string => !!p))].sort();
}

/** The runs this scope is looking at. */
export function scopeRuns(
  runs: readonly AgentRun[],
  scope: Scope,
  currentProject: string,
): AgentRun[] {
  if (scope.kind === "all") return [...runs];
  const wanted = scope.kind === "project" ? scope.name : currentProject;
  // No folder open, or one that resolves to nothing: scoping would hide every agent and leave an
  // empty panel that looks broken rather than filtered.
  if (!wanted) return [...runs];
  return runs.filter((r) => r.project === wanted);
}

/** What the panel is showing, in the words the title bar uses. */
export function describeScope(scope: Scope, currentProject: string): string {
  if (scope.kind === "all") return "all workspaces";
  if (scope.kind === "project") return scope.name;
  return currentProject || "all workspaces";
}


export interface ScopeChoice {
  label: string;
  detail?: string;
  scope: Scope;
}

/** What the workspace switcher offers, in order.
 *
 *  The folder you have open comes first because it is what you want nearly every time; "all"
 *  second because it is the other habitual answer; then every other workspace that has agents,
 *  which is the case he actually hit — a team running in a checkout he was not in, with no way to
 *  go and look at it.
 */
export function scopeChoices(runs: readonly AgentRun[], currentProject: string): ScopeChoice[] {
  const out: ScopeChoice[] = [];
  if (currentProject) out.push({ label: currentProject, detail: "this folder", scope: { kind: "current" } });
  out.push({ label: "All workspaces", scope: { kind: "all" } });
  for (const name of projectsOf(runs)) {
    if (name === currentProject) continue;
    out.push({ label: name, scope: { kind: "project", name } });
  }
  return out;
}
