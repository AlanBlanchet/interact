/** The scene: a building, and the people in it, seen through a WINDOW.
 *
 *  Three layers, and the split is the point.
 *
 *  The MAP is a pure function of the room table — it does not change when the team does — so it is
 *  rendered once and never re-sent. The ACTORS are the only thing a snapshot produces, a few
 *  hundred bytes rather than the whole building, which is what lets the panel push a new scene
 *  several times a second without the floor flickering. The VIEW is a bounded viewport the engine
 *  moves: the building is deliberately bigger than the panel, and the camera goes to where the
 *  work is.
 *
 *  That last one is not a nicety. The view this replaces scaled the WHOLE building down to fit
 *  whatever width it was given, so in the side bar it actually ships in it settled at half scale:
 *  characters eighteen pixels tall, capability marks SIX pixels across, and half the panel empty
 *  underneath. Fitting everything into the frame is the one thing a game never does.
 *
 *  Nothing here positions a person. An actor carries the SEAT it belongs to and nothing else; the
 *  simulation owns where a body actually is and may have it somewhere else entirely at the moment
 *  this markup lands.
 */
import { ZONES } from "../../src/team";
import type { TeamState, Worker, ZoneId } from "../../src/team";
import { FACULTIES } from "../../src/capabilities";
import { closeSheet, draw, drawFrames, openSheet, place } from "./pixels";
import type { Grid } from "./pixels";
import {
  FACULTY_ART,
  BANG,
  NOTE,
  POSE_AWAY_A,
  POSE_AWAY_B,
  POSE_BLINK,
  POSE_MOVE,
  POSE_REST,
  POSE_REST_A,
  POSE_REST_B,
  POSE_REST_BLINK,
  POSE_SIT_A,
  POSE_SIT_B,
  POSE_SIT_BLINK,
  POSE_SLUMP,
  POSE_STRIDE_A,
  POSE_STRIDE_B,
  POSE_STRIDE_C,
  POSE_WALK_A,
  POSE_WALK_B,
  RING,
  SKIN_PAL,
  SNOOZE,
  VISITOR_PAL,
  WAVE_A,
  WAVE_B,
  WAVE_PAL,
} from "./art";
import { TILES, TILE_CELLS, TILE_PX } from "./tiles";

/** How far the ground runs past the built world, in tiles.
 *
 *  Forty was derived for a TALL, NARROW panel and does not survive a WIDE one. At the bottom rung
 *  a tile is eight device pixels, so the whole 67-tile site is 536px across — narrower than any
 *  editor pane — and forty tiles of margin buys 320px a side. Measured in a 1394px viewport:
 *  105px of bare panel showing on the left and 72 on the right. The edge of the drawing, which is
 *  precisely what this constant exists to prevent, and it only appears at the rung that was added
 *  after this number was last checked.
 *
 *  Sized from the WORST case instead of from one panel: a 4K-wide pane at the bottom rung wants
 *  (3840 - 536) / 2 / 8 ≈ 207 tiles a side. It costs ONE `rect` with a pattern fill whatever the
 *  number is — the pattern tiles from the origin, so any whole number of tiles out is seamless,
 *  and the renderer only rasterises the part inside the viewport. */
const GROUNDS = 220;
import type { TileId } from "./tiles";
import { PITCH, WALL_FIXTURES, buildWorld } from "./world";
import type { Dept, Prop, Rect, Room, Seat, World } from "./world";
import { assignAccents, atMillis, faceOf, hash, idleAmount, shortDuration } from "./palette";
import { HEAD, WORDS, attentionOf, behaviourOf, isHeld, markOf, stampHtml, worldStampFor } from "./status";
import type { Posture } from "./status";
import { lampsFor, poolRuns, project, runPath as litPath, wallShadow, LEVELS } from "./light";
import { buildPods, posts, tally } from "./layout";
import type { Post } from "./layout";
import { clip, esc } from "./esc";

/** A worker may carry the faculties its own definition file grants it. Optional because the
 *  registry has not always written them, and a character with no declared powers must still
 *  render — as one with nothing shown, never as a crash. */
export type Cast = Worker & { faculties?: readonly string[] };

const LABELS = new Map<ZoneId, string>(ZONES.map((z) => [z.id, z.label]));
const MARK_OF = new Map(FACULTIES.map((f) => [f.id, f]));

/** How many marks a character wears at rest. Six at six pixels was the defect; three at fourteen
 *  is a row you can actually read, and the three chosen are the ones that make THIS agent
 *  different from the rest of the company rather than the first three in a fixed list. */
const MARKS_SHOWN = 3;

/* ── who works where, and what that room is for ─────────────────────────────────────────────*/

/** How common each faculty is across the whole company. A capability everybody has says nothing
 *  about anybody; the rare one is the whole character. */
function rarity(workers: readonly Cast[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const w of workers) for (const f of w.faculties ?? []) out.set(f, (out.get(f) ?? 0) + 1);
  return out;
}

/** The departments this team actually has, in a stable order, taken from the workers themselves —
 *  each carrying the faculties its people declare, ranked by how much they DISTINGUISH it from the
 *  rest of the company. That ranking is what furnishes the room: a department whose people run
 *  commands more than anyone else's gets a machine room, one whose people only read gets the
 *  stacks. No department name appears anywhere in the plan. */
export function deptsOf(workers: readonly Cast[]): Dept[] {
  const seen = new Map<string, string>();
  for (const w of workers) {
    if (!w.department) continue;
    if (!seen.has(w.department)) seen.set(w.department, w.room || w.department);
  }
  const heads = headcounts(workers);
  const company = rarity(workers);
  const people = Math.max(1, workers.length);
  return [...seen]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([id, label]) => {
      const mine = workers.filter((w) => w.department === id);
      const local = rarity(mine);
      const size = Math.max(1, mine.length);
      const kit = [...local]
        .map(([f, n]) => ({ f, lift: n / size / ((company.get(f) ?? 1) / people) }))
        .sort((a, b) => b.lift - a.lift || a.f.localeCompare(b.f))
        .map((e) => e.f);
      return { id, label, heads: heads.get(id) ?? 0, kit };
    });
}

/** How many people each room has to hold. Rooms are SIZED from this — a fixed room silently
 *  stacks the extra people on top of each other. */
function headcounts(workers: readonly Cast[]): Map<string, number> {
  const out = new Map<string, number>();
  const add = (k: string) => out.set(k, (out.get(k) ?? 0) + 1);
  for (const w of workers) {
    if (w.zone === "web") add("__web"); /* out of the building — the YARD is sized from this too */
    else if (w.brain) add("__brain");
    else if (w.department) add(w.department);
    else add("");
  }
  return out;
}

