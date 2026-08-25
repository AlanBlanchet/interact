/** The ART TABLE: every drawing in the workplace laid out flat, at three magnifications, so the
 *  sprites can be judged as SPRITES — against the craft rules small pixel art actually follows —
 *  before they are judged in a scene.
 *
 *  Three rounds of "the sprites are bad" were argued about on product screenshots where the camera,
 *  the light layer and the chrome all contaminate the read. This page is the isolation instrument:
 *  no camera, no light, no nameplates — the raw art on the two grounds it must hold against
 *  (room floor and lawn), with every FRAME of every animation side by side, because a frame pair
 *  that only ever alternates can hide a bad frame for a whole review round.
 *
 *      npx esbuild webview/workplace/dev/sprites.ts --bundle --outfile=/tmp/sprites.js \
 *        --format=cjs --platform=node --target=es2022
 *      node /tmp/sprites.js <outdir>       # writes sprites-dark.html / sprites-light.html
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import {
  BANG,
  POSES,
  PROP_PIECES,
  RING,
  SKIN_PAL,
  VISITOR_PAL,
  WAVE_A,
  WAVE_B,
  WAVE_PAL,
} from "../art";
import { draw, drawFrames } from "../pixels";
import { STYLE } from "../style";
import { TILES } from "../tiles";
import type { Grid } from "../pixels";
import { faceOf } from "../palette";

const DARK = `
--vscode-editor-background:#1f1f1f;--vscode-editor-foreground:#cccccc;--vscode-foreground:#cccccc;
--vscode-descriptionForeground:#9d9d9d;--vscode-widget-border:#3c3c3c;--vscode-focusBorder:#0078d4;
--vscode-charts-blue:#4daafc;--vscode-charts-purple:#b180d7;--vscode-charts-yellow:#d7ba7d;
--vscode-charts-green:#89d185;--vscode-charts-orange:#d18616;--vscode-charts-red:#f14c4c;
--vscode-errorForeground:#f14c4c;`;
const LIGHT = `
--vscode-editor-background:#ffffff;--vscode-editor-foreground:#3b3b3b;--vscode-foreground:#3b3b3b;
--vscode-descriptionForeground:#767676;--vscode-widget-border:#d4d4d4;--vscode-focusBorder:#0090f1;
--vscode-charts-blue:#1a85ff;--vscode-charts-purple:#652d90;--vscode-charts-yellow:#b89500;
--vscode-charts-green:#388a34;--vscode-charts-orange:#d18616;--vscode-charts-red:#e51400;
--vscode-errorForeground:#e51400;`;

/** Four sample people (the palette hashes of real-looking ids) and one pod hue each, so the ramp
 *  system is seen over several skin/hair/shirt combinations rather than the one it was tuned on. */
const PEOPLE = ["run-a", "run-h", "run-l", "run-o"];
const HUE = ["var(--wp-h1)", "var(--wp-h2)", "var(--wp-h4)", "var(--wp-h5)"];

function cell(inner: string, label: string, ground: string): string {
  return `<figure class="sp ${ground}"><div>${inner}</div><figcaption>${label}</figcaption></figure>`;
}

function frameRow(name: string, frames: readonly Grid[], palIdx: number, scale: number): string {
  const pal = palIdx < 0 ? VISITOR_PAL : SKIN_PAL;
  const vars = palIdx < 0 ? "" : `${faceOf(PEOPLE[palIdx])};--accent:${HUE[palIdx]};`;
  const one = (g: Grid, i: number): string =>
    `<span class="who wp-actor" style="${vars}">${draw(g, pal, { scale })}</span>` +
    `<i>f${i}</i>`;
  return cell(frames.map(one).join(""), name, "floor");
}

function pair(name: string, frames: readonly Grid[], palIdx: number, scale: number): string {
  /* The live alternation beside the flat frames: the page keeps animations, sprites only. */
  const pal = palIdx < 0 ? VISITOR_PAL : SKIN_PAL;
  const vars = palIdx < 0 ? "" : `${faceOf(PEOPLE[palIdx])};--accent:${HUE[palIdx]};`;
  return cell(
    `<span class="who wp-actor" data-status="running" style="${vars}">` +
      drawFrames(frames, pal, { scale, className: "wp-sprite wp-stand" }) +
      `</span>`,
    name,
    "floor",
  );
}

function main(): void {
  const outDir = process.argv[2];
  if (!outDir) throw new Error("usage: sprites.js <outdir>");
  mkdirSync(outDir, { recursive: true });

  let body = "";

  for (const scale of [3, 6]) {
    body += `<h2>people — scale ${scale}</h2><section>`;
    for (const [name, frames] of Object.entries(POSES)) {
      body += frameRow(`${name}`, frames, 0, scale);
    }
    body += frameRow("idle (visitor)", POSES.idle, -1, scale);
    body += `</section>`;
  }

  body += `<h2>people — the four faces, live tempo, scale 3</h2><section>`;
  PEOPLE.forEach((_, i) => {
    body += pair(`worker ${i}`, POSES.idle, i, 3);
  });
  body += `</section>`;

  body += `<h2>presence bits</h2><section>`;
  body += cell(drawFrames([WAVE_A, WAVE_B], WAVE_PAL, { scale: 4 }), "wave", "floor");
  body += cell(draw(BANG.grid, BANG.pal, { scale: 4 }), "bang", "floor");
  body += cell(draw(RING.grid, RING.pal, { scale: 4, outline: false }), "ring", "floor");
  body += `</section>`;

  for (const ground of ["floor", "lawn"]) {
    body += `<h2>tiles on ${ground} — scale 3 and 6</h2><section>`;
    for (const [id, t] of Object.entries(TILES)) {
      body += cell(
        draw(t.grid, t.pal, { scale: 3, outline: !!t.rim }) +
          draw(t.grid, t.pal, { scale: 6, outline: !!t.rim }),
        id,
        ground,
      );
    }
    body += `</section>`;
  }

  body += `<h2>room pieces (legacy PROPS)</h2><section>`;
  for (const [id, p] of Object.entries(PROP_PIECES)) {
    body += cell(draw(p.grid, p.pal, { scale: 3 }), id, "floor");
  }
  body += `</section>`;

  const page = (vars: string, klass: string): string =>
    `<!DOCTYPE html><html><head><meta charset="utf-8"><style>:root{${vars}}</style>` +
    `<style>${STYLE}</style><style>
      body { margin: 0; }
      .wp-sheet { padding: 12px; display: block; height: auto; overflow: auto; }
      .wp-sheet h2 { color: var(--wp-fg); font: 700 12px sans-serif; text-transform: uppercase; margin: 18px 4px 6px; }
      .wp-sheet section { display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-end; }
      .sp { margin: 0; padding: 8px; display: flex; flex-direction: column; gap: 4px; }
      .sp > div { display: flex; gap: 6px; align-items: flex-end; }
      .sp.floor { background: var(--t-floor); }
      .sp.lawn { background: var(--t-ground); }
      .sp figcaption { color: var(--wp-fg); font: 10px monospace; }
      .sp i { color: var(--wp-dim); font: 9px monospace; align-self: flex-start; }
      .sp .who { display: inline-flex; position: static; width: auto; height: auto; cursor: default; }
      .sp svg { display: block; }
    </style></head><body class="${klass}"><div class="wp"><div class="wp-sheet">${body}</div></div></body></html>`;

  writeFileSync(join(outDir, "sprites-dark.html"), page(DARK, "vscode-dark"));
  writeFileSync(join(outDir, "sprites-light.html"), page(LIGHT, "vscode-light"));
  console.log("sprites: 2 pages");
}

main();
