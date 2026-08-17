/** The live model catalog, as the panel sees it.
 *
 *  The extension used to read `./models.json` — a file baked into the bundle by `sync-data.js` at
 *  BUILD time. It looked current and wasn't: prices and context windows aged with every release
 *  and nothing said so. This reads the catalog Python refreshes
 *  (`interact.model_catalog`, `~/.interact/out/model_catalog.json`) and, when that is missing or
 *  stale, fetches OpenRouter's public endpoint directly — a plain unauthenticated GET, no key.
 *
 *  The invariant, same as the Python side: the catalog carries its SOURCE and its AGE, and
 *  `isLive` goes false for anything stale. Serving old data offline is fine; serving it as
 *  today's truth is the bug.
 */
import * as fs from "fs";
import * as path from "path";

import { agentsDir } from "./paths";

/** Matches Python's `TTL_SECONDS` — the two write the same cache file, so they must agree on
 *  when it has gone off. */
import {
  type Catalog,
  type ModelInfo,
  TTL_SECONDS,
  ageSeconds,
} from "./catalogFormat";

export * from "./catalogFormat";

const OPENROUTER_URL = "https://openrouter.ai/api/v1/models";

/** The file Python writes. It sits beside the agent registry on the same fixed path, so a process
 *  that never saw `INTERACT_DEBUG_DIR` still finds it. */
export function catalogPath(): string {
  return path.join(path.dirname(agentsDir()), "model_catalog.json");
}

export function readCatalog(): Catalog | null {
  try {
    const raw = JSON.parse(fs.readFileSync(catalogPath(), "utf8"));
    if (!Array.isArray(raw?.models) || raw.models.length === 0) return null;
    return {
      models: raw.models.filter((m: ModelInfo) => m && typeof m.id === "string"),
      source: String(raw.source || "openrouter"),
      fetched_at: Number(raw.fetched_at || 0),
    };
  } catch {
    return null; // absent or truncated — the caller falls back to a fetch
  }
}

function writeCatalog(cat: Catalog): void {
  try {
    fs.mkdirSync(path.dirname(catalogPath()), { recursive: true });
    fs.writeFileSync(catalogPath(), JSON.stringify(cat));
  } catch {
    /* caching is an optimisation, never a failure mode */
  }
}

/** The freshest catalog available, never throwing.
 *
 *  A cache inside its TTL wins (no network on every panel refresh); otherwise fetch; otherwise
 *  serve the stale cache, which `isLive` already marks as stale. Returns null only when there is
 *  genuinely nothing — the caller then says so rather than rendering an empty panel.
 */
export async function loadCatalog(): Promise<Catalog | null> {
  const cached = readCatalog();
  if (cached && ageSeconds(cached) <= TTL_SECONDS) return cached;

  try {
    const res = await fetch(OPENROUTER_URL, { signal: AbortSignal.timeout(6000) });
    if (res.ok) {
      const payload = (await res.json()) as { data?: unknown[] };
      const models: ModelInfo[] = [];
      for (const raw of payload.data ?? []) {
        const m = raw as Record<string, any>;
        if (!m?.id) continue;
        models.push({
          id: String(m.id),
          name: String(m.name ?? m.id),
          context_length: typeof m.context_length === "number" ? m.context_length : null,
          input_cost_per_token: Number(m.pricing?.prompt) || null,
          input_modalities: m.architecture?.input_modalities ?? [],
        });
      }
      if (models.length) {
        const fresh: Catalog = { models, source: "openrouter", fetched_at: Date.now() / 1000 };
        writeCatalog(fresh);
        return fresh;
      }
    }
  } catch {
    /* offline or rate-limited — fall through to whatever we already have */
  }
  return cached;
}