/** The building, kept between renders while the departments hold still. The map is most of the
 *  document and none of it changes when a person moves. */
let cached: { key: string; world: World } | null = null;
export function worldFor(workers: readonly Cast[]): World {
  const depts = deptsOf(workers);
  const heads = headcounts(workers);
  const core = {
    brain: heads.get("__brain") ?? 0,
    lobby: heads.get("") ?? 0,
    web: heads.get("__web") ?? 0,
  };
  const key =
    depts.map((d) => d.id + ":" + d.label + ":" + d.heads + ":" + (d.kit ?? []).join(",")).join("|") +
    "|" +
    core.brain +
    "/" +
    core.lobby +
    "/" +
    core.web;
  if (!cached || cached.key !== key) cached = { key, world: buildWorld(depts, core) };
  return cached.world;
}

/** Where a worker stands. Their DEPARTMENT is their room. The one exception is the web, which is
 *  genuinely outside: an agent fetching from the world walks out of the gate to do it. */
export function placeOf(world: World, w: Cast): Room {
  if (w.zone === "web") return world.yard;
  if (w.brain) return world.brainRoom;
  return (w.department && world.byId.get(w.department)) || world.lobby;
}

/* ── the map ─────────────────────────────────────────────────────────────────────────────────*/

/** One tile, drawn at a cell. Scale 1: the whole map is one SVG whose user units are tile CELLS,
 *  and the pixel size arrives from the camera, so a tile is authored once and the building can be
 *  zoomed without re-rendering anything. */
function at(id: TileId, x: number, y: number, cls = "", extra = ""): string {
  const t = TILES[id];
  return place(t.grid, t.pal, x * TILE_CELLS, y * TILE_CELLS, {
    scale: 1,
    outline: !!t.rim,
    className: cls || undefined,
    attrs: extra,
  });
}

/** Tiles that cast nothing, and the reason each one does not.
 *
 *  A prop's shadow is the same drawing in one flat ink, projected — its own SILHOUETTE lying on
 *  the floor south-east of it. Everything in this world is lit from the north-west, so everything
 *  in it drops the same way; a scene where each object invents its own light direction reads as
 *  collage.
 *
 *  Two reasons, and both have to be a DECISION somebody can point at rather than a gap in a list.
 *  A thing lying ON the ground has no height to throw (a floor casting a shadow on the floor is a
 *  chequerboard), and a thing hanging on a WALL is not standing on the ground at all — that set
 *  is `WALL_FIXTURES`, derived from the archetypes' own face lists next to where the fixtures are
 *  chosen. Everything else in the building casts, indoors and out; there is no third category and
 *  no prop that quietly falls through.
 *
 *  Exported so the shadow invariant (`dev/shadows.ts`) iterates exactly the set this renderer
 *  casts for, rather than a hand-kept copy of it — four separate bugs on this view have been a
 *  duplicated list drifting from the thing it duplicated. */
export const FLAT: ReadonlySet<TileId> = new Set<TileId>([
  // GROUND: drawn where you walk, with no height above it.
  "floor", "carpet", "grass", "wall", "path", "lino", "runner", "face", "mass", "dais", "rug",
  "doorCap", "doorWay", "matt",
  // Water is a hole in the ground, not a thing standing on it, and ground cover an inch high
  // throws nothing you could see — drawn, its shadows are the dark specks that made the lawn
  // look littered rather than textured.
  "pond", "tuft", "blooms",
  // Meadow and bare earth are GROUND, and were missing from this list purely because they only
  // ever arrive as terrain runs rather than as props today — so nothing cast them and nothing
  // caught it. The shadow invariant reads this set, which is what surfaced it; a ground tile
  // dropped into `scenery` would otherwise have thrown a silhouette of a patch of grass.
  "meadow", "earth", "litter",
  // HUNG: the wall face, whose masonry already has its own band in `wallShadow`.
  ...WALL_FIXTURES,
]);

const DROP_PAL = { "#": "var(--wp-drop)" };
/** The projected grid per tile, cached by IDENTITY rather than the drawn string: the pixel engine
 *  keys its own body cache — and the render sheet's `<use>` ids — off the grid object, so handing
 *  it a freshly-built array on every placement would defeat both. One array per tile id, forever. */
const CAST_GRID = new Map<TileId, string[]>();

function castOf(id: TileId, x: number, y: number): string {
  if (FLAT.has(id)) return "";
  let grid = CAST_GRID.get(id);
  if (!grid) CAST_GRID.set(id, (grid = project(TILES[id].grid, !!TILES[id].leafy)));
  // NO offset. The projection already lands every pixel where the ground is; a translation on
  // top of it is exactly what lifted the old shadow off the thing casting it.
  return place(grid, DROP_PAL, x * TILE_CELLS, y * TILE_CELLS, {
    scale: 1,
    outline: false,
    className: "wp-drop",
  });
}

function patch(id: TileId, r: Rect): string {
  return (
    `<rect x="${r.x * TILE_CELLS}" y="${r.y * TILE_CELLS}" ` +
    `width="${r.w * TILE_CELLS}" height="${r.h * TILE_CELLS}" fill="url(#wp-p-${id})"/>`
  );
}

function patches(id: TileId, runs: readonly Rect[]): string {
  return runs.map((r) => patch(id, r)).join("");
}

function patterns(ids: TileId[]): string {
  return ids
    .map((id) => {
      const t = TILES[id];
      return (
        `<pattern id="wp-p-${id}" width="${TILE_CELLS}" height="${TILE_CELLS}" ` +
        `patternUnits="userSpaceOnUse">` +
        draw(t.grid, t.pal, { scale: 1, outline: !!t.rim }) +
        `</pattern>`
      );
    })
    .join("");
}

/** A set of tile runs as ONE path, so a room's light is exactly its floor even when the room is
 *  an L. A bounding rectangle would spill its glow into the masonry next door. */
function runPath(runs: readonly Rect[]): string {
  const c = TILE_CELLS;
  return runs.map((r) => `M${r.x * c} ${r.y * c}h${r.w * c}v${r.h * c}h-${r.w * c}z`).join("");
}

/** The overlay that makes a prop move. A separate node every time: the drawing underneath is
 *  shared through the sheet, and a class on it would animate every copy of it in the building. */
