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

// Every text element the plate carries, with the nominal floor its size demands. The floor rises
// as the text shrinks: measured pixel contrast ran ~0.6x nominal at 10px on this surface, and
// worse at 9px, because a smaller glyph is a larger fraction anti-aliased.
//
// Enumerated rather than spot-checked, because spot-checking is what went wrong: the done-state
// fix landed on `.wp-name` and its sibling `.wp-since` in the same plate kept its old colour,
// measuring 1.5-2.6:1 — worse than the original complaint that started all this.
const PLATE_TEXT = [
  { selector: ".wp-name {", px: 10, floor: 8 },
  { selector: ".wp-since {", px: 10, floor: 8.5 },
];

function plateSurface(theme: { bg: Rgb; fg: Rgb }, roomPct: number, plateBg: string): Rgb {
  return over(theme.bg, mix(theme.fg, theme.bg, roomPct), alphaOf(plateBg));
}

/** Resolve a CSS colour expressed against the theme tokens this stylesheet mixes in. */
function inkOf(css: string, theme: { bg: Rgb; fg: Rgb }): Rgb {
  // --wp-dim is the theme's descriptionForeground; its shipping value in each.
  const dim: Rgb = theme.bg[0] < 128 ? parseHex("#9d9d9d") : parseHex("#717171");
  const pct = /(\d+)%/.exec(css);
  if (!pct) return css.includes("--wp-dim") ? dim : theme.fg;
  const [first] = css.split(",").slice(1);       // color-mix(in srgb, <first> N%, <second>)
  const second = css.split(",")[2] ?? "";
  const token = (t: string): Rgb => (t.includes("--wp-dim") ? dim : t.includes("--wp-bg") ? theme.bg : theme.fg);
  return mix(token(first ?? ""), token(second), Number(pct[1]));
}

test("every text element on the plate clears the floor its size demands", () => {
  const plateBg = decl(".wp-plate {", "background")!;
  const failures: string[] = [];

  for (const { selector, px, floor } of PLATE_TEXT) {
    const colour = decl(selector, "color");
    assert.ok(colour, `${selector} declares no colour — did it get renamed?`);
    for (const theme of THEMES) {
      for (const pct of BACKDROPS) {
        const ratio = contrastRatio(inkOf(colour!, theme), plateSurface(theme, pct, plateBg));
        if (ratio < floor) {
          failures.push(`${selector} ${px}px, ${theme.name} over ${pct}% room: ${ratio.toFixed(2)}:1 < ${floor}`);
        }
      }
    }
  }
  assert.deepEqual(failures, []);
});

test("the done state does not fade any of it", () => {
  // opacity on the plate composites every glyph in it, not just the one that was measured.
  assert.equal(hasRule('.wp-worker[data-status="done"] .wp-plate'), false);
});

test("hex parsing keeps its channels straight when an alpha is present", () => {
  assert.deepEqual(parseHex("#fff"), parseHex("#ffffff"));
  assert.deepEqual(parseHex("#fff8"), parseHex("#ffffff"));
  assert.deepEqual(parseHex("#1e1e1eff"), parseHex("#1e1e1e"));
  assert.throws(() => parseHex("#12345"));
});
