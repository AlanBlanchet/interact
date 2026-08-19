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

type View = { id: string; name?: string; initialSize?: number; visibility?: string };

const views: View[] = JSON.parse(
  readFileSync(join(import.meta.dirname, "..", "package.json"), "utf8"),
).contributes.views.interactAgentsSecondary;

const byId = (id: string): View => {
  const v = views.find((x) => x.id === id);
  assert.ok(v, `${id} is gone from the panel entirely`);
  return v;
};

test("the conversation gets more of the panel than anything else", () => {
  const chat = byId("interactAgents.chat");
  for (const other of views.filter((v) => v.id !== "interactAgents.chat")) {
    assert.ok(
      (chat.initialSize ?? 0) > (other.initialSize ?? 0),
      `chat (${chat.initialSize}) must outweigh ${other.id} (${other.initialSize}) — ` +
        `"the chat page shouldn't be small"`,
    );
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