function liveOf(p: Prop): string {
  const delay = drift(p.x, p.y);
  switch (p.live) {
    case "screen":
      return at("screenGlow", p.x, p.y, "wp-lv wp-lv-screen", delay);
    case "steam":
      return at("steam", p.x, p.y - 1, "wp-lv wp-lv-steam", delay);
    case "lamp":
      return at("lampPool", p.x, p.y + 1, "wp-lv wp-lv-lamp", delay);
    default:
      return "";
  }
}

/** A per-cell head start, so ambient motion shares the beat without sharing the DOWNBEAT. Thirty
 *  screens flickering on the same frame is not a floor with screens on it, it is one animation
 *  applied thirty times — which reads instantly, and is the tell this whole surface was rejected
 *  for. Deterministic in the cell, so the building looks the same on every render. */
function drift(x: number, y: number): string {
  return `style="--d:-${(((x * 37 + y * 61) % 480) / 100).toFixed(2)}s"`;
}

/** North-to-south, so the painter's order matches the depth order: a body in front covers a body
 *  behind, never the reverse. Ties break on x so the output stays byte-stable (the map is
 *  rendered once and cached on its department key). */
function depthOrder(props: readonly Prop[]): Prop[] {
  return [...props].sort((a, b) => a.y - b.y || a.x - b.x);
}

/** SHADE IS A LAYER OF THE BUILDING, NOT A PART OF A PROP.
 *
 *  A shadow is thrown SOUTH (see `project`), so it lands on the tile in FRONT of the thing casting
 *  it. The previous round noticed that and emitted every shadow before every body — but WITHIN
 *  each room's own group, and a room's group is a sibling of eight others plus the grounds. So the
 *  document read `roomA casts, roomA bodies, roomB casts, roomB bodies, …, grounds casts, grounds
 *  bodies`, and every one of those cast passes painted over every body emitted before it. The
 *  grounds hold 243 of them and come LAST, so all 243 painted over the entire building and over
 *  each other's neighbours: a bush one tile north of a conifer smeared a grey band across its
 *  canopy, in both themes, at every rung. Local ordering cannot fix that; the group it is local to
 *  is the problem.
 *
 *  It is also not a tree bug. Any prop set denser than today's forest reproduces it identically,
 *  which is why the fix is at the LAYER: shade goes where light goes, once, for the whole map,
 *  between the floor it falls on and everything that stands up in it. Then a shadow is occluded by
 *  whatever is standing in front of it, for free and by construction.
 *
 *  And ONE layer buys the second thing a per-prop emission can never have: shade that does not
 *  COMPOUND. The group carries the alpha and its children are opaque, so two canopies crossing
 *  union to one silhouette at one density instead of stacking to twice the ink. The old code
 *  compensated for the stacking by halving the ink everywhere — a whole lawn made paler to make
 *  its overlaps survivable. Now the single shadow can be as strong as a single shadow should be.
 */
function propCasts(props: readonly Prop[]): string {
  return depthOrder(props).map((p) => castOf(p.tile, p.x, p.y)).join("");
}

function propBodies(props: readonly Prop[]): string {
  return depthOrder(props).map(propBody).join("");
}

function propBody(p: Prop): string {
  const cls =
    (p.tile === "core" ? "wp-core " : "") + (p.live === "sway" ? "wp-lv-sway " : "") + (p.live === "fan" ? "wp-lv-fan " : "");
  const own = p.live === "sway" || p.live === "fan" ? drift(p.x, p.y) : "";
  return at(p.tile, p.x, p.y, cls.trim(), own) + liveOf(p);
}

/** The building, once. Every room is a group carrying its own id and archetype, so the simulation
 *  can light it and the stylesheet can tint a machine room colder than a library. */
