/** WHICH WAY THE SUN IS, checked against the drawing rather than against a screenshot.
 *
 *  "Floating trees." Reported three times.
 *
 *  Three rounds, three different mechanisms, and the first two were each a real fix that left the
 *  third one standing:
 *
 *    1. the shadow was the prop's grid TRANSLATED two cells down and right — a fine contact patch
 *       for something flat, a dark canopy hanging in the air for anything tall. Replaced with a
 *       projection.
 *    2. the projection put a pixel standing ON the base nowhere, so a pine's skirt and a shrub
 *       swallowed their own shade. Given a one-cell step off the foot.
 *    3. and all along THE PROJECTION RAN NORTH — toward the light. `wallShadow` drops its band
 *       south and east of every wall, `CAST` is `+2,+2`, the character's contact patch is thrown
 *       down and right, and this one alone went up. So the far end of a tree's shadow — the
 *       canopy, the big part — came to rest BEHIND the trunk, hidden by the silhouette that cast
 *       it, and what escaped was a bar level with the trunk sticking out to the right. Clear grass
 *       under the foot, a dark dash at the waist: a tree standing on nothing.
 *
 *  Every one of those is invisible to a test that renders strings and survives a screenshot,
 *  because a shadow that is merely on the WRONG SIDE still looks like a shadow in a thumbnail. It
 *  is also compressed enough (three cells for an eight-row tree) that it never got far enough
 *  north to look absurd on its own — it just sat under the object like a stain, and every check
 *  anybody ran asked "does it touch?" rather than "which way does it go?".
 *
 *  So the rule is stated as an invariant over the ART, and it is one line:
 *
 *      A SHADOW STARTS AT THE FOOT AND IS THROWN AWAY FROM THE LIGHT.
 *
 *  The light is in the north-west, for everything in this world. Therefore, for every tile this
 *  renderer casts for: the shadow exists; its nearest row is exactly one below the art's OWN
 *  lowest pixel (not the tile's bottom row — sixteen of the props stop short of theirs, and
 *  measuring from the cell is how their shade ends up a gap below their feet); nothing it draws
 *  lies north or west of that foot; it touches what casts it; and a taller thing throws further
 *  than a shorter one, or height is not being expressed at all.
 *
 *  Plus the one thing the tiles cannot say on their own: a shadow now lands on the tile in FRONT
 *  of its caster, so the paint order became load-bearing. Every shadow in a group must be emitted
 *  before every body in it, or a tree's shade paints over the canopy of whoever stands one tile
 *  downhill — and a copse is trees in touching cells, so that is most of the wood.
 *
 *  Prints one line per tile and exits non-zero on any violation, so it can be run by hand or by
 *  the suite, exactly like `dev/placement.ts`:
 *
 *      node out-shadows.js
 */
import { FLAT } from "../scene";
import { renderWorkplace } from "../index";
import { footRow, project, shadowReach } from "../light";
import { TILES, TILE_CELLS } from "../tiles";
import type { TileId } from "../tiles";
import { fixture } from "./fixture";

interface Box {
  t: number;
  b: number;
  l: number;
  r: number;
  n: number;
}

/** The drawn extent of a grid, in cells, plus how many cells are inked. */
function box(grid: readonly string[]): Box {
  let t = Infinity;
  let b = -1;
  let l = Infinity;
  let r = -1;
  let n = 0;
  grid.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      if (row[x] === "." || row[x] === " ") continue;
      n++;
      if (y < t) t = y;
      if (y > b) b = y;
      if (x < l) l = x;
      if (x > r) r = x;
    }
  });
  return { t, b, l, r, n };
}

/** Is any inked cell of the shadow a neighbour (8-connected) of an inked cell of the art?
 *
 *  This is the property the whole complaint is about, and the only one that cannot be faked by a
 *  shadow of the right size in the wrong place. */
function touches(art: readonly string[], cast: readonly string[]): boolean {
  const ink = new Set<string>();
  art.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) if (row[x] !== "." && row[x] !== " ") ink.add(x + ":" + y);
  });
  for (let y = 0; y < cast.length; y++) {
    const row = cast[y];
    for (let x = 0; x < row.length; x++) {
      if (row[x] !== "#") continue;
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) if (ink.has(x + dx + ":" + (y + dy))) return true;
      }
    }
  }
  return false;
}

/** A column `h` cells tall standing on the bottom of an 8-cell tile. Used to prove that height is
 *  actually expressed: two different heights must give two different reaches. */
function column(h: number): string[] {
  return Array.from({ length: TILE_CELLS }, (_, r) => (r >= TILE_CELLS - h ? "...#...." : "........"));
}

