/** The PLAN: a building with a spine, not a partition of a rectangle.
 *
 *  The version this replaces solved the floor by cutting one square into a 3x3 grid and giving
 *  each department a cell. Every room therefore came out the same size, the same shape and the
 *  same way up, corridors were whatever was left over, and the whole thing read — correctly — as
 *  a floor plan with pixel art painted on it. No amount of nicer tiles fixes that, because the
 *  defect is in the GENERATOR: a partition function can only ever produce a partition.
 *
 *  So the building is now composed the way a building is:
 *
 *   - a HALL runs through it, from the front gate to the chamber at its head. It has its own
 *     ground and a runner down the middle, so a passage looks nothing like the places it joins.
 *   - rooms BUD off the hall, north and south, sharing party walls. Each one is as WIDE as its
 *     headcount and as DEEP as its trade, so the band has a ragged back and the building has a
 *     silhouette. Where a shallow room leaves space behind it, that space is either the building's
 *     structural mass or an ALCOVE the room keeps for itself — which is where the L-shaped rooms
 *     come from, and where the one-of-a-kind things stand.
 *   - the wall a room FACES is two tiles: the cap you look down on and the face you look at.
 *     A one-tile band on all four sides is a border; a wall with a visible face is a wall, and it
 *     is the single cheapest thing that makes a room stop being a rectangle.
 *   - the CHAMBER at the head of the hall is not a room at all: no walls, a colonnade, a raised
 *     dais. Every route to the west half crosses it, which is the org chart drawn as architecture.
 *
 *  What a room CONTAINS comes from what its people can actually DO. A department whose members
 *  mostly run commands gets a machine room; one whose members only read gets the stacks. The
 *  faculties are read off each agent's own definition file, ranked by how much they distinguish
 *  that department from the rest of the company, and the top one picks the archetype. Nothing is
 *  keyed to a department NAME, so a company file with different departments furnishes itself.
 */
import type { TileId } from "./tiles";

/* ── the measure ─────────────────────────────────────────────────────────────────────────────
   Every number here is in TILES. A bay is one back-wall prop, one desk under it and two standing
   places three tiles apart — which is what a 36px character with a name over it actually needs. */

export const BAY = 3;
export const MIN_BAYS = 2;
/** The hall, and the runner down the middle of it. */
export const HALL_H = 3;
/** How far the outdoors reaches past the facade. */
const OUT = 7;
/** The chamber at the head of the building, before it is widened for a crowd. */
const CHAMBER_W = 9;
/** The lobby inside the front gate. */
const LOBBY_W = 8;
/** Grounds around the building. The world has to be bigger than the level in BOTH axes or the
 *  camera runs out of somewhere to go: a tall narrow side bar letterboxes the plan and puts the
 *  black bars back, which is the defect the camera exists to remove. */
const MX = 4;
const MY = 6;

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Dept {
  id: string;
  /** The room name as the company file words it — "Wealth Desk", not "wealth". */
  label: string;
  /** How many people are in it right now. A room bulges where the work is. */
  heads?: number;
  /** The faculties its people declare, most DISTINGUISHING first. The first one this file knows
   *  an archetype for decides what kind of room it is. Ranked by the caller, which is the only
   *  place that can see the whole company and therefore what counts as distinguishing. */
  kit?: readonly string[];
}

export interface Seat {
  x: number;
  y: number;
  /** Wear your name ABOVE your head rather than under your feet: a rank standing three tiles in
   *  front of another otherwise has its head in the back rank's labels, and depth ordering draws
   *  the front body over them — the wrong person hiding the right person's name. */
  up?: boolean;
}

export interface Door {
  x: number;
  y: number;
  /** A door through a two-tile wall is two cells: the opening seen from above and the frame you
   *  walk through. Passing a body through both is visibly going THROUGH a wall. */
  deep: boolean;
}

/** Something drawn standing on a cell. `live` asks the renderer for an ambient overlay — a screen
 *  that flickers, a kettle that steams, a fan that turns — which is a separate node so the tile
 *  underneath is never redrawn to make it move. */
export type LiveId = "screen" | "steam" | "fan" | "lamp" | "sway";
export interface Prop {
  x: number;
  y: number;
  tile: TileId;
  live?: LiveId;
}

export interface Room {
  /** The department id, `""` for the lobby, `__brain`, `__web`, or an open-floor marker. */
  id: string;
  label: string;
  /** Which archetype furnished it — the stylesheet tints a machine room colder than a library. */
  kind: string;
  /** The footprint, one or two rectangles. Two is an L: a room with an alcove behind it. */
  rects: Rect[];
  /** Bounding box of the footprint. */
  x: number;
  y: number;
  w: number;
  h: number;
  brain: boolean;
  outdoor: boolean;
  lobby: boolean;
  /** No walls and no door: a part of the floor rather than a room. */
  open: boolean;
  doors: Door[];
  props: Prop[];
  seats: Seat[];
  floor: TileId;
  /** Horizontal runs, worked out here so the renderer emits rectangles and never walks cells. */
  floorRuns: Rect[];
  wallRuns: Rect[];
  faceRuns: Rect[];
  /** A raised platform under the middle of the room, drawn as ground rather than as furniture. */
  dais?: Rect;
  /** A change of ground in the middle of the floor. Blocks nothing. */
  rug?: Rect;
}