function renderMap(world: World): string {
  const w = world.cols * TILE_CELLS;
  const h = world.rows * TILE_CELLS;
  let out =
    `<svg class="wp-map" width="${world.cols * TILE_PX}" height="${world.rows * TILE_PX}" ` +
    `viewBox="0 0 ${w} ${h}" shape-rendering="crispEdges" aria-hidden="true" focusable="false">` +
    `<defs>${patterns([
      "floor", "carpet", "grass", "meadow", "litter", "earth", "pond", "wall", "path", "lino", "runner",
      "face", "mass", "dais", "rug",
    ])}</defs>`;

  // The envelope, then everything carved out of it. Mass first: the building is solid until a
  // room or a passage takes a bite out of it, which is what gives a shallow room something
  // BEHIND it instead of a blank corridor.
  // The ground runs well past the world. A panel whose aspect does not match the building's —
  // a 380px side bar against a hall-shaped floor — cannot frame the whole company without slack
  // in the other axis, which is geometry and not a bug; what IS a bug is that slack reading as a
  // void. Drawn as more of the same ground at the same pitch (the pattern tiles from the origin,
  // so a whole number of tiles out is seamless), it reads as the rest of the site. One rect.
  out += patch("grass", {
    x: -GROUNDS, y: -GROUNDS, w: world.cols + GROUNDS * 2, h: world.rows + GROUNDS * 2,
  });
  /* THE GROUND OF THE SITE, before anything is built on it. Meadow left unmown, bare earth, the
     pond and the made path — as pattern runs, exactly like a room's floor, because a patch of
     ground is a rectangle and never five hundred tile elements. A change of GROUND is the only
     mark on a site big enough to be read as a SHAPE at the scale where the whole company is in
     frame, which is precisely the scale the camera exists to reach: props are one tile each and
     one tile is a speck there. */
  for (const layer of world.terrain) out += patches(layer.tile, layer.runs);

  out += patch("mass", {
    x: world.envelope.x,
    y: world.envelope.y,
    w: world.facadeX - world.envelope.x + 1,
    h: world.envelope.h,
  });

  // The building's own structure, on the parts of it you do not see into. Left as a flat dark
  // field the mass reads as a void with the rooms floating in it; a column grid on a four-tile
  // rhythm is what makes it read as the rest of the building.
  {
    const cells = new Set<number>();
    for (const r of world.mass) for (let x = r.x; x < r.x + r.w; x++) cells.add(r.y * world.cols + x);
    let d = "";
    const e = world.envelope;
    for (let y = e.y + 2; y < e.y + e.h - 1; y += 4) {
      for (let x = e.x + 2; x < world.facadeX; x += 4) {
        if (!cells.has(y * world.cols + x)) continue;
        d += `M${x * TILE_CELLS + 1} ${y * TILE_CELLS + 1}h6v6h-6z`;
      }
    }
    if (d) out += `<path class="wp-struct" d="${d}"/>`;
  }

  // The spine.
  out += patch("lino", world.hall);

  /* THREE PASSES, and the order is the whole reason this looks like a room rather than a plan.
     Rooms share party walls, so a single pass drew room B's floor over room A's furniture — and,
     more importantly, LIGHT and SHADOW are properties of the building, not of one room: a wall
     between two departments casts into both. Grounds first, then the light that falls on them,
     then the shadow that cuts it, and only then anything that stands up. */

  // Everything under the roof takes the light layer, not only the rooms with doors on them. The
  // first version lit the departments and left the lobby, the plazas, the chamber and the whole
  // corridor flat — which is most of the floor, so half the building went on reading as a plan
  // while the other half read as a place. Only the yard is left out: it has no ceiling.
  const inside = world.rooms.filter((r) => !r.outdoor);

  // 1. GROUNDS.
  for (const r of world.rooms) {
    out += `<g class="wp-rm wp-gr" data-room="${esc(r.id)}" data-kind="${esc(r.kind)}">`;
    if (r.outdoor) {
      out += patch("path", { x: world.facadeX, y: world.gateY - 1, w: 4, h: 3 });
    } else if (r.open) {
      /* An open room is a FLOOR, not a hole. Skipping the floor patch here left the plazas and
         the lobby as raw building mass with furniture standing in it — a near-black quadrant on
         a real registry, and a prop on an untextured void reads as floating whatever its shadow
         does. The unlit veil still darkens an empty plaza; it now darkens a PAVED one. */
      out += patches(r.floor, r.floorRuns);
      if (r.dais) out += patch("dais", r.dais);
    } else {
      out += patches(r.floor, r.floorRuns);
      // Ground, before anything is drawn ON the ground — including the room's own light. Drawn
      // after it, a rug is the one patch of floor the room's light does not reach and reads as a
      // hole rather than as a rug, which is exactly how it looked in a light theme.
      if (r.rug) {
        out += patch("rug", r.rug);
        out +=
          `<rect class="wp-rug" x="${r.rug.x * TILE_CELLS + 1}" y="${r.rug.y * TILE_CELLS + 1}" ` +
          `width="${r.rug.w * TILE_CELLS - 2}" height="${r.rug.h * TILE_CELLS - 2}"/>`;
      }
      if (r.dais) out += patch("dais", r.dais);
    }
    out += `</g>`;
  }

  // 2. LIGHT. A room is DARK, and its lamps carve pools out of the dark in four quantised bands
  //    on the tile grid. `data-lit` on the group is the engine's; it decides whether the lamps
  //    are on, and `data-voice` decides what colour they burn — the same status accent the rail
  //    prints the word in.
  for (const r of inside) {
    const pools = poolRuns(r, lampsFor(r), world.cols);
    const floor = litPath(r.floorRuns);
    // A head start of the room's own, so eight lit rooms breathe as a floor rather than as one
    // animation played eight times — the same reason every prop and every person carries one.
    out += `<g class="wp-rm wp-lit" data-room="${esc(r.id)}" data-kind="${esc(r.kind)}" data-lit="0" ` +
      `style="--d:-${(((hash(r.id) % 480) / 100)).toFixed(2)}s">`;
    for (let i = 0; i <= LEVELS; i++) {
      if (!pools[i].length) continue;
      out += `<path class="wp-pool" data-l="${i}" d="${litPath(pools[i])}"/>`;
    }
    out += `<path class="wp-shut" d="${floor}"/>`;
    out += `</g>`;
  }

  // A passage is lit whether or not anybody is in it — that is the difference between a corridor
  // and a room, and it is what gives the plan a bright spine to read the dark rooms against.
  {
    const spine: Room = { ...world.rooms[0], id: "__hall", kind: "hall", rects: [world.hall], floorRuns: [world.hall], props: [] };
    const pools = poolRuns(spine, lampsFor(spine), world.cols);
    out += `<g class="wp-rm wp-lit is-hall" data-room="__hall" data-kind="hall" data-lit="1">`;
    for (let i = 0; i <= LEVELS; i++) {
      if (!pools[i].length) continue;
      out += `<path class="wp-pool" data-l="${i}" d="${litPath(pools[i])}"/>`;
    }
    out += `</g>`;
  }

  // 3. SHADOW. One direction for the whole building, computed from the same grid a body walks on,
  //    so the party wall between two departments casts into both of them and the structural mass
  //    casts onto the corridor beside it.
  {
    const d = wallShadow(world);
    if (d) out += `<path class="wp-ao" d="${d}"/>`;
  }

  /* 3b. AND EVERY PROP'S OWN SHADE, for the WHOLE map, in one layer — see `propCasts`.
        Two groups, because a shadow is only as dark as the light it is subtracting: under a roof
        it comes off one lamp and is hard, out in the open it comes off the whole sky and is soft.
        The split is by what the shade LANDS on, so the yard's props go with the grounds — they
        were the odd case before, carrying a room's indoor ink onto grass because they happen to
        belong to a Room object.
        Each group is opaque inside and carries its alpha on the group, so overlaps union rather
        than stack; that is `opacity`, in the stylesheet, and it is the whole of the compounding
        fix. */
  {
    const roofed = world.rooms.filter((r) => !r.outdoor);
    const open = world.rooms.filter((r) => r.outdoor);
    const indoor = propCasts([...roofed.flatMap((r) => r.props), ...world.hallProps]);
    const outdoor = propCasts([...open.flatMap((r) => r.props), ...world.scenery]);
    if (indoor) out += `<g class="wp-shadow is-in">${indoor}</g>`;
    if (outdoor) out += `<g class="wp-shadow is-out">${outdoor}</g>`;
  }

  // 4. STRUCTURE, and everything standing on the floor. Bodies only: the shade they throw was
  //    laid in 3b, under everything, where the ground is.
  for (const r of world.rooms) {
    out += `<g class="wp-rm wp-bu${r.brain ? " is-brain" : ""}${r.open ? " is-open" : ""}" ` +
      `data-room="${esc(r.id)}" data-kind="${esc(r.kind)}">`;
    if (!r.outdoor && !r.open) {
      out += patches("wall", r.wallRuns);
      out += patches("face", r.faceRuns);
      for (const d of r.doors) {
        if (d.deep) out += at("doorCap", d.x, d.y) + at("doorWay", d.x, d.y + 1) + at("matt", d.x, d.y + 2);
        else out += at("doorWay", d.x, d.y) + at("matt", d.x, d.y - 1);
        out += at("doorLeaf", d.x, d.y + (d.deep ? 1 : 0), "wp-leaf");
      }
    }
    out += propBodies(r.props);
    out += `</g>`;
  }

  // Things standing in the passage and out in the grounds. Neither belongs to a room, so neither
  // is lit by one: a bench in a corridor is not evidence anybody is in a corridor.
  out += `<g class="wp-loose">`;
  out += propBodies([...world.hallProps, ...world.scenery]);
  out += `</g>`;

  // Last, over everything: the runner down the spine, from the gate to the dais. Drawn after the
  // rooms so it visibly crosses the chamber floor rather than stopping at its threshold.
  out += patch("runner", world.runner);
  out += at("doorWay", world.facadeX, world.gateY, "wp-gate");
  return out + `</svg>`;
}

