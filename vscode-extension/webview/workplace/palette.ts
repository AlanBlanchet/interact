/** Who looks like whom.
 *
 *  Two jobs, and they pull in opposite directions. A worker must be an INDIVIDUAL — you should be
 *  able to say "the one with the dark green hair is back" without reading a label. And a pod must
 *  be a TEAM — a report standing three rooms away still has to read as belonging to its lead.
 *
 *  So the two axes are split: the shirt is the POD's colour (assigned from the lead's id and worn
 *  by everyone under them, which is what makes the relationship survive the distance), while skin,
 *  hair and trousers are the WORKER's own, drawn from their run id. Same lead, same shirt;
 *  same person, same face, every refresh — nothing here is random.
 */

/** FNV-1a. A hash, not a random: the point is that a run keeps its face between snapshots. */
export function hash(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

function pick<T>(list: readonly T[], seed: number, salt: number): T {
  return list[(seed >>> salt) % list.length];
}

/** Skin and hair stay literal rather than following the theme. A person tinted by the editor
 *  background stops being a person; these tones are chosen to hold against a light AND a dark
 *  wall, which is what the derived ink rim is for. */
const SKIN = ["#f0c39b", "#e0a877", "#c68642", "#a8663c", "#7d4b2a", "#f7d9bd"] as const;
const HAIR = ["#2b2118", "#553311", "#8a5a2b", "#c9a227", "#7a2f2f", "#3b3f4a", "#b8b0a6"] as const;
const TROUSER = ["#3b4256", "#4a3f52", "#2f4a42", "#54463a", "#3f3f3f"] as const;
const BOOT = ["#2a2420", "#3a2f28", "#221d2b"] as const;

/** Seven hues, from the theme's own chart palette (plus two mixed from it) so a light theme does
 *  not get neon. None of them is RED: red already means "stuck" everywhere else on this surface,
 *  and a team whose platform happened to be red would read as a team on fire. */
export const HUES = 7;

/** Colours for every pod on screen at once, guaranteed DISTINCT.
 *
 *  A pure `hash % HUES` was the obvious version and it was wrong: with five leads and five hues a
 *  collision is more likely than not, and a collision does not merely look untidy — the pod colour
 *  is the ONLY thing tying a report standing three rooms away back to its lead, so two teams
 *  sharing a hue silently merges them.
 *
 *  So the hash picks a PREFERENCE and the assignment resolves the clashes: leads are walked in a
 *  stable order, each takes its preferred hue, and a lead whose preference is taken steps to the
 *  next free one. Distinct while there are at most seven leads, and — the reason for preferring a
 *  hash to a plain index — a lead keeps its colour when somebody else joins or leaves.
 */
export function assignAccents(leadRunIds: readonly string[]): Map<string, string> {
  const taken = new Set<number>();
  const out = new Map<string, string>();
  for (const id of [...leadRunIds].sort()) {
    let hue = hash(id) % HUES;
    for (let step = 0; step < HUES && taken.has(hue); step++) hue = (hue + 1) % HUES;
    taken.add(hue);
    out.set(id, `var(--wp-h${hue + 1})`);
  }
  return out;
}

/** The four properties that make this worker this worker. The shirt is deliberately absent — it
 *  comes from the pod, through the cascade. */
export function faceOf(runId: string): string {
  const h = hash(runId);
  return (
    `--c-skin:${pick(SKIN, h, 0)};` +
    `--c-hair:${pick(HAIR, h, 5)};` +
    `--c-trouser:${pick(TROUSER, h, 11)};` +
    `--c-boot:${pick(BOOT, h, 17)}`
  );
}

/** How stopped they are, 0 to 1 — the number the whole fade/slump/dust treatment hangs off.
 *  Ten minutes is the ceiling because past it the difference stops mattering: it is not "how
 *  long", it is "this one is not coming back on its own". */
export function idleAmount(seconds: number): number {
  const t = Math.max(0, seconds) / 600;
  return Math.round(Math.min(1, t) * 100) / 100;
}

/** "4m", "2h" — said the way a person waiting would say it. */
export function shortDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h`;
}
