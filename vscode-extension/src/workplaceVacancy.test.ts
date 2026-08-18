/** visual-critic could not exercise this on live data: it needs a storey where EVERY room is
 *  empty, and the registry that day had someone on all three. So the claim "an empty storey stops
 *  paying full height" sat unverified while the surface it belongs to was being judged. A test can
 *  build the state the live registry happened not to contain. */
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { createRequire } from "node:module";

import type { TeamState, Worker, ZoneId } from "./team.ts";

const render = createRequire(import.meta.url)("../out/workplace.js").renderWorkplace as (
  s: TeamState, nonce: string,
) => string;

function worker(zone: ZoneId, id: string): Worker {
  return {
    run_id: id, name: id, zone, status: "running", depth: 0,
    activity: "working", lead: null, agent: null,
  } as Worker;
}

const state = (workers: Worker[]): TeamState =>
  ({ workers, links: [], messages: [], now: 0 }) as unknown as TeamState;

/** Floors are `[library studio lab] [code managers data] [idle entry]`. */
function vacantFloors(html: string): number {
  return [...html.matchAll(/<div class="wp-floor"[^>]*data-vacant="1"/g)].length;
}

test("a storey nobody is on is marked vacant", () => {
  // Everyone downstairs: the top floor (library/studio/lab) is empty.
  const html = render(state([worker("entry", "a"), worker("code", "b")]), "n");
  assert.equal(vacantFloors(html), 1);
});

test("two empty storeys are both marked", () => {
  const html = render(state([worker("entry", "a")]), "n");
  assert.equal(vacantFloors(html), 2, "library/studio/lab and code/managers/data are both empty");
});

test("a storey with a single worker on it pays full height", () => {
  const html = render(state([worker("lab", "a"), worker("data", "b"), worker("entry", "c")]), "n");
  assert.equal(vacantFloors(html), 0);
});

test("a worker OUTSIDE the building does not keep a storey alive", () => {
  // The web is outdoors, deliberately not part of any floor — so a lone researcher out there
  // must not make the building read as occupied.
  const html = render(state([worker("web", "a"), worker("entry", "b")]), "n");
  assert.equal(vacantFloors(html), 2);
});

test("an empty building still renders every storey", () => {
  const html = render(state([]), "n");
  assert.equal([...html.matchAll(/<div class="wp-floor"/g)].length, 3, "it stays a building");
  assert.equal(vacantFloors(html), 3);
});