/** Everything the simulation needs about the building, handed over as data rather than measured
 *  out of the DOM. A tile grid IS the geometry. */
function worldData(world: World): string {
  const solid = world.solid.map((s) => (s ? "1" : "0")).join("");
  const rooms = world.rooms.map((r) => ({
    i: r.id,
    x: r.x,
    y: r.y,
    w: r.w,
    h: r.h,
    o: r.outdoor ? 1 : 0,
    s: r.seats.map((p) => [p.x, p.y]),
  }));
  return (
    `<div class="wp-world" aria-hidden="true" data-cols="${world.cols}" data-rows="${world.rows}" ` +
    `data-tile="${TILE_PX}" data-gate="${world.facadeX},${world.gateY}" ` +
    `data-solid="${solid}" data-rooms="${esc(JSON.stringify(rooms))}"></div>`
  );
}

/** The room signs, beside the DOOR rather than in a corner — which is where a building actually
 *  signs a room, and which makes the door itself legible from down the hall. */
function plaques(world: World): string {
  return world.rooms
    .filter((r) => !!r.label)
    .map((r) => {
      // Inside the room, on its own wall, clamped to the room's own width. Two signs then cannot
      // collide however the plan is solved, which the version before this could not promise: it
      // hung every north room's sign in the hall at the same height and three landed on top of
      // each other — caught by the label-overlap guard, not by looking.
      const main = r.rects[0];
      const x = main.x + 1;
      const y = r.open ? main.y + 1 : main.y + 1;
      return (
        `<span class="wp-plaque" data-room="${esc(r.id)}" ` +
        `style="left:${x * TILE_PX}px;top:${y * TILE_PX - 11}px;--rw:${main.w - 2}">` +
        `${esc(r.label)}</span>`
      );
    })
    .join("");
}

/** THE SURVEY PANEL — the one corner that owns "where am I looking, and how far back".
 *
 *  The camera took the overview away and gave back a 96px plan you could click, which is where
 *  this went wrong: the plan was `aria-hidden`, it carried no label, no cursor story and no
 *  scale, and the SCALE ITSELF was not a control at all — it was derived from the panel width
 *  and clamped to whole numbers, so the smallest view possible was two thirds of the building.
 *  A reader could neither pull back nor tell that dragging was allowed. The gesture existed and
 *  the affordance did not, which is an ergonomic failure and not a missing feature.
 *
 *  So the plan becomes a survey sheet, and it carries the instruments a survey sheet carries:
 *
 *    the plan        rooms as shapes, a dot per person, a box for where you are looking —
 *                    click it or DRAG it to go there
 *    the scale rule  the zoom ladder drawn as what it is, a rule of ascending scale marks, with
 *                    the rung you are on lit and a cap at each end
 *    whole floor     the bottom of the ladder plus a centred frame: the whole company, once
 *    follow          the latch that says whether the camera is chasing the work or you are
 *                    holding it, because a camera that silently takes itself back is worse than
 *                    one that never moved
 *
 *  Rejected: a floating +/-/fit pill in the corner, which is what every map on the web ships and
 *  therefore what I would have drawn for any project at all; and putting the controls in the top
 *  strip, which re-adds the dashboard chrome the previous round deleted and splits "where am I
 *  looking" across two corners of the same frame.
 */
function survey(world: World): string {
  const body = world.rooms
    .filter((r) => !r.outdoor)
    .map((r) =>
      r.floorRuns.length
        ? `<path class="mm-r" data-room="${esc(r.id)}" d="${runPath(r.floorRuns)}"/>`
        : `<rect class="mm-r" data-room="${esc(r.id)}" x="${r.x * TILE_CELLS}" y="${r.y * TILE_CELLS}" ` +
          `width="${r.w * TILE_CELLS}" height="${r.h * TILE_CELLS}"/>`,
    )
    .join("");
  // Nine rungs, because a rung is a THIRD of a source pixel's width on screen and thirds are the
  // only ladder that stays pixel-exact BELOW one. Drawn as a rule of rising marks: the shape says
  // "scale" on sight, and the mark you are standing on is the one that is lit.
  const rungs = Array.from({ length: 9 }, (_, i) => i + 1)
    .map((n) => `<i data-rung="${n}" style="--h:${2 + n}px"></i>`)
    .join("");
  return (
    `<div class="wp-plan">` +
    `<div class="wp-mini" data-cols="${world.cols}" data-rows="${world.rows}" ` +
    `role="button" tabindex="0" aria-label="The plan — click or drag to look somewhere else" ` +
    `title="The plan — click or drag to look somewhere else">` +
    `<svg viewBox="0 0 ${world.cols * TILE_CELLS} ${world.rows * TILE_CELLS}" ` +
    `preserveAspectRatio="none" aria-hidden="true">` +
    `<rect class="mm-bg" x="0" y="0" width="${world.facadeX * TILE_CELLS}" height="${world.rows * TILE_CELLS}"/>` +
    body +
    `<rect class="mm-hall" x="${world.hall.x * TILE_CELLS}" y="${world.hall.y * TILE_CELLS}" ` +
    `width="${world.hall.w * TILE_CELLS}" height="${world.hall.h * TILE_CELLS}"/>` +
    `</svg><b class="wp-eye"></b><span class="wp-dots"></span></div>` +
    `<div class="wp-rule" data-step="3">` +
    `<button class="wp-cam wp-cam-step" data-cam="out" type="button" ` +
    `title="Pull back — mouse wheel, or the minus key" aria-label="Zoom out">&#8722;</button>` +
    `<span class="wp-rungs" role="group" aria-label="Scale">${rungs}</span>` +
    `<button class="wp-cam wp-cam-step" data-cam="in" type="button" ` +
    `title="Move in — mouse wheel, or the plus key" aria-label="Zoom in">+</button>` +
    `<b class="wp-read">1&#215;</b>` +
    `</div>` +
    `<button class="wp-cam wp-cam-wide" data-cam="whole" type="button" ` +
    `title="Frame the whole company — the 0 key, or double-click the floor" ` +
    `aria-label="Show the whole floor">${FIT_MARK}<span>WHOLE FLOOR</span></button>` +
    `<button class="wp-cam wp-cam-wide wp-cam-follow" data-cam="follow" type="button" ` +
    `title="Follow the work — the F key" aria-label="Follow the work" ` +
    `aria-pressed="true">${EYE_MARK}` +
    `<span class="wp-on">FOLLOWING</span><span class="wp-off">RESUME FOLLOW</span></button>` +
    `</div>`
  );
}

