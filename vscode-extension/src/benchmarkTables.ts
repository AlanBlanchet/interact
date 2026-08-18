/** Live per-benchmark leaderboard tables, preferred over the bundled snapshot.
 *
 *  `benchmarks.json` is baked into the extension at BUILD time, so its scores can never change
 *  once packaged — which is how a months-old model stayed on screen as the best at MMMU. Python
 *  fetches the upstream leaderboards at runtime into `~/.interact/out/benchmark_tables.json`;
 *  this reads that and lets it win, per benchmark, falling back to the snapshot for any the
 *  upstreams could not answer.
 */
import * as fs from "fs";
import * as os from "os";
import * as path from "path";

export interface LiveTable {
  retrieved?: string;
  entries: { model_name: string; score: number }[];
}

export function tablesPath(): string {
  // The same fixed location Python writes, and the one `leaderboard.ts` already reads from —
  // deliberately not following INTERACT_DEBUG_DIR, since two front ends must find one file.
  return path.join(os.homedir(), ".interact", "out", "benchmark_tables.json");
}

/** What Python cached, keyed by benchmark id. Empty when absent — never throws at a panel. */
export function readLiveTables(): Record<string, LiveTable> {
  try {
    const raw = JSON.parse(fs.readFileSync(tablesPath(), "utf8"));
    return (raw?.tables as Record<string, LiveTable>) ?? {};
  } catch {
    return {};
  }
}

/** The bundled file with live tables merged in. Returns a COPY: the bundle is `require`d once and
 *  shared, so mutating it would leak one render's data into every later one. */
export function mergeLiveTables(bundled: any, live: Record<string, LiveTable>): any {
  // An empty live table is not an answer — an upstream can return 200 with zero rows, and
  // letting that win would blank a row that at least had an honest, dated snapshot in it.
  const usable = Object.entries(live).filter(([, t]) => t?.entries?.length);
  if (!usable.length) return bundled;
  const byId = Object.fromEntries(usable);
  return {
    ...bundled,
    benchmarks: (bundled?.benchmarks ?? []).map((b: any) =>
      byId[b.id] && isFresher(byId[b.id].retrieved, b.published?.retrieved)
        ? { ...b, published: { ...b.published, ...byId[b.id] } }
        : b,
    ),
  };
}

/** Whether a fetched table is at least as recent as the one it would replace.
 *
 *  "Live" is not the same as "current": OpenVLM's MMMU board last published in 2025, older than
 *  the packaged snapshot, so taking it merely because it came off the network would have made the
 *  panel worse. The freshest DATED source wins, whichever side it is on.
 */
function isFresher(fetched: string | undefined, bundled: string | undefined): boolean {
  if (!bundled) return true;
  if (!fetched) return false;
  return fetched >= bundled; // ISO dates compare correctly as strings
}

/** Shown ON the row. A retrieved date hidden in a tooltip reads as current, which is the whole
 *  defect: the number looks like today's truth until you hover it. */
export function provenanceLabel(retrieved: string | undefined): string {
  return retrieved ? `as of ${retrieved}` : "date unknown";
}
