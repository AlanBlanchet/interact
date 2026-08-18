import { strict as assert } from "node:assert";
import { test } from "node:test";

import { livenessOf } from "./runStatus.ts";

// Every DETACHED agent flashed "crashed" with a warning icon the moment it finished. `agents
// spawn` returns immediately, so nobody is left waiting to write the exit code — the record still
// says "running" while its process is already gone. Measured live on a teacher and a tester that
// both completed cleanly and reported their answers.

test("a run whose stream ENDED is finished, not crashed", () => {
  assert.equal(livenessOf("running", 999999, false, true), "done");
});

test("a run that stopped with no ending recorded anywhere is a real crash", () => {
  assert.equal(livenessOf("running", 999999, false, false), "crashed");
});

test("a live process is left alone", () => {
  assert.equal(livenessOf("running", 4242, true, false), "running");
});

test("a status the record already settled is never second-guessed", () => {
  for (const settled of ["done", "failed", "stopped", "foreign"] as const) {
    assert.equal(livenessOf(settled, 999999, false, false), settled);
  }
});

test("a run with no pid is not called crashed on that basis", () => {
  // Nothing to probe: claiming a crash from an absent pid invents a failure.
  assert.equal(livenessOf("running", null, false, false), "running");
});
