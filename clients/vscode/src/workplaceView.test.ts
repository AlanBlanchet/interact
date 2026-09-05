import { strict as assert } from "node:assert";
import { test } from "node:test";

import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { ZONES } from "./team.ts";

// Loaded from the COMPILED output rather than the source: `workplaceView.ts` imports `./team`
// without an extension (tsc emits, so extension-ful imports are not allowed), which node's
// type-stripping loader cannot resolve. Testing the built artifact is also closer to what ships.
const { plainRoom } = createRequire(import.meta.url)("../out/workplaceView.js");

// The plain room is the fallback when the pixel-art bundle is missing or throws. A code-reviewer
// run on this diff flagged that neither branch was covered, and that a bare catch would degrade
// silently for the life of a session with nothing saying why.

const STATE = {
  at: 1000,
  workers: [
    { run_id: "a", name: "reviewer", agent: "code-reviewer", status: "running" as const,
      zone: "code" as const, activity: "reading registry.py", parent_run_id: null,
      project: "interact", cost_usd: 1, input_tokens: 100, idle_seconds: 1 },
    { run_id: "b", name: "researcher", agent: "researcher", status: "running" as const,
      zone: "web" as const, activity: "searching the web", parent_run_id: "a",
      project: "interact", cost_usd: 0, input_tokens: 10, idle_seconds: 0 },
  ],
};

test("every zone gets a room, so nobody can be placed nowhere", () => {
  const html = plainRoom(STATE, "n1");
  for (const zone of ZONES) assert.ok(html.includes(zone.label), `no room for ${zone.label}`);
});

test("a worker stands in its own zone", () => {
  const html = plainRoom(STATE, "n1");
  const code = html.slice(html.indexOf("Code"), html.indexOf("Data"));
  assert.match(code, /reviewer/);
});

test("a sub-agent is drawn inside its parent, not loose in the room", () => {
  const html = plainRoom(STATE, "n1");
  const parent = html.indexOf("reviewer");
  assert.ok(html.indexOf("researcher") > parent, "the report follows the lead it belongs to");
});

test("every worker carries the run id the click-through needs", () => {
  const html = plainRoom(STATE, "n1");
  assert.match(html, /data-run-id="a"/);
  assert.match(html, /data-run-id="b"/);
});

test("an agent's name and activity are escaped — both are agent output", () => {
  const html = plainRoom(
    { at: 1, workers: [{ ...STATE.workers[0], name: "<img src=x>", activity: "</div><script>" }] },
    "n1",
  );
  assert.ok(!html.includes("<img src=x"));
  assert.ok(!html.includes("<script>"));
});

test("an empty team renders a building, not a blank page", () => {
  const html = plainRoom({ at: 1, workers: [] }, "n1");
  assert.match(html, /Entry/);
  assert.match(html, /<html/);
});

// --- the document must stop being rebuilt ---
//
// Assigning `webview.html` destroys the document: every sprite becomes a new element and every
// running animation dies. That is WHY a worker teleported between rooms instead of walking there —
// the walk was a one-shot replay reconstructed from persisted state on the next load, not motion.
// The panel builds the shell once and then pushes scenes into it.

test("the scene can be rendered on its own, for pushing into a live document", () => {
  // Compiled output, for the same reason as plainRoom above.
  const { renderScene } = createRequire(import.meta.url)("../out/workplaceView.js");
  const html = renderScene({ workers: [], links: [], zones: [] });

  if (html === null) return; // no bundle in this checkout; the panel falls back to rebuilding
  assert.ok(!/<html|<body|<script/i.test(html), "a fragment, not a document");
});

test("a narrow team panel keeps the world primary and makes the roster optional", () => {
  const { renderWorkplace } = createRequire(import.meta.url)("../out/workplaceView.js");
  const html = renderWorkplace({ workers: [], links: [], zones: [] }, "n1", undefined, {
    style: "", body: "<p>Roster</p>", script: "",
  });
  assert.match(html, /class="wp-roster-toggle"[^>]*aria-expanded="false"/);
  assert.match(html, /@container \(max-width: 560px\)[\s\S]*\.wp-list \{ display: none/);
  assert.match(html, /roster-open[\s\S]*\.wp-list \{ display: block/);
});

test("rendered narrow workplaces leave usable map space and contain their roster overlay", () => {
  const chrome = process.env.CHROME_BIN ?? "/usr/bin/google-chrome";
  assert.ok(fs.existsSync(chrome));
  const { renderWorkplace } = createRequire(import.meta.url)("../out/workplaceView.js");
  for (const width of [207, 299, 458]) {
    const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "out", "tests",
      `workplace-${width}-contract`);
    const page = path.join(root, "page.html");
    const profile = path.join(root, `profile-${process.pid}-${Date.now()}`);
    fs.mkdirSync(root, { recursive: true });
    const html = renderWorkplace({ workers: STATE.workers, links: [], zones: [] }, "n1", undefined, {
      style: "", body: "<p>Roster</p>", script: "",
    }).replace("</body>", `<script nonce="n1">
document.documentElement.style.width="${width}px"; document.body.style.width="${width}px";
document.querySelector('.wp-split').style.width="${width}px";
const room=document.querySelector('.wp-room'); const roster=document.querySelector('.wp-list');
const toggle=document.querySelector('.wp-roster-toggle');
const usable=room?.getBoundingClientRect().width>0;
const noOverflow=document.body.scrollWidth<=${width};
const contained=!roster || roster.getBoundingClientRect().right<=${width};
const controlled=toggle && getComputedStyle(toggle).display!=="none" &&
  toggle.getAttribute('aria-controls')==='wp-roster';
const toggleRect=toggle?.getBoundingClientRect();
const hudItems=[...document.querySelectorAll('.wp-hud > *')]
  .filter((item)=>getComputedStyle(item).display!=="none");
const overlapsHud=!!toggleRect && hudItems.some((item)=>{
  const rect=item.getBoundingClientRect();
  return toggleRect.left<rect.right && toggleRect.right>rect.left &&
    toggleRect.top<rect.bottom && toggleRect.bottom>rect.top;
});
toggle?.click();
const openRect=roster?.getBoundingClientRect();
const openContained=!!openRect && openRect.width>0 && openRect.left>=0 &&
  openRect.right<=${width} && openRect.top>=toggleRect.bottom;
const expanded=toggle?.getAttribute('aria-expanded')==='true';
const openNoOverflow=document.body.scrollWidth<=${width};
document.body.dataset.narrowContract=usable && noOverflow && (contained || controlled) && !overlapsHud && openContained && expanded && openNoOverflow ?
  'ok-map-'+room.getBoundingClientRect().width+'-roster-'+openRect.width+'-overflow-'+document.body.scrollWidth :
  'failed-map-'+(room?.getBoundingClientRect().width ?? -1)+'-roster-'+(openRect?.width ?? -1)+'-overflow-'+document.documentElement.scrollWidth+'-hud-overlap-'+overlapsHud+'-expanded-'+expanded;
</script></body>`);
    fs.writeFileSync(page, html);
    const rendered = execFileSync(chrome, ["--headless=new", "--no-sandbox", "--disable-gpu",
      "--window-size=800,800", `--user-data-dir=${profile}`, "--dump-dom", `file://${page}`],
    { encoding: "utf8" });
    assert.match(rendered, new RegExp(`data-narrow-contract="ok-map-${width}-roster-${width}-overflow-${width}`),
      `${width}px workplace must keep its map, separate its controls, and contain the open roster`);
  }
});
