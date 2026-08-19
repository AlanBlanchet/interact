/** The company: who exists, which department they sit in, and where they can actually run.
 *
 *  Written by the prompt repo (`paradigms.yaml` -> `org.json`, symlinked to `~/.claude/org.json`)
 *  and read here. Two things it carries that a directory listing of agent files cannot:
 *
 *  - a HIERARCHY — departments, reporting lines, who pairs with whom — so the panel can show an
 *    org rather than a bag of names;
 *  - PROVIDER availability, and whether each provider is actually wired (`env`) or only designed
 *    for. "Shared between providers... not all in the env" is a real distinction: an agent can be
 *    part of the company on paper and have nowhere to run today.
 *
 *  Absent for most installs — interact is used without any prompt repo — so every path here
 *  degrades to "no company known" rather than failing.
 */
import * as fs from "fs";
import * as os from "os";
import * as path from "path";

export interface OrgProvider {
  label: string;
  /** True when a consumer sync target exists NOW. False = shared design, nowhere to run yet. */
  env: boolean;
}

export interface OrgDepartment {
  id: string;
  /** The workplace zone this department belongs in, so the building and the roster agree. */
  room?: string | null;
  mission?: string | null;
  reports_to?: string | null;
  pipeline?: string[] | null;
}

export interface OrgAgent {
  name: string;
  title?: string | null;
  department?: string | null;
  seniority?: string | null;
  role?: string | null;
  reports_to?: string | null;
  pairs_with?: string | null;
  providers?: string[];
  model?: string | null;
  /** Path to the agent's own definition, relative to the prompt repo. */
  def?: string | null;
  description?: string | null;
}

export interface Org {
  coordinator: { id: string; title?: string | null };
  providers: Record<string, OrgProvider>;
  departments: OrgDepartment[];
  agents: OrgAgent[];
}

/** Where the prompt repo publishes the company. */
export function orgPath(): string {
  return path.join(os.homedir(), ".claude", "org.json");
}

export function readOrg(file: string = orgPath()): Org | null {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8")) as Partial<Org>;
    if (!parsed || !Array.isArray(parsed.agents)) return null;
    return {
      coordinator: parsed.coordinator ?? { id: "main" },
      providers: parsed.providers ?? {},
      departments: parsed.departments ?? [],
      agents: parsed.agents,
    };
  } catch {
    // No prompt repo, or a half-written file: the panel shows agents without an org, not an error.
    return null;
  }
}

export interface ResolvedProvider {
  id: string;
  label: string;
  env: boolean;
}

/** An agent with its providers already resolved, so a view never looks one up again. */
export interface OrgSeat extends Omit<OrgAgent, "providers"> {
  providers: ResolvedProvider[];
}

export interface OrgNode extends OrgDepartment {
  agents: OrgSeat[];
}

/** Departments in declared order, each with its people; anyone unfiled gets their own desk.
 *
 *  Unfiled people are KEPT. A roster that silently omits someone because a yaml row is missing is
 *  worse than one with an obvious "unassigned" bucket — the omission is invisible, the bucket is
 *  a prompt to go and file them.
 */
export function orgTree(org: Org): OrgNode[] {
  const resolve = (a: OrgAgent): OrgSeat => ({
    ...a,
    providers: (a.providers ?? []).map((id) => ({
      id,
      label: org.providers[id]?.label ?? id,
      env: org.providers[id]?.env ?? false,
    })),
  });

  const known = new Set(org.departments.map((d) => d.id));
  const nodes: OrgNode[] = org.departments.map((d) => ({
    ...d,
    agents: org.agents.filter((a) => a.department === d.id).map(resolve),
  }));
  const unfiled = org.agents.filter((a) => !a.department || !known.has(a.department));
  if (unfiled.length) {
    nodes.push({
      id: "unassigned",
      room: null,
      mission: "not filed under any department",
      reports_to: null,
      agents: unfiled.map(resolve),
    });
  }
  return nodes;
}
