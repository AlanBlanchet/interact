/** The scene: a tile map, and the people standing on it.
 *
 *  Two layers, and the split is the point. The MAP is a pure function of the room table — it does
 *  not change when the team does — so it is rendered once and never re-sent. The ACTORS are the
 *  only thing a snapshot produces, which is a few hundred bytes rather than the whole building,
 *  and is what lets the panel push a new scene several times a second without the floor flickering.
 *
 *  Nothing here positions a person. An actor carries the SEAT it belongs to and nothing else; the
 *  simulation owns where a body actually is, walks it there, and may have it somewhere else
 *  entirely at the moment this markup lands. A renderer that placed people would be a slideshow
 *  again — that is exactly the bug this whole surface was rebuilt to remove.
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
import type { Dept, Room, Seat, World } from "./world";
import { assignAccents, atMillis, faceOf, hash, idleAmount, shortDuration } from "./palette";
import { STAMPS, WORDS, isHeld, markOf, stampFor, stampHtml } from "./status";
import { buildPods, posts, tally } from "./layout";
import type { Post } from "./layout";
import { clip, esc } from "./esc";

/** A worker may carry the faculties its own definition file grants it. Optional because the
 *  registry has not always written them, and a character with no declared powers must still
 *  render — as one with nothing shown, never as a crash. */
export type Cast = Worker & { faculties?: readonly string[] };

const LABELS = new Map<ZoneId, string>(ZONES.map((z) => [z.id, z.label]));
const MARK_OF = new Map(FACULTIES.map((f) => [f.id, f]));

/** The departments this team actually has, in a stable order, taken from the workers themselves.
 *  The building is a function of the company file — a department that exists gets a room, one that
 *  does not is not invented, and nobody is placed in a room their definition never named. */
export function deptsOf(workers: readonly Cast[]): Dept[] {
  const seen = new Map<string, string>();
  for (const w of workers) {
    if (!w.department) continue;
    if (!seen.has(w.department)) seen.set(w.department, w.room || w.department);
  }
  const heads = headcounts(workers);
  return [...seen]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([id, label]) => ({ id, label, heads: heads.get(id) ?? 0 }));
}

/** How many people each room has to hold. Rooms are SIZED from this — a department of six needs a
 *  wider room than a department of one, and a fixed room silently stacks the extra people on top
 *  of each other, which is what a full team looked like before. Counted here, before the building
 *  exists, because the building is a function of it. */
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

/** The building, kept between renders while the departments hold still. The tilemap is most of
 *  the document and none of it changes when a person moves, so rebuilding it per snapshot would
 *  be the single most expensive thing this file does. */
let cached: { key: string; world: World } | null = null;
export function worldFor(workers: readonly Cast[]): World {
  const depts = deptsOf(workers);
  const heads = headcounts(workers);
  const core = { brain: heads.get("__brain") ?? 0, lobby: heads.get("") ?? 0 };
  const key =
    depts.map((d) => d.id + ":" + d.label + ":" + d.heads).join("|") + "|" + core.brain + "/" + core.lobby;
  if (!cached || cached.key !== key) cached = { key, world: buildWorld(depts, core) };
  return cached.world;
}

/** Where a worker stands. Their DEPARTMENT is their room — that is the domain of work the
 *  company filed them under. The one exception is the web, which is genuinely outside: an agent
 *  fetching from the world walks out of the front gate to do it, and walks back in after. */
export function placeOf(world: World, w: Cast): Room {
  if (w.zone === "web") return world.yard;
  if (w.brain) return world.brainRoom;
  return (w.department && world.byId.get(w.department)) || world.lobby;
}

/* ── the map ─────────────────────────────────────────────────────────────────────────────────
   Ground goes down as PATTERN-filled rectangles — one element per region rather than one per
   cell, which is the difference between a 50 kB floor and a 2 kB one — and only the things that
   sit ON it are placed cell by cell. */

/** One tile, drawn at a cell. Scale 1 here: the whole map is one SVG whose user units are tile
 *  CELLS, and the pixel size arrives from the stylesheet, so a tile is authored once and the
 *  building can be zoomed without re-rendering anything. */
