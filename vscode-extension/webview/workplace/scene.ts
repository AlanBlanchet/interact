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
import { closeSheet, draw, drawFrames, openSheet } from "./pixels";
import {
  FACULTY_ART,
  GHOST_PAL,
  NOTE,
  POSE_MOVE,
  POSE_REST,
  POSE_WALK_A,
  POSE_WALK_B,
  SKIN_PAL,
  SNOOZE,
} from "./art";
import { TILES, TILE_CELLS, TILE_PX } from "./tiles";
import type { TileId } from "./tiles";
import { buildWorld } from "./world";
import type { Dept, Prop, Rect, Room, Seat, World } from "./world";
import { assignAccents, atMillis, faceOf, hash, idleAmount, shortDuration } from "./palette";
import { WORDS, isHeld, markOf, stampFor, stampHtml } from "./status";
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
    if (w.zone === "web") continue; /* out of the building, standing in the yard */
    if (w.brain) add("__brain");
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
  const core = { brain: heads.get("__brain") ?? 0, lobby: heads.get("") ?? 0 };
  const key =
    depts.map((d) => d.id + ":" + d.label + ":" + d.heads + ":" + (d.kit ?? []).join(",")).join("|") +
    "|" +
    core.brain +
    "/" +
    core.lobby;
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
  return draw(t.grid, t.pal, {
    scale: 1,
    outline: !!t.rim,
    className: cls || undefined,
    attrs: `x="${x * TILE_CELLS}" y="${y * TILE_CELLS}"` + (extra ? " " + extra : ""),
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

function propHtml(p: Prop): string {
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
    `<defs>${patterns(["floor", "carpet", "grass", "wall", "path", "lino", "runner", "face", "mass", "dais", "rug"])}</defs>`;

  // The envelope, then everything carved out of it. Mass first: the building is solid until a
  // room or a passage takes a bite out of it, which is what gives a shallow room something
  // BEHIND it instead of a blank corridor.
  out += patch("grass", { x: 0, y: 0, w: world.cols, h: world.rows });
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

  for (const r of world.rooms) {
    const lit = r.outdoor || r.open ? "" : ` data-lit="0"`;
    out +=
      `<g class="wp-rm${r.brain ? " is-brain" : ""}${r.open ? " is-open" : ""}" ` +
      `data-room="${esc(r.id)}" data-kind="${esc(r.kind)}"${lit}>`;
    if (r.outdoor) {
      out += patch("path", { x: world.facadeX, y: world.gateY - 1, w: 4, h: 3 });
    } else if (r.open) {
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
      out += patches("wall", r.wallRuns);
      out += patches("face", r.faceRuns);
      for (const d of r.doors) {
        if (d.deep) out += at("doorCap", d.x, d.y) + at("doorWay", d.x, d.y + 1) + at("matt", d.x, d.y + 2);
        else out += at("doorWay", d.x, d.y) + at("matt", d.x, d.y - 1);
        out += at("doorLeaf", d.x, d.y + (d.deep ? 1 : 0), "wp-leaf");
      }
      if (!r.open) {
        // The light a room casts when somebody is in it, and the veil over it when nobody is.
        // Both follow the room's actual floor, so an L-shaped room is lit as an L.
        const d = runPath(r.floorRuns);
        out += `<path class="wp-glow" d="${d}"/><path class="wp-shut" d="${d}"/>`;
      }
    }
    for (const p of r.props) out += propHtml(p);
    out += `</g>`;
  }

  // Things standing in the passage and out in the grounds. Neither belongs to a room, so neither
  // is lit by one: a bench in a corridor is not evidence anybody is in a corridor.
  out += `<g class="wp-loose">`;
  for (const p of world.hallProps) out += propHtml(p);
  for (const p of world.scenery) out += propHtml(p);
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
        `style="left:${x * TILE_PX}px;top:${y * TILE_PX - 11}px;` +
        `max-width:${(main.w - 2) * TILE_PX}px">${esc(r.label)}</span>`
      );
    })
    .join("");
}

/** The whole building at a glance, in the corner. The camera takes the overview away, so this
 *  gives it back in the one form that costs no space: room shapes, and a dot per person in their
 *  pod's colour. The engine draws the dots and the box showing where you are looking. */
