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
 *  ── AND THEN A FOURTH AND A FIFTH, both of which THIS FILE COULD NOT SEE ────────────────────
 *
 *  The three above are properties of one tile's ART, and a per-tile check is the right instrument
 *  for them. The next two are properties of the DOCUMENT, and a per-tile check is structurally
 *  blind to both — which is exactly the gap a fourth report was going to arrive in.
 *
 *    4. INDOOR PROPS SHOWED NO SHADOW AT ALL. Not detached: absent, on a pixel scan of the floor
 *       under a potted tree — and a small conifer on a flat grey floor with no shade is the most
 *       literal floating in the whole picture. The art was right and the DOM was right; the INK
 *       was `--wp-ink` at 44%, and `--wp-ink` is the same near-black an unlit room's floor already
 *       is. Measured: floor 0.079 luminance, its shadow 0.074. A shadow painted in the colour of
 *       the thing it falls on cannot be seen, and no invariant over a grid of "#" can tell.
 *       Two ways in for a probe that never opens a pixel: every standing prop must OWN a drop in
 *       the rendered document (a whole class silently casting nothing shows up as a count), and
 *       the ink must be OPAQUE with the strength carried as a ratio on the layer.
 *    5. THE SHADE LAYER PAINTED OVER EVERY BODY ON THE MAP. Shadows were emitted before bodies
 *       WITHIN each room's group — correct locally, useless globally, because the document then
 *       read `roomA casts, roomA bodies, roomB casts, …, grounds casts, grounds bodies` and the
 *       grounds hold 243 of them and come last. A bush one tile north of a conifer smeared a band
 *       across its canopy. That is a z-order bug, not a tree bug: any prop set denser than this
 *       forest reproduces it. So the check is on the whole map, not inside one group.
 *
 *  And one measurement rather than a rule, because "reads as a bar" is not a boolean: the longest
 *  UNBROKEN run of shade anywhere on the site. A copse used to lay 32 cells of it end to end (the
 *  55px slab an independent critic measured under two trunks); solid-is-contact-and-thrown-is-
 *  dapple takes it to 15, and nothing on the site now runs longer than two tiles.
 *
 *  Prints one line per tile plus the document checks, and exits non-zero on any violation, so it
 *  can be run by hand or by the suite, exactly like `dev/placement.ts`:
 *
 *      node out-shadows.js
 */
import { FLAT, worldFor } from "../scene";
import { renderWorkplace } from "../index";
import { STYLE } from "../style";
import { footRow, project, shadowReach } from "../light";
import { TILES, TILE_CELLS } from "../tiles";
import type { TileId } from "../tiles";
import { WALL_FIXTURES } from "../world";
import type { Prop, Room } from "../world";
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

/** How many cells of unbroken shade stop reading as several things' shade and start reading as one
 *  bar. Two tiles: a tree's own throw is a little over one, so anything past two is two casters
 *  fused. The measured slab was four. */
const SLAB = TILE_CELLS * 2;

/** The whole of one element, balanced — the map nests the pattern svgs and the shade layers nest
 *  nothing, but a bare indexOf of the closing tag lands inside the first nested one either way. */
function balanced(doc: string, start: number, open: RegExp, close: string): string {
  const re = new RegExp(`${open.source}|${close}`, "g");
  re.lastIndex = start;
  let depth = 0;
  for (let m = re.exec(doc); m; m = re.exec(doc)) {
    depth += m[0] === close ? -1 : 1;
    if (depth === 0) return doc.slice(start, m.index + close.length);
  }
  throw new Error(`unbalanced ${close} from ${start}`);
}