function at(id: TileId, x: number, y: number, cls = ""): string {
  const t = TILES[id];
  return draw(t.grid, t.pal, {
    scale: 1,
    outline: !!t.rim,
    className: cls || undefined,
    attrs: `x="${x * TILE_CELLS}" y="${y * TILE_CELLS}"`,
  });
}

function patch(id: TileId, x: number, y: number, w: number, h: number): string {
  return (
    `<rect x="${x * TILE_CELLS}" y="${y * TILE_CELLS}" ` +
    `width="${w * TILE_CELLS}" height="${h * TILE_CELLS}" fill="url(#wp-p-${id})"/>`
  );
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

/** The building, once. Every room is a group carrying its own zone, so the simulation can light
 *  it, stir it and name it without touching a single tile. */
function renderMap(world: World): string {
  const w = world.cols * TILE_CELLS;
  const h = world.rows * TILE_CELLS;
  let out =
    `<svg class="wp-map" width="${world.cols * TILE_PX}" height="${world.rows * TILE_PX}" ` +
    `viewBox="0 0 ${w} ${h}" shape-rendering="crispEdges" aria-hidden="true" focusable="false">` +
    `<defs>${patterns(["floor", "carpet", "dais", "grass", "wall", "path"])}</defs>`;

  // The ground: corridors first, then each room's own floor over the top of it.
  out += patch("floor", 0, 0, world.facadeX, world.rows);
  out += patch("grass", world.facadeX, 0, world.cols - world.facadeX, world.rows);

  for (const r of world.rooms) {
    const lit = r.outdoor ? "" : ` data-lit="0"`;
    out += `<g class="wp-rm${r.brain ? " is-brain" : ""}${r.open ? " is-open" : ""}" ` +
      `data-room="${esc(r.id)}"${lit}>`;
    if (r.outdoor) {
      out += patch("path", world.facadeX, world.gateY - 1, 3, 3);
    } else if (r.open) {
      out += patch(r.floor, r.x, r.y, r.w, r.h);
    } else {
      out += patch(r.floor, r.x + 1, r.y + 1, r.w - 2, r.h - 2);
      // The brain stands on a raised platform, not on a room-wide pattern: the dais is the thing
      // that makes the middle of the building read as the middle of it, and a lattice across the
      // whole floor stopped being a platform and became wallpaper.
      if (r.brain) out += patch("dais", r.x + 2, r.y + 2, 5, 2);
      // Walls as four runs, not as tiles: a rectangle filled with the wall pattern is one node.
      out += patch("wall", r.x, r.y, r.w, 1);
      out += patch("wall", r.x, r.y + r.h - 1, r.w, 1);
      out += patch("wall", r.x, r.y + 1, 1, r.h - 2);
      out += patch("wall", r.x + r.w - 1, r.y + 1, 1, r.h - 2);
      for (const win of r.windows) out += at("window", win.x, win.y);
      for (const d of r.doors) out += at(d.dir === "v" ? "doorV" : "doorH", d.x, d.y);
      // The light a room casts when somebody is in it. One rectangle, switched by a class — the
      // cheapest possible way to answer "where is everyone" before a single label is read.
      const bx = (r.x + 1) * TILE_CELLS;
      const by = (r.y + 1) * TILE_CELLS;
      const bw = (r.w - 2) * TILE_CELLS;
      const bh = (r.h - 2) * TILE_CELLS;
      out +=
        `<rect class="wp-glow" x="${bx}" y="${by}" width="${bw}" height="${bh}"/>` +
        `<rect class="wp-shut" x="${bx}" y="${by}" width="${bw}" height="${bh}"/>`;
    }
    for (const p of r.props) out += at(p.tile, p.x, p.y, p.tile === "core" ? "wp-core" : "");
    out += `</g>`;
  }

  // The exterior: the map's own border and the facade, with the gate punched through it.
  out += patch("wall", 0, 0, world.cols, 1);
  out += patch("wall", 0, world.rows - 1, world.cols, 1);
  out += patch("wall", 0, 1, 1, world.rows - 2);
  out += patch("wall", world.cols - 1, 1, 1, world.rows - 2);
  out += patch("wall", world.facadeX, 1, 1, world.rows - 2);
  out += at("doorV", world.facadeX, world.gateY, "wp-gate");
  return out + `</svg>`;
}

/** Everything the simulation needs about the building, handed over as data rather than measured
 *  out of the DOM. A tile grid IS the geometry — there is nothing to read off a bounding box —
 *  which is most of why the tilemap is worth having: routes are computed, not guessed from a
 *  layout that may have re-flowed since. */
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

/** The room signs, in HTML rather than in the SVG so they stay crisp text at any zoom. */
function plaques(world: World): string {
  return world.rooms
    .filter((r) => !!r.label)
    .map((r) => {
      const x = r.x + 1;
      const y = r.outdoor ? 1 : r.y + 1;
      return (
        `<span class="wp-plaque" data-room="${esc(r.id)}" ` +
        `style="left:${x * TILE_PX}px;top:${y * TILE_PX - 15}px">${esc(r.label)}` +
        `<b class="wp-head"></b></span>`
      );
    })
    .join("");
}

/* ── the people ──────────────────────────────────────────────────────────────────────────────
   An actor is a small stack: a sprite, a name, what it can do, and a line it may say. Sized so
   the whole thing is about a tile and a half wide — the moment the text out-masses the character,
   the map stops being a place and goes back to being a labelled diagram, which is the state this
   view was rejected in. */

function spriteOf(w: Cast): string {
  const pal = w.status === "foreign" ? GHOST_PAL : SKIN_PAL;
  // Four frames for anyone who can move: two of standing, two of walking. The simulation picks
  // which pair is showing, so one drawing serves the desk and the corridor.
  return (
    drawFrames([POSE_REST, POSE_MOVE], pal, { scale: 3, className: "wp-sprite wp-stand" }) +
    drawFrames([POSE_WALK_A, POSE_WALK_B], pal, { scale: 3, className: "wp-sprite wp-walk" })
  );
}

/** What this one can DO, read off its own definition file. Glyphs, not a tool list: a row of six
 *  marks under a character is readable at a glance and a list of `mcp__interact__*` is not. The
 *  simulation lights the matching mark while the character is doing that thing. */
function faculties(w: Cast): string {
  const list = (w.faculties ?? []).map((id) => MARK_OF.get(id)).filter(Boolean);
  if (!list.length) return "";
  return (
    `<span class="wp-can">` +
    list
      .map((f) => {
        const art = FACULTY_ART[f!.id];
        const body = art ? draw(art.grid, art.pal, { scale: 2, outline: false }) : esc(f!.mark);
        return `<i class="wp-fac" data-fac="${esc(f!.id)}" title="${esc(f!.label)}">${body}</i>`;
      })
      .join("") +
    `</span>`
  );
}

function actor(
  w: Cast,
  seat: Seat,
  home: Room,
  accent: string,
  brain: boolean,
): string {
  const stalled = isHeld(w) ? 1 : 0;
  const st = stampFor(w);
  const say = w.activity ? clip(w.activity, 72) : "";
  const label =
    `${w.name} — ${w.status}, ${LABELS.get(w.zone) ?? w.zone}` + (w.activity ? `: ${w.activity}` : "");
  return (
    `<div class="wp-actor${brain ? " is-brain" : ""}" data-run-id="${esc(w.run_id)}" ` +
    `data-status="${esc(w.status)}" data-zone="${esc(w.zone)}" data-stalled="${stalled}" ` +
    `data-seat="${seat.x},${seat.y}" data-say="${esc(say)}" data-home="${esc(home.id)}" ` +
    (seat.up ? `data-label="up" ` : "") +
    `data-dept="${esc(w.room || w.department || "")}" ` +
    `style="--accent:${accent};--idle:${idleAmount(w.idle_seconds)};${faceOf(w.run_id)}" ` +
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
    faculties(w) +
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
    // The brain first where it is standing in its own room; otherwise a stable hash order, so
    // seats do not reshuffle when somebody unrelated joins.
    list.sort((a, b) => {
      if (a.run_id === brainId) return -1;
      if (b.run_id === brainId) return 1;
      return hash(a.run_id) - hash(b.run_id);
    });
    list.forEach((w, i) => {
      const seat = room.seats[i % room.seats.length];
      // Past the seat count people stand a tile deeper rather than on top of each other.
      const wrap = Math.floor(i / room.seats.length);
      out.set(w.run_id, { x: seat.x, y: seat.y - (wrap % 2), up: seat.up });
    });
  }
  return out;
}

/** The agent that was asked first: the root of the tree, oldest where the registry knows. It is
 *  the one the whole building is arranged around, so it is worth finding honestly rather than
 *  taking whoever happens to be first in an array. */
export function brainOf(workers: readonly Cast[]): string | null {
  // The roster says so outright where the company file has been read; otherwise fall back to the
  // shape of the tree — the earliest root — so a team whose records predate the flag still has a
  // middle rather than none.
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

function hud(state: TeamState, t: ReturnType<typeof tally>, mail: number): string {
  const when = new Date(atMillis(state.at)).toLocaleTimeString();
  const chip = (status: string, n: number, word: string, colour: string) =>
    n ? `<span class="wp-chip" style="--mark:${colour}">${markOf(status)}<b>${n}</b> ${word}</span>` : "";
  const projects = t.projects.length === 1 ? esc(t.projects[0]) : `${t.projects.length} projects`;
  return (
    `<header class="wp-hud">` +
    `<span class="wp-sign"><span class="wp-sign-name">The team</span>` +
    `<span class="wp-sign-sub">${projects}</span></span>` +
    `<span class="wp-tally">` +
    chip("running", t.running, WORDS.running, "var(--wp-ok)") +
    chip("error", t.error, WORDS.error, "var(--wp-bad)") +
    chip("done", t.done, WORDS.done, "var(--wp-dim)") +
    chip("foreign", t.foreign, WORDS.foreign, "var(--wp-dim)") +
    chip("held", t.idle, WORDS.held, "var(--wp-dim)") +
    (mail ? `<span class="wp-chip">${draw(NOTE.grid, NOTE.pal, { scale: 2 })}<b>${mail}</b> said</span>` : "") +
    `<span class="wp-chip">spend <b>${money(t.cost)}</b></span>` +
    `</span>` +
    `<span class="wp-clock">as of ${esc(when)}</span>` +
    `</header>`
  );
}

function legend(): string {
  return (
    `<footer class="wp-legend">` +
    `<span class="wp-key" style="--mark:var(--wp-ok)">${markOf("running")} ${WORDS.running}</span>` +
    `<span class="wp-key">${stampHtml(STAMPS.error)}</span>` +
    `<span class="wp-key">${stampHtml(STAMPS.held)}</span>` +
    `<span class="wp-key">${stampHtml(STAMPS.done)}</span>` +
    `<span class="wp-key">${stampHtml(STAMPS.foreign)}</span>` +
    `<span class="wp-facs">` +
    FACULTIES.map((f) => {
      const art = FACULTY_ART[f.id];
      const body = art ? draw(art.grid, art.pal, { scale: 2, outline: false }) : esc(f.mark);
      return `<i class="wp-fac">${body}</i>${esc(f.label)}`;
    }).join("") +
    `</span>` +
    `</footer>`
  );
}

/** The whole visible thing. The map is inside it so a harness or a first render gets a complete
 *  picture; a live refresh replaces only `.wp-cast`. */
export function renderScene(state: TeamState): string {
  openSheet();
  const WORLD = worldFor(state.workers as Cast[]);
  const t = tally(state);
  const list = posts(state);
  const body =
    hud(state, t, list.length) +
    `<div class="wp-view">` +
    `<div class="wp-stagebox" style="--cols:${WORLD.cols};--rows:${WORLD.rows};` +
    `--tile:${TILE_PX}px;width:${WORLD.cols * TILE_PX}px;height:${WORLD.rows * TILE_PX}px">` +
    renderMap(WORLD) +
    plaques(WORLD) +
    worldData(WORLD) +
    renderActors(state) +
    `</div></div>` +
    legend();
  return `<div class="wp">${closeSheet()}${body}</div>`;
}

