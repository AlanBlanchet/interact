/** The rail as it actually renders.
 *
 *  The whole point of moving off a `TreeView` is that chrome can be VISIBLE AT REST, so these
 *  tests are mostly about what exists in the document without anyone hovering, focusing, or
 *  selecting an agent first. Each one corresponds to a measured defect in the surface it replaces.
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { buildRail } from "./rail.ts";
import { railHtml, headerLine } from "./railHtml.ts";
import { voiceOf } from "./statusLanguage.ts";
import { conversationTitle, roleOf } from "./roster.ts";
import { actionsFor } from "./agentActions.ts";

const run = (over: Record<string, unknown> = {}) => ({
  run_id: "r1", name: "visual-critic", provider: "claude", status: "running", started_at: 100,
  ...over,
}) as never;

const html = (runs: unknown[] = [run()], scope = "interact") =>
  railHtml(buildRail(runs as never[], scope, () => 0), "N0NCE", voiceOf,
    (r) => conversationTitle(r as never), (r) => ({ id: roleOf(r as never).id, label: roleOf(r as never).id }), (r) => actionsFor(r as never));

test("every destination is in the document at rest, with its word", () => {
  // The defect this replaces: VS Code renders a view's title actions only while the pointer is in
  // the header, and clips the overflow with no "…" menu. At rest the panel had NO buttons.
  const doc = html();
  // Two destinations now, not four: the dashboard and the sequence view are their own surfaces and
  // live in the palette. What a panel this narrow must still offer at rest is the world and a way
  // to start someone — see CHIPS.
  for (const label of ["Team", "Company"]) {
    assert.ok(doc.includes(`>${label}<`), `"${label}" is not present without hovering`);
  }
});

test("the scope is stated on the surface, not hidden in a dialog", () => {
  assert.ok(html([run()], "sheets").includes("sheets"),
    "whose agents these are must be readable without opening anything");
});

test("an empty team still renders every destination", () => {
  // The old empty state offered nothing at all: no agents meant no composer, so no way to reach
  // the team either. Empty is exactly when you most need the buttons.
  const doc = html([]);
  assert.ok(doc.includes(">Team<"));
  assert.ok(doc.includes("nobody working yet"));
});

test("a run that needs you is marked, not merely listed", () => {
  const doc = html([run({ run_id: "bad", name: "perf-critic", status: "crashed" })]);
  assert.ok(doc.includes("perf-critic"));
  assert.ok(doc.includes("stopped with an error"));
  assert.match(doc, /data-attention="error"/);
});

test("agent output is escaped — it is untrusted text in a webview", () => {
  const doc = html([run({ name: "<img src=x onerror=alert(1)>" })]);
  assert.ok(!doc.includes("<img src=x"), "an agent's name reached the DOM as markup");
  assert.ok(doc.includes("&lt;img"));
});

test("the script carries the nonce the CSP demands", () => {
  const doc = html();
  assert.match(doc, /<script nonce="N0NCE"/);
  assert.match(doc, /Content-Security-Policy/);
  // A script without the nonce is silently dropped, which is how a whole panel's behaviour
  // vanished before with nothing on screen to say so.
  assert.ok(!/<script(?![^>]*nonce)/.test(doc), "a script would be blocked by the CSP");
});

test("it themes off body, not :root", () => {
  // VS Code injects its --vscode-* variables onto <body>. A :root block never resolves and
  // silently falls back — the light theme rendered as unstyled once for exactly this reason.
  const doc = html();
  assert.ok(!/:root\s*\{[^}]*--vscode-/.test(doc),
    "a :root block will not see the host's theme variables");
});

test("each row can be actuated, and says which run it is", () => {
  const doc = html([run({ run_id: "abc123" })]);
  assert.match(doc, /data-run="abc123"/);
});

test("an empty team reads as a sentence, not as zeroes", () => {
  assert.equal(headerLine(buildRail([], "x", () => 0).header), "nobody working yet");
});

test("the header line leads with what needs you", () => {
  const built = buildRail([run({ run_id: "a" }), run({ run_id: "b", status: "failed" })] as never[], "x", () => 0);
  assert.match(headerLine(built.header), /^1 needs you/);
});

test("dim text never uses the raw description token", () => {
  // VS Code ships --vscode-descriptionForeground at 4.28:1 in its own Light theme — under AA
  // before any panel touches it. themeTokens.ts exists for exactly this, and a second copy of the
  // workaround is how the first one ended up covering two of seven sites.
  const doc = html();
  assert.ok(!/color:\s*var\(--vscode-descriptionForeground\)/.test(doc),
    "raw descriptionForeground is sub-AA in light; pull it toward the foreground");
});

test("the orchestrator is marked on the surface, not just in the data", () => {
  const doc = html([
    run({ run_id: "boss", name: "main", started_at: 100 }),
    run({ run_id: "kid", name: "tester", parent_run_id: "boss", started_at: 200 }),
  ]);
  assert.match(doc, /data-brain="1"/, "nothing tells you which one you steer from");
  assert.ok(doc.includes(">brain<"));
});

test("a report is marked as one, so the roster reads as a company", () => {
  const doc = html([
    run({ run_id: "boss", name: "main", started_at: 100 }),
    run({ run_id: "kid", name: "tester", parent_run_id: "boss", started_at: 200 }),
  ]);
  assert.match(doc, /data-report="1"/, "a sub-agent floats loose beside its lead");
});

test("each row carries the actions that would actually work on it", () => {
  // "They should have actions for these. And we should show they actions in a ergonomic way."
  // Built, tested, and consumed by nothing until now — the orphan pattern that has landed eight
  // times in this repo.
  const doc = html([run({ run_id: "live", name: "artist", status: "running" })]);
  assert.match(doc, /data-action="stop"/, "a running agent can be stopped");
  assert.match(doc, /data-action="message"/);
  assert.match(doc, /data-action="transcript"/);
});

test("a finished agent offers no stop, so no control on screen is dead", () => {
  const doc = html([run({ run_id: "over", name: "librarian", status: "done" })]);
  assert.ok(!doc.includes('data-action="stop"'));
  assert.match(doc, /data-action="transcript"/, "its transcript is always readable");
});

test("every action carries a title, since a bare glyph is a guess", () => {
  const doc = html([run({ run_id: "live", status: "running" })]);
  for (const m of doc.matchAll(/<button class="act"[^>]*>/g)) {
    assert.match(m[0], /title="/, `an action button with no title: ${m[0]}`);
  }
});

test("the rail and the world stay quiet about the same states", () => {
  /* The coherence rule, updated with the design: the world dropped its DONE stamp — a finished
     agent SITS at rest, and captioning the obvious is noise ("Agents keep saying 'finished'.
     Instead, we should not have that"). So the shared vocabulary carries QUIET, and the rail obeys
     the same bit: a finished row is a green ✓ and nothing else, while ERROR still says its word on
     both surfaces, because that is a state that needs him. */
  const doneRow = html([run({ status: "completed" })]);
  assert.ok(!doneRow.includes(">DONE<"), "a finished row must not caption itself");
  assert.ok(doneRow.includes(voiceOf("finished").mark), "the mark carries the state alone");

  const errRow = html([run({ status: "failed" })]);
  const err = voiceOf("error");
  assert.ok(errRow.includes(`>${err.word}<`), "an error must still SAY so, in the shared word");
});


test("each state carries its own accent, so colour still separates them", () => {
  const finished = html([run({ status: "completed" })]);
  const failed = html([run({ status: "failed" })]);
  assert.ok(finished.includes(`var(${voiceOf("finished").accent})`));
  assert.ok(failed.includes(`var(${voiceOf("error").accent})`));
  assert.notEqual(voiceOf("finished").accent, voiceOf("error").accent);
});