export interface World {
  cols: number;
  rows: number;
  rooms: Room[];
  byId: Map<string, Room>;
  /** cols*rows, true where a body may NOT stand. Doors are always false. */
  solid: boolean[];
  facadeX: number;
  gateY: number;
  brainRoom: Room;
  lobby: Room;
  yard: Room;
  /** The spine, for the renderer: its ground, and the runner down the middle of it. */
  hall: Rect;
  runner: Rect;
  /** The building's structural mass — everything inside the envelope that is neither room nor
   *  passage. Drawn as solid wall, which is what gives the plan weight. */
  mass: Rect[];
  /** The building itself, inside the grounds. */
  envelope: Rect;
  /** Things standing in the passage, and things standing outside the building. */
  hallProps: Prop[];
  scenery: Prop[];
}

function hash32(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/* ── what a department DOES ──────────────────────────────────────────────────────────────────
   One archetype per faculty. The lists are four long and indexed by bay PLUS the room's own hash,
   so two bays in a row are different things and two rooms of the same trade are furnished in a
   different order — the "plant, monitor, plant" that repeated identically three times per row was
   a single list read from zero in every room. */

interface Archetype {
  kind: string;
  /** Interior rows. Six is the floor: two ranks of people need three rows between them. */
  depth: number;
  /** Against the back wall, one per bay. */
  back: TileId[];
  /** On the wall face above it. */
  face: TileId[];
  /** The working surface in front of the back wall. */
  desk: TileId;
  floor: TileId;
  /** The one thing this trade has that no other does. Placed once, in the alcove where there is
   *  one and beside the door where there is not. */
  feature: TileId;
}

const ARCHETYPES: Record<string, Archetype> = {
  reads: {
    kind: "stacks",
    depth: 7,
    back: ["stacks", "stacks", "ladder", "cabinet"],
    face: ["pinboard", "winFace", "poster", "clock"],
    desk: "desk",
    floor: "carpet",
    feature: "globe",
  },
  writes: {
    kind: "drafting",
    depth: 6,
    back: ["cabinet", "shelf", "crates", "cabinet"],
    face: ["winFace", "pinboard", "poster", "winFace"],
    desk: "drafting",
    floor: "carpet",
    feature: "printer",
  },
  runs: {
    kind: "machine",
    depth: 6,
    back: ["rack", "rack", "crates", "rack"],
    face: ["pipes", "vent", "screenWall", "pipes"],
    desk: "desk",
    floor: "floor",
    feature: "printer",
  },
  sees: {
    kind: "gallery",
    depth: 6,
    back: ["screen", "board", "screen", "shelf"],
    face: ["screenWall", "clock", "screenWall", "winFace"],
    desk: "desk",
    floor: "carpet",
    feature: "tank",
  },
  searches: {
    kind: "signals",
    depth: 7,
    back: ["dish", "globe", "board", "rack"],
    face: ["winFace", "poster", "pinboard", "winFace"],
    desk: "desk",
    floor: "floor",
    feature: "dish",
  },
  delegates: {
    kind: "boardroom",
    depth: 6,
    back: ["board", "cabinet", "board", "shelf"],
    face: ["whiteboard", "clock", "whiteboard", "poster"],
    desk: "desk",
    floor: "carpet",
    feature: "tableM",
  },
};

const COMMONS: Archetype = {
  kind: "commons",
  depth: 6,
  back: ["sofa", "plant", "urn", "sofa"],
  face: ["poster", "winFace", "clock", "pinboard"],
  desk: "bench",
  floor: "carpet",
  feature: "coffee",
};

/** The plants and screens the stylesheet is asked to animate. Kept here so a prop cannot acquire
 *  ambient motion by accident: a tile is alive because the plan said so. */
const LIVE_OF: Partial<Record<TileId, LiveId>> = {
  plant: "sway",
  screen: "screen",
  rack: "screen",
  board: "screen",
  screenWall: "screen",
  coffee: "steam",
  desk: "screen",
  lamp: "lamp",
  tank: "screen",
};

/** Things there is only ONE of in a building. A room asks for one and gets it if nobody already
 *  took it — which is the whole mechanism against "decorative filler repeats identically three
 *  times per row": the second room that wants a coffee machine does not get one. */
const ONCE: TileId[] = ["coffee", "tank", "vending", "cooler", "fan", "globe", "ladder", "printer", "dish"];

class Uniques {
  private taken = new Set<string>();
  claim(tile: TileId): boolean {
    if (!ONCE.includes(tile)) return true;
    if (this.taken.has(tile)) return false;
    this.taken.add(tile);
    return true;
  }
  /** The best still-unclaimed thing from a wish list, in order. */
  pick(wish: readonly TileId[]): TileId | null {
    for (const t of wish) if (this.claim(t)) return t;
    return null;
  }
}

/* ── from rectangles to walls ────────────────────────────────────────────────────────────────
   The footprint is one or two rectangles; everything else is derived. A cell inside the footprint
   whose eight neighbours are all inside is floor; anything else inside is wall. Then every wall
   run with floor directly BELOW it is thickened by one and that second row is its FACE — which is
   what turns a plan into a room you are looking into. L-shapes fall out for free: the derivation
   never knew the footprint was a rectangle in the first place. */

interface Shape {
  wall: Set<number>;
  face: Set<number>;
  floor: Set<number>;
  box: Rect;
}

function shapeOf(rects: readonly Rect[], stride: number): Shape {
  const x0 = Math.min(...rects.map((r) => r.x));
  const y0 = Math.min(...rects.map((r) => r.y));
  const x1 = Math.max(...rects.map((r) => r.x + r.w));
  const y1 = Math.max(...rects.map((r) => r.y + r.h));
  const inside = (x: number, y: number): boolean =>
    rects.some((r) => x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h);
  const core = (x: number, y: number): boolean => {
    if (!inside(x, y)) return false;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) if (!inside(x + dx, y + dy)) return false;
    return true;
  };
  const wall = new Set<number>();
  const face = new Set<number>();
  const floor = new Set<number>();
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      if (!inside(x, y)) continue;
      (core(x, y) ? floor : wall).add(y * stride + x);
    }
  }
  // The second row of every wall that has floor under it. Done after the first pass so the pass
  // itself is not reading a set it is still writing.
  for (const key of [...wall]) {
    const x = key % stride;
    const y = (key - x) / stride;
    const below = (y + 1) * stride + x;
    if (!floor.has(below)) continue;
    floor.delete(below);
    wall.add(below);
    face.add(below);
  }
  return { wall, face, floor, box: { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } };
}

