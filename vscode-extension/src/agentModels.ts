/** Which model an agent runs on, when YOU chose it.
 *
 *  "find a way that we could easily chose what models are ran for what."
 *
 *  An agent's model is declared in the company file (`org.json`) — but that file is GENERATED from
 *  the prompt repo, so a choice written there is erased by the next sync. A preference made in the
 *  editor therefore lives in the agents POLICY (`~/.interact/agents.json`), the one file the spawn
 *  reads: this module edits its `agents` map and nothing else, beside the profiles, toolsets and
 *  provider switches written by hand or by the CLI. One fact, one file — the choice the panel
 *  writes IS the choice the spawn uses, and a rule typed by hand (a `@profile`, a criterion) shows
 *  in the panel exactly as written.
 *
 *  Deliberately a plain readable JSON file: he edits his own configuration by hand, and a file he
 *  cannot read is a file he cannot fix — which is also why a file that will not parse is never
 *  overwritten from here.
 */
import * as fs from "fs";
import * as os from "os";
import * as path from "path";

/** The agents policy — profiles, per-agent model rules, toolsets, provider switches — beside
 *  `config.env` and NEVER under the debug dir: Python's `policy_path()` is anchored the same way,
 *  and `tests/test_paths.py` holds the two together. */
export function agentsPolicyPath(): string {
  return path.join(os.homedir(), ".interact", "agents.json");
}

/** Where v0.38 kept these choices, before the policy existed. Read once, to carry them over. */
export function legacyChoicesPath(): string {
  return path.join(os.homedir(), ".interact", "agent-models.json");
}

/** A model id we are willing to store.
 *
 *  This value becomes an argv `--model`, and a provider-prefixed one also selects an ENDPOINT, so
 *  it is validated on the way IN rather than trusted on the way out: no flags, no whitespace, no
 *  newlines, nothing unbounded.
 */
const MODEL = /^[A-Za-z0-9][A-Za-z0-9._:\/-]{0,95}$/;

/** An agent (or profile) name we are willing to key by — a name, never a path. */
const AGENT = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

/** A rule somebody wrote by hand — a profile, a criterion, an id. SHOWN, never interpreted here:
 *  Python parses it at spawn. One line, bounded, is all the panel asks of it. */
const RULE = /^[^\r\n]{1,200}$/;

type Raw = Record<string, unknown>;

/** The policy as written. `parsable` is false for a file that exists but will not parse — theirs
 *  to fix, never ours to erase — and true for a missing file, which is simply an empty policy. */
function readPolicy(file: string): { raw: Raw; parsable: boolean } {
  try {
    const raw = JSON.parse(fs.readFileSync(file, "utf8")) as unknown;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return { raw: {}, parsable: false };
    return { raw: raw as Raw, parsable: true };
  } catch (err) {
    return { raw: {}, parsable: (err as NodeJS.ErrnoException)?.code === "ENOENT" };
  }
}

function stringMap(value: unknown, valueOk: RegExp): Record<string, string> {
  const out: Record<string, string> = {};
  if (!value || typeof value !== "object" || Array.isArray(value)) return out;
  for (const [key, v] of Object.entries(value as Raw)) {
    if (typeof v === "string" && AGENT.test(key) && valueOk.test(v)) out[key] = v;
  }
  return out;
}

/** Every agent's rule in the policy. A missing or malformed file reads as "no choices" rather than
 *  throwing: a panel that will not render is worse than a preference that does not show. */
export function chosenModels(file: string = agentsPolicyPath()): Record<string, string> {
  return stringMap(readPolicy(file).raw.agents, RULE);
}

/** The profiles the policy defines — a rule written once, worn by many — for the picker to offer. */
export function profilesIn(file: string = agentsPolicyPath()): Record<string, string> {
  return stringMap(readPolicy(file).raw.profiles, RULE);
}

/** The rule chosen for one agent, or null to mean "whatever the company file says". */
export function modelChosenFor(agent: string, file: string = agentsPolicyPath()): string | null {
  return chosenModels(file)[agent] ?? null;
}

/** Record a choice: a model id, or `@profile` naming a profile the policy defines. Returns false —
 *  and writes nothing — for anything it will not vouch for, and for a policy it cannot parse. */
export function chooseModel(agent: string, rule: string, file: string = agentsPolicyPath()): boolean {
  if (!AGENT.test(agent)) return false;
  const isProfile = rule.startsWith("@") && rule.slice(1) in profilesIn(file);
  if (!isProfile && !MODEL.test(rule)) return false;
  return editAgents(file, (agents) => { agents[agent] = rule; });
}

/** Hand an agent back to the company file's default. */
export function clearChoice(agent: string, file: string = agentsPolicyPath()): boolean {
  return editAgents(file, (agents) => { delete agents[agent]; });
}

/** Choices made in v0.38's own file, carried into the policy ONCE — never overriding a rule the
 *  policy already holds (the newer word) — and the old file removed so it is never read again.
 *  Returns how many were carried; 0 when there is nothing to do or the policy cannot take them yet. */
export function adoptLegacyChoices(
  legacy: string = legacyChoicesPath(), file: string = agentsPolicyPath(),
): number {
  if (!fs.existsSync(legacy)) return 0;
  const have = chosenModels(file);
  const carry = Object.entries(stringMap(readPolicy(legacy).raw, MODEL)).filter(([agent]) => !(agent in have));
  const taken = editAgents(file, (agents) => { for (const [agent, model] of carry) agents[agent] = model; });
  if (!taken) return 0;  // an unparsable policy: keep the old file, try again next start
  try { fs.unlinkSync(legacy); } catch { /* already gone, or not ours to remove — either is fine */ }
  return carry.length;
}

/** Edit ONLY the `agents` map, leaving every other key as written — including entries in that map
 *  we would not have written ourselves (a hand-typed rule is theirs, not ours to drop). */
function editAgents(file: string, edit: (agents: Record<string, string>) => void): boolean {
  const { raw, parsable } = readPolicy(file);
  if (!parsable) return false;  // a broken file is theirs to fix, never ours to erase
  const current = raw.agents;
  const agents = (current && typeof current === "object" && !Array.isArray(current))
    ? { ...(current as Record<string, string>) } : {};
  edit(agents);
  const next: Raw = { ...raw, agents };
  if (Object.keys(agents).length === 0) delete next.agents;
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify(next, null, 2) + "\n");
    return true;
  } catch {
    return false;  // a preference that cannot be saved must not break the action that set it
  }
}
