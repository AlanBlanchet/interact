/** How the secondary-sidebar panel divides itself at REST.
 *
 *  His ask, verbatim: "The chat page shouldn't be small." An independent visual-critic round
 *  measured it at ~300px on cold entry — a third of a narrow sidebar, because three views stack
 *  in one container and the middle one was a second tree listing the same roster the rail above
 *  it already shows.
 *
 *  Layout that only exists in a manifest is exactly what regresses silently: nothing imports it,
 *  no compiler checks it, and the symptom (a cramped conversation) looks like a styling opinion
 *  rather than a dropped decision. This pins it.
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

type View = { id: string; name?: string; initialSize?: number; visibility?: string; when?: string };

const views: View[] = JSON.parse(
  readFileSync(join(import.meta.dirname, "..", "package.json"), "utf8"),
).contributes.views.interactAgentsSecondary;

const byId = (id: string): View => {
  const v = views.find((x) => x.id === id);
  assert.ok(v, `${id} is gone from the panel entirely`);
  return v;
};

test("the roster and the conversation are never on screen together", () => {
  /* His complaint: "the actual conversation chat panel is not taking the whole space on the right
     side of my vscode. Instead, i'm having to close the menus for team and agent."

     Weighting the views was not enough — an EMPTY chat still held weight 5 of the column, leaving
     the roster ~230px, six rows across three scroll-screens. The two are states of one panel, not
     neighbours, so their `when` clauses are complements: each gets the whole column when it is the
     one you are using, and nobody collapses anything by hand. */
  const chat = byId("interactAgents.chat");
  const rail = byId("interactAgents.rail");
  const board = byId("interactAgents.board");
  assert.equal(chat.when, "interact.inConversation");
  for (const roster of [rail, board]) {
    assert.equal(roster.when, "!interact.inConversation",
      `${roster.id} must step aside for exactly the state the chat appears in`);
  }
});

test("the duplicate roster tree does not take height at rest", () => {
  assert.equal(
    byId("interactAgents.board").visibility,
    "collapsed",
    "the rail already lists every agent; a second expanded tree of the same people is what " +
      "squeezed the conversation",
  );
});

test("every view still declares a size, so none silently collapses to nothing", () => {
  for (const v of views) {
    assert.ok(
      typeof v.initialSize === "number" && v.initialSize > 0,
      `${v.id} has no initialSize — its height then depends on declaration order`,
    );
  }
});

test("a view that VS Code can dispose is never written to afterwards", () => {
  /* The `when` clause that gives the conversation the whole column also makes VS Code DISPOSE the
     chat view every time the clause goes false. A kept reference to a disposed webview throws on
     the next write — which blanked the entire sidebar on the SECOND conversation a user opened,
     with no visible way back.

     Not unit-testable: chatView.ts imports `vscode`, which the strip-types loader cannot resolve,
     and that is exactly why the defect reached a live host. So the contract is pinned at the
     source: forget the view on disposal, and never paint one that is not visible. `railView.ts`
     has always done both; this file only became disposable when it gained a `when`. */
  const chat = readFileSync(join(import.meta.dirname, "chatView.ts"), "utf8");
  assert.match(chat, /onDidDispose\(/,
    "chatView must forget a disposed view, or the next show() writes to a dead webview");
  assert.match(chat, /this\.view\s*=\s*undefined/,
    "onDidDispose must actually clear the reference, not merely log");
  assert.match(chat, /if \(!this\.view\?\.visible\) return;/,
    "render() must refuse a hidden view — writing to one VS Code tore down throws, it does not no-op");

  /* And the invariant that makes it necessary: a `when`-gated view is a disposable view. */
  const views = JSON.parse(
    readFileSync(join(import.meta.dirname, "..", "package.json"), "utf8"),
  ).contributes.views.interactAgentsSecondary as View[];
  const gated = views.filter((v) => v.when);
  assert.ok(gated.length >= 1, "if nothing is gated any more, this guard has lost its subject");
});