/** Two marks for the two latches, drawn rather than typed: a glyph font is the one thing in this
 *  document that cannot be relied on inside a webview, and both of these have to read at 11px. */
const FIT_MARK =
  `<svg class="wp-cam-mark" viewBox="0 0 12 12" aria-hidden="true">` +
  `<path d="M0 0h4v1.5H1.5V4H0zM8 0h4v4h-1.5V1.5H8zM0 8h1.5v2.5H4V12H0zM10.5 8H12v4H8v-1.5h2.5z"/>` +
  `<rect x="3.5" y="4" width="5" height="4.5"/></svg>`;
const EYE_MARK =
  `<svg class="wp-cam-mark" viewBox="0 0 12 12" aria-hidden="true">` +
  `<path d="M5.25 0h1.5v2.5h-1.5zM5.25 9.5h1.5V12h-1.5zM0 5.25h2.5v1.5H0zM9.5 5.25H12v1.5H9.5z"/>` +
  `<path d="M6 2.5A3.5 3.5 0 1 0 6 9.5 3.5 3.5 0 1 0 6 2.5zm0 1.5a2 2 0 1 1 0 4 2 2 0 0 1 0-4z"/>` +
  `</svg>`;

/* ── the people ──────────────────────────────────────────────────────────────────────────────*/

/** The pair a body RESTS in, chosen by what its state means it is doing.
 *
 *  Deliberately emitted under the same class the standing pair used to carry, so every rule that
 *  already animates a resting body — the two-frame swap on the beat, the walk swap, the lean —
 *  keeps working untouched. A posture is a different DRAWING, not a different mechanism.
 *
 *  Both seated pairs are fourteen rows against the standing figure's sixteen and every sprite is
 *  anchored at the boots, so sitting down drops the head six device pixels: the posture is legible
 *  before any of its detail is, which is the only test that matters at this size.
 */
const RESTING: Record<Posture, readonly Grid[]> = {
  stand: [POSE_REST, POSE_MOVE, POSE_BLINK],
  sit: [POSE_SIT_A, POSE_SIT_B, POSE_SIT_BLINK],
  slump: [POSE_SLUMP],
  lounge: [POSE_REST_A, POSE_REST_B, POSE_REST_BLINK],
};

/** The third frame of every waking pair is the BLINK — the lids down for a few frames every few
 *  seconds, staggered per person. The slump has no blink because its eyes are already shut, and
 *  the absence is what keeps a genuinely stopped body genuinely still. */
function spriteOf(w: Cast, posture: Posture): string {
  const pal = w.status === "foreign" ? VISITOR_PAL : SKIN_PAL;
  /* Three walks, one per facing the tile floor allows: the side gait (mirrored for west by the
     engine's face flip), the back going north, the front coming south. Which one shows is the
     engine's `data-dir`; the stylesheet holds the other two. The vertical gaits repeat their two
     frames across the four footfall phases so one `data-step` drives all three. */
  return (
    drawFrames(RESTING[posture], pal, { scale: 3, className: "wp-sprite wp-stand" }) +
    drawFrames([POSE_STRIDE_A, POSE_STRIDE_B, POSE_STRIDE_C, POSE_STRIDE_B], pal, {
      scale: 3, className: "wp-sprite wp-walk wp-walk-x",
    }) +
    drawFrames([POSE_WALK_A, POSE_WALK_B, POSE_WALK_A, POSE_WALK_B], pal, {
      scale: 3, className: "wp-sprite wp-walk wp-walk-s",
    }) +
    drawFrames([POSE_AWAY_A, POSE_AWAY_B, POSE_AWAY_A, POSE_AWAY_B], pal, {
      scale: 3, className: "wp-sprite wp-walk wp-walk-n",
    })
  );
}

/** What this one can DO, read off its own definition file.
 *
 *  Two failures were measured here and both are the same failure: six marks at twelve CSS pixels,
 *  which the whole-building fit then halved again, is not information — it is texture. So the row
 *  shows the THREE that distinguish this agent from the rest of the company, drawn twice the size,
 *  and the full set with its words arrives when a reader points at them. Rarity is the ranking
 *  because a capability everybody has says nothing about anybody. */
function faculties(w: Cast, rare: Map<string, number>): string {
  const list = (w.faculties ?? []).map((id) => MARK_OF.get(id)).filter(Boolean);
  if (!list.length) return "";
  const shown = [...list].sort((a, b) => (rare.get(a!.id) ?? 0) - (rare.get(b!.id) ?? 0)).slice(0, MARKS_SHOWN);
  const glyph = (id: string): string => {
    const art = FACULTY_ART[id];
    return art ? draw(art.grid, art.pal, { scale: 2, outline: false }) : "";
  };
  return (
    `<span class="wp-can">` +
    shown
      .map((f) => `<i class="wp-fac" data-fac="${esc(f!.id)}" title="${esc(f!.label)}">${glyph(f!.id)}</i>`)
      .join("") +

    `</span>` +
    `<span class="wp-kit">` +
    list.map((f) => `<i>${glyph(f!.id)}${esc(f!.label)}</i>`).join("") +
    `</span>`
  );
}