/** Horizontal runs of a cell set, as rectangles. One patch per run instead of one node per cell:
 *  a forty-by-thirty building is about two hundred elements rather than twelve hundred. */
function runsOf(cells: Set<number>, box: Rect, stride: number): Rect[] {
  const out: Rect[] = [];
  for (let y = box.y; y < box.y + box.h; y++) {
    let x = box.x;
    while (x < box.x + box.w) {
      if (!cells.has(y * stride + x)) {
        x++;
        continue;
      }
      let run = 1;
      while (cells.has(y * stride + x + run)) run++;
      out.push({ x, y, w: run, h: 1 });
      x += run;
    }
  }
  return out;
}

/* ── furnishing ──────────────────────────────────────────────────────────────────────────────
   The skeleton is the same in every trade — things against the back wall, a working surface in
   front of them, two ranks of standing room — and everything ON that skeleton comes from the
   archetype and the room's own hash. That is deliberate: a place is legible because its shape is
   familiar and its contents are not. */

function furnish(
  room: Room,
  arch: Archetype,
  bays: number,
  uniques: Uniques,
  seed: number,
): void {
  const main = room.rects[0];
  // A recess deep enough to stand something in. The plan forms also emit a WING — two or three
  // rows, most of it wall — and treating that as an alcove put the room's one-of-a-kind prop
  // inside the masonry, outside every room, on the building's own mass.
  const wing = room.rects[1] ?? null;
  const alcove = wing && wing.h >= 4 ? wing : null;
  const ix = main.x + 1; /* first interior column */
  const iy = main.y + 2; /* first interior row, under the wall face */
  const D = main.h - 3; /* interior rows */
  const put = (x: number, y: number, tile: TileId): void => {
    room.props.push({ x, y, tile, live: LIVE_OF[tile] });
  };

  for (let i = 0; i < bays; i++) {
    const cx = ix + i * BAY + 1;
    put(cx, iy, arch.back[(i + seed) % arch.back.length]);
    // Every OTHER desk gets a lit screen. All of them would be forty animations in one room and
    // a wall of blinking; every other one reads as a floor where some people are at their machine.
    room.props.push({
      x: cx,
      y: iy + 1,
      tile: arch.desk,
      live: (i + seed) % 2 === 0 ? LIVE_OF[arch.desk] : undefined,
    });
  }

  // Two ranks, three rows apart at the very least. The back rank wears its name the other way up.
  for (let i = 0; i < bays; i++) room.seats.push({ x: ix + i * BAY + 1, y: iy + 2, up: true });
  for (let i = 0; i < bays; i++) room.seats.push({ x: ix + i * BAY + 1, y: iy + D - 1 });

  // The face: a fixture over every second bay, offset by the room's hash so no two rooms carry
  // the same things in the same order.
  const faceY = main.y + 1;
  for (let i = 0; i < bays; i++) {
    if ((i + seed) % 2 === 1 && bays > 2) continue;
    room.props.push({
      x: ix + i * BAY + 1,
      y: faceY,
      tile: arch.face[(i + seed + 1) % arch.face.length],
      live: LIVE_OF[arch.face[(i + seed + 1) % arch.face.length]],
    });
  }
  // One wall lamp, always on the face, always off-centre.
  room.props.push({ x: ix + ((seed % Math.max(1, bays)) * BAY), y: faceY, tile: "lamp", live: "lamp" });

  // The floor between the desks and the door. Left bare it is the "vast empty carpet" that made
  // every room read as a rectangle with props glued to one edge; it is where the things a room
  // accumulates go. Never on a standing place, and the list is walked from the room's own hash so
  // no two rooms accumulate the same things in the same order.
  const clutter: TileId[] = ["chair", "crates", "plant", "bench", "cabinet", "sofa", "urn", "chair", "printer"];
  // What a chair may NEVER stand on. Every standing place AND its four neighbours, so a body
  // always has somewhere to step and somebody can always come and stand beside it; and the two
  // cells inside every door, because a crate there seals the department. Both were found by the
  // building's own invariants — a seat inside the masonry and a room nothing could path into —
  // never by looking at it.
  const forbidden = new Set<string>();
  for (const p of room.seats) {
    forbidden.add(p.x + ":" + p.y);
    forbidden.add(p.x + 1 + ":" + p.y);
    forbidden.add(p.x - 1 + ":" + p.y);
    forbidden.add(p.x + ":" + (p.y + 1));
    forbidden.add(p.x + ":" + (p.y - 1));
  }
  for (const d of room.doors) {
    for (let k = -3; k <= 3; k++) forbidden.add(d.x + ":" + (d.y + k));
    for (let k = -1; k <= 1; k++) forbidden.add(d.x + k + ":" + (d.y + (d.deep ? 2 : -2)));
  }
  let c = seed;
  for (let row = iy + 3; row < iy + D; row++) {
    for (let i = 0; i < bays; i++) {
      c++;
      if ((c * 7 + row * 3) % 4) continue;
      const cx = ix + i * BAY + (c % 3);
      if (forbidden.has(cx + ":" + row)) continue;
      put(cx, row, clutter[c % clutter.length]);
    }
  }
  // And a rug under the middle of it, which is ground rather than furniture: a room whose whole
  // interior is one colour is waiting space, not a room.
  if (main.w >= 8 && D >= 6) {
    room.rug = { x: ix + 1, y: iy + 3, w: main.w - 4, h: Math.min(3, D - 4) };
  }

  // The one-of-a-kind thing. It stands in the alcove where the room has one — which is exactly
  // what an alcove is for — and otherwise just inside the door.
  const wish: TileId[] = [arch.feature, "cooler", "vending", "crates", "cabinet"];
  const only = uniques.pick(wish) ?? "crates";
  if (alcove) {
    const ax = alcove.x + Math.floor(alcove.w / 2);
    const ay = alcove.y + 2;
    put(ax, ay, only);
    // "boxes" was in this list, cast to TileId, and there is no such tile. The cast is what let it
    // through the type system, and the room shapes this list is walked for never happened to reach
    // it until the plan forms changed — so the whole map threw on an undefined grid. A tile id that
    // needs a cast to compile is an id that does not exist.
    const mate = uniques.pick(["fan", "coffee", "printer", "cabinet", "crates"]) ?? "crates";
    put(ax + 1, ay + 1, mate);
  } else {
    put(ix + (bays - 1) * BAY + 1, iy + D - 3, only);
  }
}

