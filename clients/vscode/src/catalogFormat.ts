/** Pure decisions about the model catalog — no imports, so they are unit-testable.
 *
 *  Same discipline as `agentsFormat.ts` / `paths.ts`. These are the judgements that go quietly
 *  wrong: whether data is fresh enough to present as current, and which models are worth showing
 *  in a tool that drives UIs by looking at them.
 */
export const TTL_SECONDS = 12 * 60 * 60;

export interface ModelInfo {
  id: string;
  name: string;
  context_length: number | null;
  input_cost_per_token: number | null;
  input_modalities: string[];
}

export interface Catalog {
  models: ModelInfo[];
  source: string; // "openrouter" | "litellm" | "bundled"
  fetched_at: number; // epoch SECONDS, matching Python
}

export function ageSeconds(cat: Catalog): number {
  return Math.max(0, Date.now() / 1000 - (cat.fetched_at || 0));
}

/** True only for network data still inside its TTL. Anything else is shown with its age instead
 *  of being passed off as current. */
export function isLive(cat: Catalog): boolean {
  return cat.source === "openrouter" && ageSeconds(cat) <= TTL_SECONDS;
}

export function describeAge(seconds: number): string {
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

/** The models worth showing first. interact drives UIs by looking at them, so a model that cannot
 *  take an image is not a candidate however cheap it is; among those that can, prefer the larger
 *  context. */
export function pickHighlights(cat: Catalog, limit = 6): ModelInfo[] {
  const seeing = cat.models.filter((m) => (m.input_modalities || []).includes("image"));
  return [...seeing]
    .sort((a, b) => (b.context_length ?? 0) - (a.context_length ?? 0))
    .slice(0, limit);
}

