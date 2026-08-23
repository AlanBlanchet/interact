/** Which model an agent runs on, when YOU chose it.
 *
 *  "find a way that we could easily chose what models are ran for what."
 *
 *  An agent's model is declared in the company file (`org.json`) — but that file is GENERATED from
 *  the prompt repo, so a choice written there is erased by the next sync. A preference made in the
 *  editor therefore lives beside interact's own state, where no generator owns it, and the company
 *  file stays the DEFAULT rather than the only answer.
 *
 *  Deliberately a plain readable JSON map: he edits his own configuration by hand, and a file he
 *  cannot read is a file he cannot fix.
 */
import * as fs from "fs";
import * as os from "os";
import * as path from "path";

/** Where the choices live: beside the agent registry, outside the repo, outside the prompt repo. */
export function agentModelsPath(): string {
  return path.join(os.homedir(), ".interact", "agent-models.json");
}

/** A model id we are willing to store.
 *
 *  This value becomes an argv `--model`, and a provider-prefixed one also selects an ENDPOINT, so
 *  it is validated on the way IN rather than trusted on the way out: no flags, no whitespace, no
 *  newlines, nothing unbounded. Mirrors the shape `profiles.py` accepts on the Python side.
 */
const MODEL = /^[A-Za-z0-9][A-Za-z0-9._:\/-]{0,95}$/;

/** An agent name we are willing to key by — a name, never a path. */
const AGENT = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

/** Every choice made so far. A missing or malformed file reads as "no choices" rather than
 *  throwing: losing a preference is survivable, a panel that will not render is not. */
export function chosenModels(file: string = agentModelsPath()): Record<string, string> {
  try {
    const raw = JSON.parse(fs.readFileSync(file, "utf8")) as unknown;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
    const out: Record<string, string> = {};
    for (const [agent, model] of Object.entries(raw as Record<string, unknown>)) {
      if (typeof model === "string" && AGENT.test(agent) && MODEL.test(model)) out[agent] = model;
    }
    return out;
  } catch {
    return {};
  }
}

/** The model chosen for one agent, or null to mean "whatever the company file says". */
export function modelChosenFor(agent: string, file: string = agentModelsPath()): string | null {
  return chosenModels(file)[agent] ?? null;
}

/** Record a choice. Returns false — and writes nothing — for anything it will not vouch for. */
export function chooseModel(agent: string, model: string, file: string = agentModelsPath()): boolean {
  if (!AGENT.test(agent) || !MODEL.test(model)) return false;
  return write({ ...chosenModels(file), [agent]: model }, file);
}

/** Hand an agent back to the company file's default. */
export function clearChoice(agent: string, file: string = agentModelsPath()): boolean {
  const all = chosenModels(file);
  delete all[agent];
  return write(all, file);
}

function write(all: Record<string, string>, file: string): boolean {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify(all, null, 2) + "\n");
    return true;
  } catch {
    return false;  // a preference that cannot be saved must not break the action that set it
  }
}