/** An open piece of floor: no walls, no door, and furniture that is there to be sat on rather
 *  than worked at. Every part of the building the departments do not fill becomes one, so a small
 *  company gets a building with a plaza in it rather than a blank quadrant. */
function loosen(room: Room, uniques: Uniques, seed: number): void {
  const b = room.rects[0];
  const put = (x: number, y: number, tile: TileId): void => {
    room.props.push({ x, y, tile, live: LIVE_OF[tile] });
  };
  const wish: TileId[] = ["coffee", "cooler", "tank", "vending", "plant"];
  const kit: TileId[] = ["sofa", "plant", "bench", "urn", "crates"];
  let n = 0;
  for (let y = b.y + 1; y < b.y + b.h - 1; y += 3) {
    for (let x = b.x + 2; x < b.x + b.w - 2; x += 4) {
      n++;
      if (n === 2) {
        const only = uniques.pick(wish);
        if (only) {
          put(x, y, only);
          continue;
        }
      }
      put(x, y, kit[(n + seed) % kit.length]);
    }
  }
  for (let y = b.y + 2; y < b.y + b.h - 2; y += 3) {
    for (let x = b.x + 3; x < b.x + b.w - 2; x += 3) {
      room.seats.push({ x, y, up: y === b.y + 2 });
    }
  }
}

/* ── the building ────────────────────────────────────────────────────────────────────────────*/

const baysOf = (heads: number): number => Math.max(MIN_BAYS, Math.ceil(heads / 2));
/** The archetype for one department, given the ones already handed out. A department takes the
 *  trade its people most distinguish themselves by; if the room next door already IS that, it
 *  takes the next one down its own list. Two identical rooms is the repetition defect one level
 *  up from the furniture, and it is the level a reader notices first. */
const archOf = (kit: readonly string[] | undefined, taken: Set<string>): Archetype => {
  for (const f of kit ?? []) {
    const a = ARCHETYPES[f];
    if (a && !taken.has(a.kind)) return a;
  }
  for (const f of kit ?? []) if (ARCHETYPES[f]) return ARCHETYPES[f];
  return COMMONS;
};

interface Slot {
  dept: Dept;
  arch: Archetype;
  bays: number;
  w: number;
  h: number;
}

function slotFor(dept: Dept, taken: Set<string>): Slot {
  const arch = archOf(dept.kit, taken);
  taken.add(arch.kind);
  const bays = baysOf(dept.heads ?? 0);
  return { dept, arch, bays, w: BAY * bays + 2, h: arch.depth + 3 };
}