const svgAt = (doc: string, at: number): string => balanced(doc, at, /<svg\b/, "</svg>");
const svgGroupAt = (doc: string, at: number): string => balanced(doc, at, /<g\b/, "</g>");
const count = (s: string, re: RegExp): number => [...s.matchAll(re)].length;

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

  const doc = renderWorkplace(fixture(), "devnonce123");
  const map = svgAt(doc, doc.indexOf('<svg class="wp-map"'));
  const world = worldFor(fixture().workers as never);
  const rooms: Room[] = [...world.rooms];
  const flag = (why: string): void => { faults.push(why); };

  /* ── 1. THE PAINT ORDER, ACROSS THE WHOLE MAP ──────────────────────────────────────────────
     A shadow lands on the tile in FRONT of its caster, so shade has to be UNDER everything that
     stands up — not merely under the bodies of the same room. The old check read one group and
     passed while 243 grounds shadows painted over the entire building, because "before every body
     in this group" is true of a group that is itself painted last. So: every drop in the document
     lives in a shade layer, and every shade layer closes before the first thing that stands up. */
  const firstStanding = map.indexOf('<g class="wp-rm wp-bu');
  const drops = [...map.matchAll(/<use class="wp-drop"[^>]*>/g)];
  const strays = drops.filter((m) => (m.index ?? 0) > firstStanding);
  if (strays.length) {
    flag(
      `${strays.length} of ${drops.length} shadows are emitted AFTER the first prop body on the map — ` +
        `they will paint over whatever is standing in front of them`,
    );
  }
  const layers = [...map.matchAll(/<g class="wp-shadow ([^"]*)">/g)];
  const inLayers = layers.reduce((n, m) => n + count(svgGroupAt(map, m.index ?? 0), /<use class="wp-drop"/g), 0);
  if (inLayers !== drops.length) {
    flag(`${drops.length - inLayers} shadows are outside the shade layers — those cannot union or be dimmed as one`);
  }
  console.log(
    `\npaint order: ${drops.length} shadows in ${layers.length} layers ` +
      `(${layers.map((m) => m[1]).join(", ")}), all before the first body at ${firstStanding}.`,
  );

  /* ── 2. THE STRENGTH IS A RATIO ON THE LAYER, NOT AN ALPHA ON THE INK ──────────────────────
     Both of the round-four defects live here. A translucent ink cannot be seen on a floor its own
     colour (the potted trees, in every unlit room), and translucent inks STACK, which is what a
     copse's overlaps were doing before the layer existed. Opaque children under a group opacity
     fixes both at once and neither can regress silently: the ink must have no alpha, and each
     layer must carry one. */
  for (const m of STYLE.matchAll(/--wp-drop:\s*([^;]+);/g)) {
    const ink = m[1].trim();
    if (/transparent|rgba|hsla|\/\s*[\d.]+/.test(ink)) {
      flag(`--wp-drop is translucent (${ink}) — a per-element alpha stacks where two shadows cross, and vanishes on a floor its own colour`);
    }
  }
  const strengths = [...STYLE.matchAll(/\.wp-shadow\.(is-in|is-out)\s*\{[^}]*opacity:\s*([\d.]+)/g)];
  for (const m of layers) {
    const cls = m[1].trim();
    if (!strengths.some((s) => s[1] === cls)) flag(`the ${cls} shade layer has no opacity — its shadows will paint at full ink`);
  }
  console.log(`strength: ${strengths.map((s) => "." + s[1] + " " + s[2]).join(", ")} of the surface's own light, ink opaque.`);

  /* ── 3. EVERY STANDING PROP CASTS, INDOORS AS WELL AS OUT ──────────────────────────────────
     The defect this replaces was invisible to a per-tile check because the tiles were fine: the
     renderer simply never showed what they drew. Counted from the built world rather than from
     the list of things that ought to cast, and reported PER ROOM, so a whole interior quietly
     casting nothing is one line rather than a number nobody can place.
     A prop that does not cast has to be one of exactly two DECISIONS — it lies on the ground, or
     it hangs on a wall — never an omission. */
  const groups: { name: string; props: readonly Prop[] }[] = [
    ...rooms.map((r) => ({ name: (r.outdoor ? "yard " : "") + (r.id || "lobby"), props: r.props })),
    { name: "hall", props: world.hallProps },
    { name: "grounds", props: world.scenery },
  ];
  let expected = 0;
  console.log("\nwhere                 props  cast  flat (ground / hung)");
  for (const g of groups) {
    const castable = g.props.filter((p) => !FLAT.has(p.tile));
    const hung = g.props.filter((p) => WALL_FIXTURES.has(p.tile));
    const ground = g.props.length - castable.length - hung.length;
    expected += castable.length;
    if (g.props.length && !castable.length) {
      flag(`${g.name} has ${g.props.length} props and casts nothing at all — an interior with no shade is furniture on a printed floor`);
    }
    console.log(
      `${g.name.padEnd(20)} ${String(g.props.length).padStart(5)} ${String(castable.length).padStart(5)} ` +
        `${String(ground).padStart(6)} / ${hung.length}`,
    );
  }
  if (expected !== drops.length) {
    flag(`the world has ${expected} standing props but the document draws ${drops.length} shadows`);
  }

  /* ── 4. AND NO SLAB ────────────────────────────────────────────────────────────────────────
     Not a rule but a measurement, because "reads as one bar rather than per-tree shade" is not a
     boolean. Every cast rasterised into the world's own cells: how deep the deepest overlap is
     (the union makes the DRAWN answer 1 whatever this says, but a rising number means the layout
     is crowding), and the longest unbroken horizontal run of shade anywhere. A row of trees used
     to butt their solid contact bands end to end for 32 cells — four tiles of continuous ink, and
     the 55px bar a critic measured under two trunks. Solid-is-contact / thrown-is-dapple is what
     holds this down, and it is the number that says so. */
  const C = TILE_CELLS;
  const cover = new Int16Array(world.cols * C * world.rows * C);
  const W = world.cols * C;
  for (const g of groups) {
    for (const p of g.props) {
      if (FLAT.has(p.tile)) continue;
      const grid = project(TILES[p.tile].grid, !!TILES[p.tile].leafy);
      grid.forEach((row, y) => {
        for (let x = 0; x < row.length; x++) {
          if (row[x] !== "#") continue;
          const X = p.x * C + x;
          const Y = p.y * C + y;
          if (X >= 0 && X < W && Y >= 0 && Y < world.rows * C) cover[Y * W + X]++;
        }
      });
    }
  }
  let longest = 0;
  let deepest = 0;
  let where = "";
  for (let y = 0; y < world.rows * C; y++) {
    let run = 0;
    for (let x = 0; x <= W; x++) {
      const v = x < W ? cover[y * W + x] : 0;
      if (!v) { run = 0; continue; }
      if (v > deepest) deepest = v;
      if (++run > longest) { longest = run; where = `row ${y} (tile y ${Math.floor(y / C)})`; }
    }
  }
  if (longest > SLAB) {
    flag(`${longest} cells of unbroken shade at ${where} — over ${SLAB} it stops reading as several things' shade and becomes one bar`);
  }
  console.log(
    `\nno slab: longest unbroken run ${longest} cells (${(longest / C).toFixed(1)} tiles, limit ${SLAB}); ` +
      `deepest geometric overlap ${deepest}, drawn as ${deepest ? 1 : 0} by the layer's own union.`,
  );

  const cast = shadowReach(TILE_CELLS);
  console.log(`\n${checked} tiles cast. A full-height tile reaches ${cast.east} tile east, ${cast.south} south.`);
  if (faults.length) {
    console.log("\nSHADOWS THROWN THE WRONG WAY:");
    for (const f of faults) console.log("  " + f);
    process.exit(1);
  }
  console.log("Every shadow starts one cell below its own foot, is thrown away from the light, and lies under everything standing.");
}

main();
