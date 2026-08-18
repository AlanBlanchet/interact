import { strict as assert } from "node:assert";
import { test } from "node:test";

import { mergeLiveTables, provenanceLabel } from "./benchmarkTables.ts";

// The extension bundles benchmarks.json at BUILD time, so its scores could never change once
// packaged — a months-old model stayed on screen as best at MMMU, with its retrieved date buried
// in a tooltip nobody hovers. Python now caches live tables; this is the consumer that reads them.

const baked = {
  benchmarks: [
    { id: "mmmu", name: "MMMU", published: { retrieved: "2026-06-07", entries: [{ model_name: "OldModel", score: 0.94 }] } },
    { id: "screenspot", name: "ScreenSpot", published: { retrieved: "2026-05-21", entries: [] } },
  ],
};

test("a live table replaces the baked one for that benchmark", () => {
  const merged = mergeLiveTables(baked, {
    mmmu: { retrieved: "2026-08-18", entries: [{ model_name: "NewModel", score: 0.97 }] },
  });
  assert.equal(merged.benchmarks[0].published.entries[0].model_name, "NewModel");
});

test("a benchmark with no live table keeps its baked snapshot", () => {
  const merged = mergeLiveTables(baked, { mmmu: { retrieved: "x", entries: [] } });
  assert.equal(merged.benchmarks[1].published.retrieved, "2026-05-21");
});

test("no live data at all leaves everything as it was", () => {
  assert.deepEqual(mergeLiveTables(baked, {}), baked);
});

test("the baked file is not mutated — a stale render must not poison the next one", () => {
  mergeLiveTables(baked, { mmmu: { retrieved: "2026-08-18", entries: [{ model_name: "X", score: 1 }] } });
  assert.equal(baked.benchmarks[0].published.entries[0].model_name, "OldModel");
});

test("provenance is VISIBLE text, not a tooltip — a hidden date reads as current", () => {
  assert.match(provenanceLabel("2026-06-07"), /2026-06-07/);
});

test("a table with no date says so rather than looking authoritative", () => {
  assert.match(provenanceLabel(undefined), /unknown|undated/i);
});

test("an EMPTY live table never replaces a populated snapshot", () => {
  // Observed live: OpenVLM answered 200 with zero rows for MMMU. Letting that win would blank
  // the panel — trading stale data for no data.
  const merged = mergeLiveTables(baked, { mmmu: { retrieved: "2026-08-18", entries: [] } });
  assert.equal(merged.benchmarks[0].published.entries[0].model_name, "OldModel");
  assert.equal(merged.benchmarks[0].published.retrieved, "2026-06-07",
    "and it keeps the OLD date, so the row still admits how old it is");
});