function blank(id: string, label: string, rects: Rect[], over: Partial<Room> = {}): Room {
  const x = Math.min(...rects.map((r) => r.x));
  const y = Math.min(...rects.map((r) => r.y));
  const w = Math.max(...rects.map((r) => r.x + r.w)) - x;
  const h = Math.max(...rects.map((r) => r.y + r.h)) - y;
  return {
    id,
    label,
    kind: "room",
    rects,
    x,
    y,
    w,
    h,
    brain: false,
    outdoor: false,
    lobby: false,
    open: false,
    doors: [],
    props: [],
    seats: [],
    floor: "carpet",
    floorRuns: [],
    wallRuns: [],
    faceRuns: [],
    ...over,
  };
}

/** The whole building, solved from a department list. Pure and deterministic: the same
 *  departments give byte-identical output, which is what lets the map be rendered once and never
 *  re-sent when somebody walks. */
export function buildWorld(
  depts: readonly Dept[],
  core: { brain?: number; lobby?: number } = {},
): World {
  const uniques = new Uniques();

  // Alternate the departments between the two bands in declaration order, so the first ones
  // declared face each other across the hall rather than filling one side first.
  const kinds = new Set<string>();
  const slots = depts.map((d) => slotFor(d, kinds));
  const north: Slot[] = [];
  const south: Slot[] = [];
  slots.forEach((s, i) => (i % 2 === 0 ? north : south).push(s));

  const bandW = (band: Slot[]): number => band.reduce((n, s) => n + s.w - 1, 1);
  const bandH = (band: Slot[]): number => Math.max(9, ...band.map((s) => s.h));

  const chamberW = Math.max(CHAMBER_W, BAY * baysOf(core.brain ?? 0) + 4);
  const NB = bandH(north);
  const SB = bandH(south);
  const wallY = MY; /* the building's own top wall, with grounds above it */
  const hallY = wallY + 1 + NB;
  const floorY = hallY + HALL_H + SB; /* its bottom wall */
  const rows = floorY + 1 + MY;
  const bandStart = MX + 1 + chamberW;
  const bandSpan = Math.max(14, bandW(north), bandW(south));
  const lobbyX = bandStart + bandSpan;
  const facadeX = lobbyX + LOBBY_W;
  const cols = facadeX + 1 + OUT;
  const gateY = hallY + 1;

  const rooms: Room[] = [];

  /** THE PLAN FORM of one room, and the reason the building has a silhouette.
   *
   *  Every room used to be a rectangle. Sized differently, furnished differently, lit differently
   *  — and still eight rectangles in two rows, which is what a floor PLAN looks like and not what
   *  a place looks like. A rectangle has nothing to stand behind, no corner to turn, and no wall
   *  that runs out and comes back, so nothing in it can ever be tucked away.
   *
   *  Three forms, chosen by the department's own hash so a company file draws the same building
   *  every time. All three keep the HALL-FACING edge at full width, because that edge carries the
   *  door and the sign, and a door on a stepped wall is a door nobody can find.
   *
   *   - BAR      a plain rectangle. Small rooms stay rectangles; an L in four tiles is a corridor.
   *   - ELL/TEE  the room is set back from the outer wall and one WING pushes out to it. At an end
   *              that is an L; in the middle it is a T. The step is what the eye reads.
   *   - ALCOVE   where there is spare depth behind the room, it keeps it as a recess — which is
   *              where `furnish` already puts the one-of-a-kind thing in each trade.
   */
  const plan = (x: number, y: number, w: number, h: number, side: "n" | "s", spare: number, seed: number): Rect[] => {
    const north = side === "n";
    // Deep enough behind it to keep a recess: that reads better than a step, so it wins.
    if (spare >= 3 && w >= 8) {
      const aw = Math.min(6, w - 3);
      const ax = x + 1 + (seed % Math.max(1, w - aw - 1));
      return [
        { x, y, w, h },
        north ? { x: ax, y: y - spare, w: aw, h: spare + 2 } : { x: ax, y: y + h - 2, w: aw, h: spare + 2 },
      ];
    }
    // Too small to step without becoming a corridor. Measured against the rooms this actually
    // produces: at a floor of six tiles a three-tile wing still leaves three, which reads as a
    // step; the first guard I wrote asked for nine and left four rooms out of five rectangular.
    if (w < 7 || h < 5) return [{ x, y, w, h }];
    const ww = 3 + ((seed >>> 3) % Math.max(1, w - 6));
    // End or middle. Two thirds of rooms take an end, so the band reads as steps rather than as a
    // row of identical castles.
    const where = (seed >>> 11) % 3;
    const wx = where === 0 ? x : where === 1 ? x + w - ww : x + Math.floor((w - ww) / 2);
    // The wing pushes OUT into whatever depth is left rather than being carved out of the room:
    // the first version set the whole room back two rows and gave one strip of it back, which
    // stepped the silhouette correctly and cost every department a fifth of its floor. Where
    // there is genuinely nothing behind, the room gives up ONE row for the step.
    const out = Math.min(2, spare);
    const back = out > 0 ? 0 : 1;
    const deep = out > 0 ? out + 1 : 2;
    return north
      ? [
          { x, y: y + back, w, h: h - back },
          { x: wx, y: y + back - deep + 1, w: ww, h: deep },
        ]
      : [
          { x, y, w, h: h - back },
          { x: wx, y: y + h - back - 1, w: ww, h: deep },
        ];
  };

  /** One band of rooms, budding off the hall. They share party walls: the next room starts on the
   *  previous one's wall, which is what stops a row of rooms reading as a row of boxes. */
  const layBand = (band: Slot[], side: "n" | "s"): void => {
    const avail = side === "n" ? NB : SB;
    let x = bandStart;
    for (const s of band) {
      const y = side === "n" ? hallY - s.h : hallY + HALL_H;
      const seed = hash32(s.dept.id) >>> 0;
      const rects: Rect[] = plan(x, y, s.w, s.h, side, avail - s.h, seed);
      const room = blank(s.dept.id, s.dept.label, rects, {
        kind: s.arch.kind,
        floor: s.arch.floor,
      });
      // The door is on the wall that faces the hall: shallow on a north room (you look over its
      // low south wall), two cells deep on a south room (you walk through the face).
      // UNSIGNED shift. The hash is a uint32, so a signed >> turns it negative above 2^31, the
      // modulus comes out negative, and the door is placed to the LEFT of its own room — which is
      // what happened: one department's door landed three tiles inside its neighbour and nothing
      // could path into it. Invisible on screen (it looked like a door), caught by the invariant
      // that every room must be reachable from every other.
      const doorX = x + 1 + ((seed >>> 5) % Math.max(1, s.w - 3));
      room.doors.push(
        side === "n" ? { x: doorX, y: y + s.h - 1, deep: false } : { x: doorX, y, deep: true },
      );
      furnish(room, s.arch, s.bays, uniques, seed % 4);
      rooms.push(room);
      x += s.w - 1;
    }
    // Whatever the shorter band does not use is open floor, not corridor: a plaza with seats in
    // it, which is also where anybody the company filed under no department can stand.
    const rest = bandStart + bandSpan - x;
    if (rest >= 6) {
      const y = side === "n" ? wallY + 1 : hallY + HALL_H;
      const room = blank("__open" + side, "", [{ x, y, w: rest, h: avail }], {
        open: true,
        kind: "plaza",
        floor: "floor",
      });
      loosen(room, uniques, side === "n" ? 1 : 3);
      rooms.push(room);
    }
  };

  // The chamber at the head of the hall. Not a room: no walls, a colonnade and a raised dais, so
  // the one place everybody's routes cross is the one place that is not four walls and a door.
  const capH = Math.min(floorY - wallY - 1, HALL_H + 2 * (4 + baysOf(core.brain ?? 0)));
  const capY = Math.max(wallY + 1, Math.round(hallY + HALL_H / 2 - capH / 2));
  const chamber = blank("__brain", "The Brain", [{ x: MX + 1, y: capY, w: chamberW, h: capH }], {
    brain: true,
    open: true,
    kind: "chamber",
    floor: "floor",
  });
  {
    const cx = MX + 1 + Math.floor(chamberW / 2);
    const cy = Math.floor((wallY + floorY) / 2);
    const top = capY;
    const bot = capY + capH - 1;
    chamber.props.push({ x: cx, y: cy - 2, tile: "core", live: "screen" });
    // A colonnade down both sides, every third row, so the chamber is HELD UP rather than shut
    // in — the one space in the plan that is not four walls and a door.
    for (let y = top + 2; y < bot - 1; y += 3) {
      chamber.props.push({ x: MX + 2, y, tile: "pillar" });
      chamber.props.push({ x: MX + chamberW - 1, y, tile: "pillar" });
    }
    chamber.props.push({ x: cx - 3, y: cy - 5, tile: "plant", live: "sway" });
    chamber.props.push({ x: cx + 3, y: cy - 5, tile: "plant", live: "sway" });
    chamber.props.push({ x: cx - 3, y: cy + 4, tile: "bench" });
    chamber.props.push({ x: cx + 3, y: cy + 4, tile: "bench" });
    chamber.props.push({ x: cx - 3, y: top + 1, tile: "board", live: "screen" });
    chamber.props.push({ x: cx + 3, y: bot - 1, tile: "crates" });
    const bays = baysOf(core.brain ?? 0);
    const lo = MX + 3;
    const hi = MX + chamberW - 2;
    const fits = (x: number): boolean => x >= lo && x <= hi;
    chamber.seats.push({ x: cx, y: cy, up: true });
    for (let i = 1; i < bays + 1; i++) {
      if (fits(cx - i * BAY)) chamber.seats.push({ x: cx - i * BAY, y: cy, up: true });
      if (fits(cx + i * BAY)) chamber.seats.push({ x: cx + i * BAY, y: cy });
    }
    for (let i = 0; i < bays + 1; i++) {
      const x = cx - BAY + i * BAY;
      if (fits(x)) chamber.seats.push({ x, y: cy + 3 });
    }
    chamber.dais = { x: cx - 2, y: cy - 3, w: 5, h: 3 };
  }
  rooms.push(chamber);

  layBand(north, "n");
  layBand(south, "s");

  // The front desk, inside the gate. Open like the chamber, because a lobby with a door on it is
  // not a lobby.
  const lobH = Math.min(floorY - wallY - 1, HALL_H + 2 * (4 + baysOf(core.lobby ?? 0)));
  const lobY = Math.max(wallY + 1, Math.round(hallY + HALL_H / 2 - lobH / 2));
  const lobby = blank("", "Front desk", [{ x: lobbyX, y: lobY, w: LOBBY_W, h: lobH }], {
    lobby: true,
    open: true,
    kind: "lobby",
    floor: "floor",
  });
  {
    const lx = lobbyX + 1;
    lobby.props.push({ x: lx + 1, y: gateY - 4, tile: "plant", live: "sway" });
    lobby.props.push({ x: lx + 4, y: gateY - 4, tile: "sofa" });
    lobby.props.push({ x: lx + 1, y: gateY + 4, tile: "sofa" });
    lobby.props.push({ x: lx + 4, y: gateY + 4, tile: "plant", live: "sway" });
    const only = uniques.pick(["cooler", "vending", "coffee", "tank"]);
    if (only) lobby.props.push({ x: lx + 5, y: gateY - 2, tile: only, live: LIVE_OF[only] });
    lobby.props.push({ x: lx, y: lobY + 1, tile: "board", live: "screen" });
    lobby.props.push({ x: lx + 5, y: lobY + lobH - 2, tile: "plant", live: "sway" });
    const bays = baysOf(core.lobby ?? 0);
    for (let i = 0; i < bays; i++) lobby.seats.push({ x: lx + 1, y: gateY - 2 + i * 3, up: i === 0 });
    for (let i = 0; i < bays; i++) lobby.seats.push({ x: lx + 4, y: gateY - 2 + i * 3 });
  }
  rooms.push(lobby);

  // Outdoors. Not a room and no walls: you get there by walking out of the gate, which is the
  // only reason the gate exists.
  const yardSeats: Seat[] = [];
  for (const dy of [0, 3, -3, 6, -6]) {
    for (let dx = 2; dx < OUT; dx += 3) yardSeats.push({ x: facadeX + dx, y: gateY + dy, up: dx === 2 });
  }
  const yard = blank("__web", "Out on the web", [{ x: facadeX + 1, y: wallY, w: OUT, h: floorY - wallY + 1 }], {
    outdoor: true,
    open: true,
    kind: "outside",
    floor: "grass",
    seats: yardSeats,
    props: [
      { x: facadeX + 4, y: wallY + 2, tile: "mast" },
      { x: facadeX + 3, y: floorY - 3, tile: "plant", live: "sway" },
      { x: facadeX + 5, y: floorY - 6, tile: "plant", live: "sway" },
    ],
  });
  rooms.push(yard);

  /* ── the walkability grid ────────────────────────────────────────────────────────────────
     Solid by default INSIDE the envelope: the building is mass until something carves a space
     out of it, which is the opposite of the old plan (empty until something drew a wall) and is
     why a shallow room now leaves visible structure behind it rather than a blank corridor. */
  const solid = new Array<boolean>(cols * rows).fill(true);
  const carve = (r: Rect): void => {
    for (let y = r.y; y < r.y + r.h; y++) {
      for (let x = r.x; x < r.x + r.w; x++) {
        if (x < 0 || y < 0 || x >= cols || y >= rows) continue;
        solid[y * cols + x] = false;
      }
    }
  };
  const block = (x: number, y: number): void => {
    if (x < 0 || y < 0 || x >= cols || y >= rows) return;
    solid[y * cols + x] = true;
  };

  const hall: Rect = { x: bandStart - 1, y: hallY, w: lobbyX - bandStart + 2, h: HALL_H };
  const hallProps: Prop[] = [];
  const scenery: Prop[] = [];
  /* The runner runs the WHOLE spine, from the front gate to the dais at the head of the chamber,
     and is drawn over the rooms rather than under them — a corridor that stops at the chamber
     door is a corridor that leads nowhere. */
  const runnerRect: Rect = { x: MX + 1 + Math.floor(chamberW / 2), y: hallY + 1, w: facadeX - (MX + 1 + Math.floor(chamberW / 2)), h: 1 };
  const envelope: Rect = { x: MX, y: wallY, w: facadeX - MX + 1, h: floorY - wallY + 1 };
  const runner: Rect = runnerRect;
  carve(hall);

  // Things standing IN the passage. A corridor with nothing in it is a gap between rooms. Never
  // in a door's own column: the door cell's only way out is the hall row directly under it, so a
  // prop there walls a whole department in.
  {
    const blocked = new Set<number>();
    for (const r of rooms) for (const d of r.doors) for (let k = -1; k <= 1; k++) blocked.add(d.x + k);
    const kit: TileId[] = ["bench", "plant", "crates", "cabinet", "cooler", "printer"];
    let n = 0;
    for (let x = hall.x + 3; x < hall.x + hall.w - 3; x += 5) {
      if (blocked.has(x)) continue;
      const tile = uniques.pick([kit[n % kit.length], "bench", "plant"]) ?? "plant";
      hallProps.push({ x, y: n % 2 === 0 ? hallY : hallY + HALL_H - 1, tile, live: LIVE_OF[tile] });
      n++;
    }
  }

  // Every room's own shape, and the same pass that hands the renderer its rectangles.
  for (const room of rooms) {
    if (room.open) {
      carve(room.rects[0]);
      room.floorRuns = [{ ...room.rects[0] }];
      for (const p of room.props) block(p.x, p.y);
      continue;
    }
    const shape = shapeOf(room.rects, cols);
    for (const key of shape.floor) solid[key] = false;
    for (const key of shape.wall) solid[key] = true;
    for (const d of room.doors) {
      solid[d.y * cols + d.x] = false;
      shape.wall.delete(d.y * cols + d.x);
      shape.face.delete(d.y * cols + d.x);
      if (d.deep) {
        solid[(d.y + 1) * cols + d.x] = false;
        shape.wall.delete((d.y + 1) * cols + d.x);
        shape.face.delete((d.y + 1) * cols + d.x);
      }
    }
    room.floorRuns = runsOf(shape.floor, shape.box, cols);
    room.faceRuns = runsOf(shape.face, shape.box, cols);
    const body = new Set([...shape.wall].filter((k) => !shape.face.has(k)));
    room.wallRuns = runsOf(body, shape.box, cols);

    /* A STANDING PLACE OUTRANKS A PROP, and it is enforced here rather than hoped for in the
       furnisher.
       `furnish` lays out desks, seats and clutter against the room's first rectangle on a fixed
       inset, which is exactly right while every room IS that rectangle. The moment a plan form
       steps the wall, some of those cells are masonry or are already carrying a crate — and a
       body standing inside a wall is invisible until an invariant goes looking for it (this one
       did: three seats, three departments, no visible symptom). So: anything standing on a seat
       is removed, and a seat that is not floor walks to the nearest cell that is. */
    const seatAt = new Set(room.seats.map((p) => p.x + ":" + p.y));
    room.props = room.props.filter((p) => !seatAt.has(p.x + ":" + p.y));
    const propAt = new Set(room.props.map((p) => p.x + ":" + p.y));
    const taken = new Set<string>();
    for (const seat of room.seats) {
      const free = (x: number, y: number): boolean =>
        shape.floor.has(y * cols + x) && !propAt.has(x + ":" + y) && !taken.has(x + ":" + y);
      if (!free(seat.x, seat.y)) {
        let best: [number, number] | null = null;
        let near = Infinity;
        for (const key of shape.floor) {
          const x = key % cols;
          const y = (key - x) / cols;
          if (!free(x, y)) continue;
          const d = Math.abs(x - seat.x) + Math.abs(y - seat.y);
          if (d < near) { near = d; best = [x, y]; }
        }
        if (best) { seat.x = best[0]; seat.y = best[1]; }
      }
      taken.add(seat.x + ":" + seat.y);
    }

    // Furniture is solid: the moment a route has to bend around a desk the floor stops being a
    // backdrop and becomes a place with things in it. A prop on the wall FACE is already solid.
    for (const p of room.props) block(p.x, p.y);
  }

  // The envelope, the grounds outside it, and the gate through the facade. Everything beyond the
  // building is solid: it is scenery the camera can rest on, never floor anybody walks.
  for (let x = 0; x < cols; x++) {
    for (let y = 0; y < rows; y++) {
      if (y < envelope.y || y >= envelope.y + envelope.h || x < envelope.x) block(x, y);
    }
  }
  for (let x = envelope.x; x <= facadeX; x++) {
    block(x, envelope.y);
    block(x, envelope.y + envelope.h - 1);
  }
  for (let y = envelope.y; y < envelope.y + envelope.h; y++) {
    block(envelope.x, y);
    block(facadeX, y);
  }
  carve({ x: facadeX + 1, y: envelope.y, w: OUT, h: envelope.h });
  solid[gateY * cols + facadeX] = false;

  // What is left solid inside the envelope, as rectangles, so the renderer can draw the building's
  // mass rather than leaving a hole where a shallow room did not reach the outside wall.
  const massCells = new Set<number>();
  for (let y = envelope.y; y < envelope.y + envelope.h; y++) {
    for (let x = envelope.x; x < facadeX; x++) if (solid[y * cols + x]) massCells.add(y * cols + x);
  }
  for (const room of rooms) {
    for (const r of [...room.wallRuns, ...room.faceRuns]) {
      for (let x = r.x; x < r.x + r.w; x++) massCells.delete(r.y * cols + x);
    }
    for (const p of room.props) massCells.delete(p.y * cols + p.x);
  }
  const mass = runsOf(massCells, envelope, cols);

  for (const p of hallProps) block(p.x, p.y);

  // Trees and shrubs in the grounds. Deterministic, thinned near the gate so the way in stays
  // clear, and never on the building — scenery the camera can rest on rather than a green margin.
  for (let y = 1; y < rows - 1; y += 2) {
    for (let x = 1; x < cols - 1; x += 3) {
      if (x >= envelope.x - 1 && x <= facadeX + OUT && y >= envelope.y - 1 && y <= envelope.y + envelope.h) continue;
      const seed = hash32(x + ":" + y);
      if (seed % 5) continue;
      scenery.push({ x, y, tile: seed % 3 === 0 ? "plant" : "urn", live: seed % 3 === 0 ? "sway" : undefined });
    }
  }

  const byId = new Map(rooms.map((r) => [r.id, r]));
  return {
    cols,
    rows,
    rooms,
    byId,
    solid,
    facadeX,
    gateY,
    brainRoom: chamber,
    lobby,
    yard,
    hall,
    runner,
    mass,
    envelope,
    hallProps,
    scenery,
  };
}