function actor(w: Cast, seat: Seat, home: Room, accent: string, brain: boolean, rare: Map<string, number>): string {
  const stalled = isHeld(w) ? 1 : 0;
  const how = behaviourOf(attentionOf(w));
  /* A state cannot conjure furniture. Where the place has nothing to sit on — the path outside
     the gate, an open plaza — a seated posture falls back to standing rather than putting a
     person cross-legged on a lawn. */
  const posture: Posture = seat.perch === false && how.posture !== "stand" ? "stand" : how.posture;
  const st = worldStampFor(w);
  /* A body at REST does not narrate its restfulness. A real registry is mostly finished runs, so
     letting the activity line speak here filled the cold open with a row of white bubbles all
     saying the done-word — the exact word the posture system exists to replace. The lounge on
     the couch IS the sentence; the full detail stays on the title for whoever asks. Working
     bodies keep their line: reading a file is news, being done is not.
     READY is the same non-event: the moment ready moved to the desks (post "desk") its caption
     re-appeared, and a floor of identical waiting-word bubbles is the done-word noise again in
     a new state. Standing at the station IS the sentence. */
  const resting = how.post === "rest" || attentionOf(w) === "ready";
  const say = !resting && w.activity ? clip(w.activity, 64) : "";
  const label =
    `${w.name} — ${w.status}, ${LABELS.get(w.zone) ?? w.zone}` + (w.activity ? `: ${w.activity}` : "");
  return (
    `<div class="wp-actor${brain ? " is-brain" : ""}" data-run-id="${esc(w.run_id)}" ` +
    `data-status="${esc(w.status)}" data-zone="${esc(w.zone)}" data-stalled="${stalled}" ` +
    // The state in the RAIL's words, so the room's light and the rail's stamp are one taxonomy
    // read by two renderers rather than two tables that happen to agree today.
    `data-attention="${esc(attentionOf(w))}" data-posture="${posture}" data-head="${HEAD[posture]}" ` +
    // Which way the body looks once it settles. Worth nothing at a desk and everything on a
    // bench: two people on one couch turned toward each other are sitting together.
    `data-face="${seat.face ?? 1}" ` +
    `data-seat="${seat.x},${seat.y}" data-say="${esc(say)}" data-home="${esc(home.id)}" ` +
    (seat.up ? `data-label="up" ` : "") +
    `data-dept="${esc(w.room || w.department || "")}" ` +
    // A head start of their own, so eleven people at their desks are eleven people rather than one
    // animation played eleven times. Measured: without it every sprite reported the same phase.
    `style="--accent:${accent};--idle:${idleAmount(w.idle_seconds)};--head:${HEAD[posture]}px;` +
    `--d:-${((hash(w.run_id) % 240) / 100).toFixed(2)}s;${faceOf(w.run_id)}" ` +
    `tabindex="0" role="button" title="${esc(label)}" aria-label="${esc(label)}">` +
    (st ? `<span class="wp-mark">${stampHtml(st)}</span>` : "") +
    (say ? `<span class="wp-say"><b>${esc(say)}</b></span>` : "") +
    `<span class="wp-shade"></span>` +
    /* The three presence pieces, hidden until the pointer earns them: the claim ring under the
       picked character, the wave when hovered, the startle when poked. In every actor rather than
       injected on demand, so the engine can grant them with a class and the sheet dedupes the
       art to one body each. */
    `<span class="wp-ring">${draw(RING.grid, RING.pal, { scale: 3, outline: false })}</span>` +
    `<span class="wp-body">${spriteOf(w, posture)}` +
    (stalled ? `<span class="wp-zzz">${draw(SNOOZE.grid, SNOOZE.pal, { scale: 2, outline: false })}</span>` : "") +
    `<span class="wp-hi">${drawFrames([WAVE_A, WAVE_B], WAVE_PAL, { scale: 2, className: "wp-wavehand" })}</span>` +
    `<span class="wp-bang">${draw(BANG.grid, BANG.pal, { scale: 3 })}</span>` +
    `</span>` +
    `<span class="wp-tag">${esc(clip(w.name, 16))}` +
    (w.idle_seconds >= 30 ? `<i>${esc(shortDuration(w.idle_seconds))}</i>` : "") +
    `</span>` +
    faculties(w, rare) +
    `</div>`
  );
}

/** Who stands where. Seats are handed out per room in a stable order so a person does not hop
 *  desks between two snapshots, and the agent that was asked first takes the seat at the core. */
export function seating(world: World, cast: Cast[], brainId: string | null): Map<string, Seat> {
  const out = new Map<string, Seat>();
  const byRoom = new Map<Room, Cast[]>();
  for (const w of cast) {
    const room = placeOf(world, w);
    const list = byRoom.get(room) ?? [];
    list.push(w);
    byRoom.set(room, list);
  }
  for (const [room, list] of byRoom) {
    list.sort((a, b) => {
      if (a.run_id === brainId) return -1;
      if (b.run_id === brainId) return 1;
      return hash(a.run_id) - hash(b.run_id);
    });
    /* THE STATE PICKS THE END OF THE ROOM, arrival order only picks the place within it. This is
       the whole difference between a floor you can read and sixteen interchangeable bodies: a
       department at its desks is working, and the same department on its couches has finished,
       from far enough back that no word on screen is legible at all.

       Seat CHANGES are how the transition happens, and they cost nothing here: the engine already
       treats a moved seat as "the roster moved them", so it routes the body across the room and
       walks it there. Nobody teleports into a chair. */
    const desks = room.seats.filter((s) => s.post !== "rest");
    /* Couches before standing room. Both are `post: "rest"`, but only a place with something to
       lie on can say FINISHED with a body — a lounger falls back to standing on a perchless
       spot, indistinguishable from ready, which is the one distinction the rest end exists to
       draw. Insertion order already puts the furniture first; stated here so no emitter's
       ordering is load-bearing. */
    const rests = [
      ...room.seats.filter((s) => s.post === "rest" && s.perch !== false),
      ...room.seats.filter((s) => s.post === "rest" && s.perch === false),
    ];
    /* ONE BODY PER COORDINATE — keyed by the COORDINATE, never by the seat object. Two distinct
       seat objects on one cell (two emitters drifting onto the same row) would each count as
       "free" to an identity Set, and the render is two nameplates over one visible body. */
    const used = new Set<string>();
    const handed: { x: number; y: number }[] = [];
    const at = (p: { x: number; y: number }): string => p.x + "," + p.y;
    const give = (seat: Seat): Seat => {
      used.add(at(seat));
      handed.push({ x: seat.x, y: seat.y });
      return seat;
    };
    /* OVERFLOW GROWS THE ROOM'S OWN SEAT SET; it never leaves the room and never doubles up.
       The old queue stepped BELOW the room — `room.y + room.h + ring * PITCH` — which is the
       hall for a north room, the neighbour for a stacked one, and the solid grounds for the
       yard: a coordinate space the building never agreed to, invisible to every invariant over
       `room.seats`, and (cross-room) not even injective. Overflow now scans the room's own
       walkable floor: first for a cell a full PITCH clear of everything already handed out,
       then — only if the room is genuinely that crowded — for any distinct cell at all. A room
       sized from its own headcount never reaches either pass; this is the net, not the plan. */
    const grow = (): Seat => {
      for (const minGap of [PITCH, 1]) {
        for (const r of room.rects) {
          for (let y = r.y + 1; y < r.y + r.h - 1; y++) {
            for (let x = r.x + 1; x < r.x + r.w - 1; x++) {
              if (world.solid[y * world.cols + x]) continue;
              if (used.has(x + "," + y)) continue;
              if (handed.some((p) => Math.abs(p.x - x) < minGap && Math.abs(p.y - y) < minGap)) continue;
              return { x, y, post: "rest", face: 1, perch: false };
            }
          }
        }
      }
      /* More bodies than the room has floor cells: nothing non-overlapping exists. Distinct
         coordinates stay guaranteed by walking rows below the room; unreachable for any world
         this builder produces, kept so the guarantee has no hole. */
      let y = room.y + room.h;
      let x = room.x + 1;
      while (used.has(x + "," + y)) {
        x += PITCH;
        if (x >= room.x + room.w) { x = room.x + 1; y += PITCH; }
      }
      return { x, y, post: "rest", face: 1, perch: false };
    };
    /* The state picks the END; past both ends the room grows a place rather than doubling one. */
    const take = (wants: "desk" | "rest"): Seat => {
      const order = wants === "rest" ? [rests, desks] : [desks, rests];
      for (const pool of order) {
        for (const seat of pool) if (!used.has(at(seat))) return give(seat);
      }
      return give(grow());
    };
    for (const w of list) {
      const seat = take(behaviourOf(attentionOf(w)).post);
      out.set(w.run_id, {
        x: seat.x,
        y: seat.y,
        up: seat.up,
        post: seat.post,
        face: seat.face,
        perch: seat.perch,
      });
    }
  }
  return out;
}

