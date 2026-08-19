/** How much autonomy a spawned agent is given, as a choice the panel can offer.
 *
 *  Supervising a team is largely this decision, made per member — the researcher reads, the one
 *  refactoring writes, the one you have not watched yet plans and touches nothing. The panel
 *  could spawn agents but never say which; every run got whatever the vendor happened to default
 *  to, and nothing on screen said what that was.
 *
 *  The list is READ from the CLI (`interact agents modes`), never hardcoded here. Two copies of a
 *  vendor's flag values drift, and the copy that drifts is always the one further from the
 *  binary. It is also why that command is tab-separated rather than prose: this parser must not
 *  break when someone rewords a description.
 */

export interface PermissionMode {
  id: string;
  label: string;
  detail: string;
  /** Acts without asking. Offered, but never rendered as an unremarkable option. */
  unrestricted: boolean;
}

/** Parse `interact agents modes`. Anything malformed is dropped rather than shown half-read.
 *
 *  A row we cannot read is likelier to be an error message than a mode, and offering "ERROR: no
 *  such provider" as an autonomy setting is worse than offering one option fewer.
 */
export function parseModes(stdout: string): PermissionMode[] {
  return stdout
    .split("\n")
    .map((line) => line.split("\t"))
    .filter((f) => f.length === 4 && f[0].trim() !== "")
    .map(([id, label, detail, unrestricted]) => ({
      id: id.trim(),
      label: label.trim(),
      detail: detail.trim(),
      unrestricted: unrestricted.trim() === "yes",
    }));
}

export interface ModeChoice {
  label: string;
  description: string;
  detail: string;
  id: string | null;
}

/** The quick-pick items, with the CLI's own default kept as a real choice.
 *
 *  "Whatever your CLI is set to" leads, because it is what happens today and what happens if the
 *  person dismisses the picker — an option list whose first entry silently CHANGES the behaviour
 *  is a trap. `last` floats the previous choice to the top instead, so spawning ten agents the
 *  same way is nine fewer decisions.
 *
 *  The unrestricted mode is marked in its own label rather than by position or colour: a webview
 *  quick pick has no styling to lean on, and this must read as different at a glance.
 */
export function modeChoices(modes: readonly PermissionMode[], last?: string | null): ModeChoice[] {
  const inherit: ModeChoice = {
    label: "Your CLI's default",
    description: "",
    detail: "whatever the agent CLI is already configured to do",
    id: null,
  };
  const items = modes.map((m) => ({
    label: m.unrestricted ? `$(warning) ${m.label}` : m.label,
    description: m.id,
    detail: m.unrestricted ? `${m.detail} — no confirmation, ever` : m.detail,
    id: m.id,
  }));
  const all = [inherit, ...items];
  if (!last) return all;
  const previous = all.filter((c) => c.id === last);
  return previous.length ? [...previous, ...all.filter((c) => c.id !== last)] : all;
}

/** What a run's recorded mode should say in the panel, or null when nobody chose one.
 *
 *  Answers "why did that one stop to ask" / "why did that one just do it" about an agent you are
 *  watching — the question the record could not answer before. An unknown id is shown verbatim
 *  rather than dropped: a run really was started with it, and hiding it would misreport the
 *  autonomy an agent is running under, which is the one thing this field exists to be honest about.
 */
export function describeMode(
  id: string | null | undefined,
  modes: readonly PermissionMode[],
): { label: string; unrestricted: boolean } | null {
  if (!id) return null;
  const known = modes.find((m) => m.id === id);
  if (known) return { label: known.label, unrestricted: known.unrestricted };
  // An id this build does not recognise is shown verbatim — a run really was started with it, and
  // hiding it would misreport the autonomy an agent is running under. Marked UNRESTRICTED though:
  // on the one axis this exists to be honest about, an unknown mode fails CLOSED. A newer CLI's
  // more permissive setting must not render as unremarkable because this build has not heard of it.
  return { label: id, unrestricted: true };
}

/** The modes this machine's CLI offers, asked once.
 *
 *  Three call sites each shelled out for this — the spawn picker, the workspace default, and the
 *  chat panel turning a recorded id into words — with three different error handlings between
 *  them. The answer changes only when the CLI is upgraded, so asking per repaint was pure cost;
 *  worse, the divergence meant only one of them had a timeout.
 *
 *  A FAILURE is not cached. An empty list means "this CLI exposes no verified modes", which is a
 *  real answer that hides the control; caching a transient failure as that answer would hide it
 *  until the window was closed.
 */
let cached: PermissionMode[] | null = null;

export async function knownModes(): Promise<PermissionMode[]> {
  if (cached) return cached;
  // Imported lazily so this module stays loadable by `node --test --experimental-strip-types`,
  // which resolves real specifiers and would demand a ".ts" suffix that tsc then refuses to emit.
  // The pure functions above are what the tests exercise; this path never runs there.
  const { interactCli } = await import("./interactCli");
  const { stdout, error } = await interactCli(["agents", "modes"]);
  if (error) return [];
  cached = parseModes(stdout);
  return cached;
}

/** Forget the cached answer — for a test, or after the CLI is upgraded under a running window. */
export function forgetModes(): void {
  cached = null;
}