function minimap(world: World): string {
  const body = world.rooms
    .filter((r) => !r.outdoor)
    .map((r) =>
      r.floorRuns.length
        ? `<path class="mm-r" data-room="${esc(r.id)}" d="${runPath(r.floorRuns)}"/>`
        : `<rect class="mm-r" data-room="${esc(r.id)}" x="${r.x * TILE_CELLS}" y="${r.y * TILE_CELLS}" ` +
          `width="${r.w * TILE_CELLS}" height="${r.h * TILE_CELLS}"/>`,
    )
    .join("");
  return (
    `<div class="wp-mini" aria-hidden="true" data-cols="${world.cols}" data-rows="${world.rows}">` +
    `<svg viewBox="0 0 ${world.cols * TILE_CELLS} ${world.rows * TILE_CELLS}" preserveAspectRatio="none">` +
    `<rect class="mm-bg" x="0" y="0" width="${world.facadeX * TILE_CELLS}" height="${world.rows * TILE_CELLS}"/>` +
    body +
    `<rect class="mm-hall" x="${world.hall.x * TILE_CELLS}" y="${world.hall.y * TILE_CELLS}" ` +
    `width="${world.hall.w * TILE_CELLS}" height="${world.hall.h * TILE_CELLS}"/>` +
    `</svg><b class="wp-eye"></b><span class="wp-dots"></span></div>`
  );
}

/* ── the people ──────────────────────────────────────────────────────────────────────────────*/

function spriteOf(w: Cast): string {
  const pal = w.status === "foreign" ? GHOST_PAL : SKIN_PAL;
  return (
    drawFrames([POSE_REST, POSE_MOVE], pal, { scale: 3, className: "wp-sprite wp-stand" }) +
    drawFrames([POSE_WALK_A, POSE_WALK_B], pal, { scale: 3, className: "wp-sprite wp-walk" })
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
  const st = stampFor(w);
  const say = w.activity ? clip(w.activity, 64) : "";
  const label =
    `${w.name} — ${w.status}, ${LABELS.get(w.zone) ?? w.zone}` + (w.activity ? `: ${w.activity}` : "");
  return (
    `<div class="wp-actor${brain ? " is-brain" : ""}" data-run-id="${esc(w.run_id)}" ` +
    `data-status="${esc(w.status)}" data-zone="${esc(w.zone)}" data-stalled="${stalled}" ` +
    `data-seat="${seat.x},${seat.y}" data-say="${esc(say)}" data-home="${esc(home.id)}" ` +
    (seat.up ? `data-label="up" ` : "") +
    `data-dept="${esc(w.room || w.department || "")}" ` +
    // A head start of their own, so eleven people at their desks are eleven people rather than one
    // animation played eleven times. Measured: without it every sprite reported the same phase.
    `style="--accent:${accent};--idle:${idleAmount(w.idle_seconds)};` +
    `--d:-${((hash(w.run_id) % 240) / 100).toFixed(2)}s;${faceOf(w.run_id)}" ` +
    `tabindex="0" role="button" title="${esc(label)}" aria-label="${esc(label)}">` +
    (st ? `<span class="wp-mark">${stampHtml(st)}</span>` : "") +
    (say ? `<span class="wp-say"><b>${esc(say)}</b></span>` : "") +
    `<span class="wp-shade"></span>` +
    `<span class="wp-body">${spriteOf(w)}` +
    (stalled ? `<span class="wp-zzz">${draw(SNOOZE.grid, SNOOZE.pal, { scale: 2, outline: false })}</span>` : "") +
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
function seating(world: World, cast: Cast[], brainId: string | null): Map<string, Seat> {
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
    list.forEach((w, i) => {
      const seat = room.seats[i % Math.max(1, room.seats.length)] ?? { x: room.x + 2, y: room.y + 3 };
      const wrap = Math.floor(i / Math.max(1, room.seats.length));
      out.set(w.run_id, { x: seat.x, y: seat.y - (wrap % 2), up: seat.up });
    });
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
    (mail ? `<span class="wp-chip">${draw(NOTE.grid, NOTE.pal, { scale: 2 })}<b>${mail}</b></span>` : "") +
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
    minimap(WORLD) +
    `</div>`;
  return `<div class="wp">${closeSheet()}${body}</div>`;
}