function main(): void {
  const faults: string[] = [];
  let checked = 0;

  for (const id of Object.keys(TILES) as TileId[]) {
    if (FLAT.has(id)) continue;
    const t = TILES[id];
    const art = box(t.grid);
    if (art.n === 0) continue;
    checked++;
    const cast = project(t.grid, !!t.leafy);
    const s = box(cast);
    const foot = footRow(t.grid);
    const say = (why: string): void => { faults.push(`${id}: ${why}`); };

    if (s.n === 0) {
      say("casts nothing at all");
      continue;
    }
    // AWAY FROM THE LIGHT. Not one cell of it may sit level with or above the foot: a shadow that
    // shares rows with the thing casting it is a shadow hiding behind it.
    if (s.t <= foot) {
      say(`reaches north to row ${s.t}, at or above its own foot at row ${foot} — thrown toward the light`);
    }
    // AND IT STARTS AT THE FOOT. One row below, never two: a gap is the whole complaint.
    if (s.t !== foot + 1) {
      say(`starts at row ${s.t}, ${s.t - foot} below its foot at ${foot} — a shadow starts one below`);
    }
    if (s.l < art.l) {
      say(`reaches west to column ${s.l}, left of its own left edge at ${art.l}`);
    }
    if (!touches(t.grid, cast)) {
      say("does not touch the thing that casts it");
    }
    const depth = s.b - foot;
    const reach = s.r - art.r;
    console.log(
      `${id.padEnd(12)} foot@${String(foot).padStart(2)}  cast rows ${String(s.t).padStart(2)}..${String(s.b).padStart(2)}` +
        `  ${String(depth).padStart(2)} south  ${String(reach).padStart(2)} east  ${String(s.n).padStart(3)} cells`,
    );
  }

  /* ── AND HEIGHT MUST ACTUALLY READ ─────────────────────────────────────────────────────────
     Before this round every prop in the set — a three-row glow and an eight-row tree alike —
     threw a shadow spanning exactly the same three rows, because the compression collapsed the
     whole grid into the foot's own band. That is not a shadow, it is a decal, and it is why a
     tall thing looked no more planted than a flat one. Two columns of different height must
     differ in both axes. */
  const shortCast = box(project(column(2)));
  const tallCast = box(project(column(TILE_CELLS)));
  if (!(tallCast.b > shortCast.b && tallCast.r > shortCast.r)) {
    faults.push(
      `height does not read: a ${TILE_CELLS}-cell column reaches row ${tallCast.b}/col ${tallCast.r}, ` +
        `a 2-cell one reaches row ${shortCast.b}/col ${shortCast.r}`,
    );
  }
  console.log(
    `\nheight reads: 2 cells -> ${shortCast.b - (TILE_CELLS - 1)} south / ${shortCast.r - 3} east, ` +
      `${TILE_CELLS} cells -> ${tallCast.b - (TILE_CELLS - 1)} south / ${tallCast.r - 3} east.`,
  );

  /* ── AND THE PAINT ORDER ───────────────────────────────────────────────────────────────────
     A shadow lands on the tile in FRONT of its caster now, so an interleaved `cast, body, cast,
     body` emission paints a tree's shade straight over its neighbour's canopy. Checked on the
     real document rather than on the function that writes it: inside the group that holds the
     grounds, every shadow must come before every body. */
  const doc = renderWorkplace(fixture(), "devnonce123");
  const loose = doc.slice(doc.indexOf('<g class="wp-loose">'));
  const uses = [...loose.slice(0, loose.indexOf("</g>")).matchAll(/<use\b[^>]*>/g)].map((m) => m[0]);
  const lastDrop = uses.map((u) => u.includes("wp-drop")).lastIndexOf(true);
  const firstBody = uses.findIndex((u) => !u.includes("wp-drop"));
  if (lastDrop >= 0 && firstBody >= 0 && lastDrop > firstBody) {
    faults.push(
      `the grounds interleave shadows with bodies: body #${firstBody} is emitted before shadow #${lastDrop} ` +
        `of ${uses.length} — a shadow will paint over the prop in front of it`,
    );
  }
  console.log(
    `paint order: ${uses.length} nodes in the grounds, ${lastDrop + 1} shadows, all before the first body.`,
  );

  const cast = shadowReach(TILE_CELLS);
  console.log(`\n${checked} tiles cast. A full-height tile reaches ${cast.east} tile east, ${cast.south} south.`);
  if (faults.length) {
    console.log("\nSHADOWS THROWN THE WRONG WAY:");
    for (const f of faults) console.log("  " + f);
    process.exit(1);
  }
  console.log("Every shadow starts one cell below its own foot and is thrown away from the light.");
}

main();
