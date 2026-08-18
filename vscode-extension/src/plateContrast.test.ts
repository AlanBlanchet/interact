import { strict as assert } from "node:assert";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { contrastRatio, mix, over, parseHex, type Rgb } from "./contrast.ts";

// The workplace has now shipped TWO contrast defects on the same surface — the title badge
// (2.38:1) and then the worker name plate. Both were judged by eye or by a computed-style read,
// and a computed-style read cannot see this stack at all: the plate's background is TRANSLUCENT,
// so its real colour depends on the room art behind it, and an ancestor `opacity` composites the
// text along with it. So model the stack and hold a floor, rather than fixing one plate again.
//
// The floor is not a bare 4.5. visual-critic measured REAL pixels twice on this surface: the
// title badge computed 7.95 and measured 6.998, and the 10px name plate measured 3.81-4.05
// against a nominal well above 4.5. Small semibold text is mostly anti-aliased pixels, so the
// perceived contrast runs materially under the nominal colour pair. 10px plate text therefore
// has to clear AA with roughly 2x headroom to survive the sampling.
const SMALL_TEXT_FLOOR = 8;

const style = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "..", "webview", "workplace", "style.ts"),
  "utf8",
);

/** The body of a rule, or a thrown error naming the selector that vanished.
 *
 *  Returning "" for an absent block was worse than useless here: `Number("" || 1)` reads as
 *  "fully opaque", so a renamed selector would silently turn this into a test of nothing while
 *  still passing. A missing rule is a broken test, not a default. */
function block(selector: string): string {
  const parts = style.split(selector);
  if (parts.length < 2) throw new Error(`no rule '${selector}' in style.ts — did it get renamed?`);
  return parts[1].slice(0, parts[1].indexOf("}"));
}

/** A declaration from a rule that MUST exist, else undefined when absent from a rule that may not. */
function decl(selector: string, prop: string): string | undefined {
  const m = new RegExp(`${prop}\\s*:\\s*([^;]+);`).exec(block(selector));
  return m ? m[1].trim() : undefined;
}

/** Whether style.ts declares a rule at all. */
function hasRule(selector: string): boolean {
  return style.includes(selector);
}

/** `color-mix(in srgb, var(--x) N%, transparent)` -> N/100, else fully opaque. */
function alphaOf(css: string): number {
  const m = /color-mix\(in srgb,\s*var\([^)]+\)\s*([\d.]+)%\s*,\s*transparent\)/.exec(css);
  return m ? Number(m[1]) / 100 : 1;
}

// Both themes, at the fallbacks the stylesheet itself declares plus VS Code's shipping dark.
const THEMES: Array<{ name: string; bg: Rgb; fg: Rgb }> = [
  { name: "dark (fallback)", bg: parseHex("#1e1e1e"), fg: parseHex("#d4d4d4") },
  { name: "dark modern", bg: parseHex("#1f1f1f"), fg: parseHex("#cccccc") },
  { name: "light", bg: parseHex("#ffffff"), fg: parseHex("#3b3b3b") },
];

// A plate can sit over any room surface; these are the lightest and darkest the rooms paint.
const BACKDROPS = [19, 34];

test("the done state does not fade the plate — that is what broke the contrast", () => {
  // Stated positively, so it fails if the rule ever comes back rather than only measuring its
  // absence indirectly. `opacity` composites the TEXT along with its translucent background, so
  // the name's real colour came from whatever room art sat behind it.
  assert.equal(hasRule('.wp-worker[data-status="done"] .wp-plate'), false);
});

test("a finished worker's name stays readable on every room surface, in every theme", () => {
  const plateBg = decl(".wp-plate {", "background")!;
  const doneSel = '.wp-worker[data-status="done"] .wp-plate {';
  const doneOpacity = Number((hasRule(doneSel) ? decl(doneSel, "opacity") : undefined) ?? 1);
  const nameSel = '.wp-worker[data-status="done"] .wp-name {';
  const doneName = (hasRule(nameSel) ? decl(nameSel, "color") : undefined) ?? "";

  const failures: string[] = [];
  for (const theme of THEMES) {
    for (const pct of BACKDROPS) {
      const room = mix(theme.fg, theme.bg, pct);
      const plate = over(theme.bg, room, alphaOf(plateBg));
      // The name is --wp-fg unless the done rule dims it; a `color-mix(... N%, var(--wp-bg))`
      // reads as N% of the foreground.
      const dim = /([\d.]+)%/.exec(doneName);
      const ink = dim ? mix(theme.fg, theme.bg, Number(dim[1])) : theme.fg;
      // An `opacity` on the plate composites BOTH the text and the plate onto the room.
      const text = over(ink, room, doneOpacity);
      const surface = over(plate, room, doneOpacity);
      const ratio = contrastRatio(text, surface);
      if (ratio < SMALL_TEXT_FLOOR) {
        failures.push(`${theme.name} over ${pct}% room: ${ratio.toFixed(2)}:1`);
      }
    }
  }
  assert.deepEqual(failures, [], `done-state name plate under ${SMALL_TEXT_FLOOR}:1`);
});

test("a running worker's name clears the same floor", () => {
  const plateBg = decl(".wp-plate {", "background")!;
  const failures: string[] = [];
  for (const theme of THEMES) {
    for (const pct of BACKDROPS) {
      const room = mix(theme.fg, theme.bg, pct);
      const plate = over(theme.bg, room, alphaOf(plateBg));
      const ratio = contrastRatio(theme.fg, plate);
      if (ratio < SMALL_TEXT_FLOOR) failures.push(`${theme.name} over ${pct}%: ${ratio.toFixed(2)}:1`);
    }
  }
  assert.deepEqual(failures, [], `running name plate under ${SMALL_TEXT_FLOOR}:1`);
});

test("hex parsing keeps its channels straight when an alpha is present", () => {
  // "#fff8" used to be read as three channels of "ff","f8",NaN — an alpha silently becoming part
  // of the colour, in a module whose whole job is producing trustworthy numbers.
  assert.deepEqual(parseHex("#fff"), parseHex("#ffffff"));
  assert.deepEqual(parseHex("#fff8"), parseHex("#ffffff"));
  assert.deepEqual(parseHex("#1e1e1eff"), parseHex("#1e1e1e"));
  assert.throws(() => parseHex("#12345"));
});