/** The agent that was asked first: the root of the tree, oldest where the registry knows. */
export function brainOf(workers: readonly Cast[]): string | null {
  const flagged = workers.find((w) => w.brain);
  if (flagged) return flagged.run_id;
  const roots = workers.filter((w) => !w.parent_run_id);
  if (!roots.length) return null;
  return [...roots].sort((a, b) => (a.started_at ?? 0) - (b.started_at ?? 0))[0].run_id;
}

/** Just the people — what a refresh actually sends. */
export function renderActors(state: TeamState): string {
  const cast = state.workers as Cast[];
  const pods = buildPods(state);
  const accents = assignAccents(pods.map((p) => p.lead.run_id));
  const accentOf = (w: Cast): string => {
    const pod = pods.find((p) => p.members.some((m) => m.worker.run_id === w.run_id));
    return (pod && accents.get(pod.lead.run_id)) || "var(--wp-h1)";
  };
  const world = worldFor(cast);
  const brain = brainOf(cast);
  const seats = seating(world, cast, brain);
  const rare = rarity(cast);
  const list: Post[] = posts(state);
  const mailbag = list.map((p) => ({
    f: p.from,
    t: p.to,
    k: p.key,
    x: clip(p.text, 80),
    g: p.age === null ? null : Math.round(p.age),
  }));
  return (
    `<div class="wp-cast" data-brain="${esc(brain ?? "")}" ` +
    `data-links="${esc(JSON.stringify(mailbag))}">` +
    cast
      .map((w) =>
        actor(
          w,
          seats.get(w.run_id) ?? { x: 2, y: 2 },
          placeOf(world, w),
          accentOf(w),
          w.run_id === brain,
          rare,
        ),
      )
      .join("") +
    `</div>`
  );
}

function money(total: number): string {
  if (!total) return "—";
  return total >= 1 ? `~$${total.toFixed(2)}` : `~$${total.toFixed(3)}`;
}

/** The board by the door, reduced to a strip laid OVER the world rather than a band beside it.
 *  The critic's word for the old one was that the eye is pulled to data rather than to place —
 *  so the counts that matter stay, the legend of every mark in the building is gone (the marks
 *  carry their own words on hover, and the stamps are already words), and the whole thing is one
 *  line thin enough that the floor is the biggest thing on screen at any panel width. */
function hud(state: TeamState, t: ReturnType<typeof tally>, mail: number): string {
  const when = new Date(atMillis(state.at)).toLocaleTimeString();
  const chip = (status: string, n: number, word: string, colour: string) =>
    n ? `<span class="wp-chip" style="--mark:${colour}">${markOf(status)}<b>${n}</b> ${word}</span>` : "";
  const projects = t.projects.length === 1 ? esc(t.projects[0]) : `${t.projects.length} projects`;
  return (
    `<header class="wp-hud">` +
    `<span class="wp-sign"><span class="wp-sign-name">The team</span>` +
    `<span class="wp-sign-sub">${projects}</span></span>` +
    chip("running", t.running, WORDS.running, "var(--wp-ok)") +
    chip("error", t.error, WORDS.error, "var(--wp-bad)") +
    chip("held", t.idle, WORDS.held, "var(--wp-dim)") +
    /* The other four chips read "11 on", "1 error", "1 held" — a number and a WORD. This one was
       a bare envelope and a number, so the only count on the strip nobody could name was the one
       whose glyph is smallest. It says what it counts. */
    (mail
      ? `<span class="wp-chip">${draw(NOTE.grid, NOTE.pal, { scale: 2 })}<b>${mail}</b> ` +
        `${mail === 1 ? "note" : "notes"}</span>`
      : "") +
    `<span class="wp-chip wp-spend">${money(t.cost)}</span>` +
    `<span class="wp-clock">${esc(when)}</span>` +
    `</header>`
  );
}

/** The whole visible thing: a viewport with a building inside it, a strip over the top and the
 *  plan in the corner. The map is inside so a harness or a first render gets a complete picture;
 *  a live refresh replaces only `.wp-cast`. */
export function renderScene(state: TeamState): string {
  openSheet();
  const WORLD = worldFor(state.workers as Cast[]);
  const t = tally(state);
  const list = posts(state);
  const body =
    `<div class="wp-view">` +
    `<div class="wp-stagebox" style="--cols:${WORLD.cols};--rows:${WORLD.rows};` +
    `--tile:${TILE_PX}px;width:${WORLD.cols * TILE_PX}px;height:${WORLD.rows * TILE_PX}px">` +
    renderMap(WORLD) +
    plaques(WORLD) +
    worldData(WORLD) +
    renderActors(state) +
    `</div>` +
    hud(state, t, list.length) +
    survey(WORLD) +
    `</div>`;
  return `<div class="wp">${closeSheet()}${body}</div>`;
}
