/** The MAP: a floor plan on a tile grid, solved from the company's own departments.
 *
 *  A room is not a `<div>` here. It is a rectangle of tiles with a wall run around it, doors in
 *  the wall, furniture standing on specific cells and a set of SEATS — the cells a person stands
 *  on. Everything the simulation needs is a consequence of that: which cells are solid, where the
 *  doors are, and which seat is free.
 *
 *  The plan is DATA, and the data is the company file. "Finance would be elsewhere" is not a
 *  special case to code: the Wealth Desk is a department, so it is a room, and it is a room in the
 *  same way Quality & Critics is. Nothing here is hand-placed and no zone is hard-coded — hand
 *  `buildWorld` a different set of departments and you get a different building.
 *
 *  The middle cell is the BRAIN: the agent that was asked first, that the others report to. Every
 *  route between two rooms passes its door, which is the plan saying what the org chart says
 *  without anybody having to draw an org chart.
 */
import type { TileId } from "./tiles";

/* ── the block ───────────────────────────────────────────────────────────────────────────────
   Rooms on a square grid with corridors between them, an exterior wall, and the outdoors past the
   front gate. Every number here is in TILES; nothing in this file knows about pixels. */

/** A room is measured in BAYS. One bay is a back-wall prop, a desk under it, and two standing
 *  places — one at the desk and one a rank forward. Three tiles wide and three tiles between
 *  ranks, because that is what a 36px character with a name under it actually needs: at two tiles
 *  the desks fitted and the PEOPLE did not, and six critics in one room drew on top of each other.
 *  A room is therefore sized to its HEADCOUNT, not to a constant. */
export const BAY = 3;
export const MIN_BAYS = 3;
export const RH = 8;
export const widthFor = (bays: number): number => BAY * bays;
const GAP = 2; /* the corridor between two rooms */
const OUT = 6; /* how far the outdoors reaches past the facade */

export interface Dept {
  id: string;
  /** The room name as the company file words it — "Wealth Desk", not "wealth". */
  label: string;
  /** How many people are in it right now. The building bulges where the work is: a department of
   *  six gets a wider room than one of one, which is the honest thing for a floor plan to do and
   *  the only way a full team fits without stacking. */
  heads?: number;
}

export interface Seat {
  x: number;
  y: number;
  /** Wear your name ABOVE your head rather than under your feet.
   *
   *  A character is 54px tall and its nameplate and faculty row add another 24 under its boots,
   *  so a rank standing three tiles (72px) in front of another has its HEAD in the back rank's
   *  labels — and depth ordering draws the front body over them, so the wrong person's head hides
   *  the right person's name. Rather than space the ranks four tiles apart (which costs a whole
   *  storey of height), the back rank simply wears its label the other way up: over the desk it
   *  is standing at, where nothing else is. */
  up?: boolean;
}

export interface Door {
  x: number;
  y: number;
  dir: "h" | "v";
}

export interface Room {
  /** The department id, `""` for the lobby, or the outdoor marker. */
  id: string;
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
  brain: boolean;
  outdoor: boolean;
  lobby: boolean;
  /** No walls and no door: an open part of the floor rather than a room. Every cell the company
   *  does not fill becomes one, so a small team gets a building with a plaza in it instead of a
   *  quadrant of blank corridor. */
  open: boolean;
  doors: Door[];
  props: { x: number; y: number; tile: TileId }[];
  windows: { x: number; y: number }[];
  /** Standing room, handed out in this order: the desk seats first, then the open floor. */
  seats: Seat[];
  floor: TileId;
}

export interface World {
  cols: number;
  rows: number;
  grid: number;
  rooms: Room[];
  byId: Map<string, Room>;
  /** cols*rows, true where a body may NOT stand. Doors are always false. */
  solid: boolean[];
  facadeX: number;
  gateY: number;
  brainRoom: Room;
  lobby: Room;
  yard: Room;
}

/** The kit a room is furnished with. Cycled per room so five departments do not look like five
 *  copies of one room, and keyed off the department's own id so a given department always gets
 *  the same furniture — a room you recognise is a room you can navigate. */
const KITS: TileId[][] = [
  ["shelf", "board", "shelf", "plant"],
  ["rack", "rack", "board", "rack"],
  ["bench", "rack", "bench", "plant"],
  ["board", "shelf", "board", "shelf"],
  ["urn", "shelf", "plant", "board"],
];

function hash32(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** One room, furnished. The kit repeats across four bays along the back wall, the desks sit one
 *  row in front of it, and every remaining interior cell is standing room — which is what makes a
 *  crowded room look crowded rather than overflow into a scrollbar. */
function furnish(
  id: string,
  label: string,
  x: number,
  y: number,
  bays: number,
  opts: { brain?: boolean; lobby?: boolean; open?: boolean; edge: { left: boolean; top: boolean } },
): Room {
  const RW = widthFor(bays);
  /* Where each bay's furniture and its two standing places sit. */
  const at = (i: number): number => 1 + i * BAY;
  const props: Room["props"] = [];
  const seats: Seat[] = [];
  const windows: { x: number; y: number }[] = [];
  const kit = KITS[hash32(id) % KITS.length];

  const mid = Math.floor(bays / 2);
  if (opts.open) {
    // An open bay: seating, greenery and nothing to shut. People cross it, and somebody with no
    // department of their own can stand in it without the building pretending they have a desk.
    for (let i = 0; i < bays; i++) {
      props.push({ x: x + at(i), y: y + 1, tile: i === mid ? "urn" : "plant" });
      props.push({ x: x + at(i) + 1, y: y + 4, tile: i === mid ? "bench" : "sofa" });
    }
    for (const dy of [3, 6]) {
      for (let i = 0; i < bays; i++) seats.push({ x: x + at(i), y: y + dy, up: dy === 3 });
    }
  } else if (opts.brain) {
    // The core stands in the middle of its own room, and the closest standing place in the
    // building is the one right in front of it — which is where the agent that was asked first
    // ends up. A clear row between the two, so the core is never hidden behind its own owner.
    props.push({ x: x + at(mid), y: y + 1, tile: "core" });
    for (let i = 0; i < bays; i++) if (i !== mid) props.push({ x: x + at(i), y: y + 1, tile: "rack" });
    seats.push({ x: x + at(mid), y: y + 3, up: true });
    for (let i = 0; i < bays; i++) if (i !== mid) seats.push({ x: x + at(i), y: y + 3, up: true });
    for (let i = 0; i < bays; i++) seats.push({ x: x + at(i), y: y + 6 });
  } else if (opts.lobby) {
    for (let i = 0; i < bays; i++) props.push({ x: x + at(i), y: y + 1, tile: i === mid ? "urn" : "plant" });
    for (const dy of [3, 6]) {
      for (let i = 0; i < bays; i++) seats.push({ x: x + at(i), y: y + dy, up: dy === 3 });
    }
  } else {
    for (let i = 0; i < bays; i++) {
      props.push({ x: x + at(i), y: y + 1, tile: kit[i % kit.length] });
      props.push({ x: x + at(i), y: y + 2, tile: "desk" });
      // Directly in FRONT of the desk, facing the camera — the seat a worker is given first.
      seats.push({ x: x + at(i), y: y + 3, up: true });
    }
    // The second rank stands THREE rows forward, not one, and every bay is three tiles wide. A
    // character is over two tiles tall and carries a nameplate under its feet, so the spacing is
    // set by the PEOPLE, not by the floor — packed tighter, six critics in one room were drawn
    // on top of each other, sprites and labels both.
    for (let i = 0; i < bays; i++) seats.push({ x: x + at(i), y: y + 6 });
  }

  // Doors on the left and the right, so a row of rooms is a passage rather than three dead ends.
  // A room against the building's own outer wall has nothing on that side to open onto.
  const doors: Door[] = [];
  if (!opts.open) {
    if (!opts.edge.left) doors.push({ x, y: y + 4, dir: "v" });
    doors.push({ x: x + RW - 1, y: y + 4, dir: "v" });
    if (opts.edge.top) for (let i = 0; i < bays; i++) windows.push({ x: x + at(i) + 1, y });
  }

  return {
    id,
    label,
    x,
    y,
    w: RW,
    h: RH,
    brain: !!opts.brain,
    lobby: !!opts.lobby,
    open: !!opts.open,
    outdoor: false,
    doors,
    props,
    windows,
    seats,
    floor: opts.open ? "floor" : opts.lobby ? "floor" : "carpet",
  };
}

/** Where the cells go, in the order they are handed out. The centre is the brain and is never
 *  offered; the cell hard against the facade on the middle row is the lobby, because that is the
 *  one next to the front gate and a lobby anywhere else is not a lobby. */
function cellOrder(g: number): [number, number][] {
  const mid = (g - 1) / 2;
  const cells: [number, number][] = [];
  for (let j = 0; j < g; j++) for (let i = 0; i < g; i++) cells.push([i, j]);
  return cells
    .filter(([i, j]) => !(i === mid && j === mid) && !(i === g - 1 && j === mid))
    .sort((a, b) => {
      // Nearest the brain first, so the first departments declared sit closest to the middle.
      const da = Math.abs(a[0] - mid) + Math.abs(a[1] - mid);
      const db = Math.abs(b[0] - mid) + Math.abs(b[1] - mid);
      return da - db || a[1] - b[1] || a[0] - b[0];
    });
}

/** The whole building, solved from a department list. Pure and deterministic: the same
 *  departments give byte-identical output, which is what lets the tilemap be rendered once and
 *  never re-sent when the team changes. */
export function buildWorld(
  depts: readonly Dept[],
  core: { brain?: number; lobby?: number } = {},
): World {
  // An odd grid so there is a true middle to put the brain in. Two cells are always reserved —
  // the brain and the lobby — and any cell the company does not fill becomes open floor rather
  // than a blank quadrant of corridor.
  let g = 3;
  while (g * g - 2 < depts.length) g += 2;
  const mid = (g - 1) / 2;

  // Who is in which cell, before anything is measured.
  const order = cellOrder(g);
  const plan: { id: string; label: string; heads: number; i: number; j: number; brain?: boolean; lobby?: boolean; open?: boolean }[] = [
    { id: "__brain", label: "The Brain", heads: core.brain ?? 1, i: mid, j: mid, brain: true },
    { id: "", label: "Front desk", heads: core.lobby ?? 2, i: g - 1, j: mid, lobby: true },
  ];
  order.forEach(([i, j], n) => {
    const d = depts[n];
    if (d) plan.push({ id: d.id, label: d.label, heads: d.heads ?? 0, i, j });
    else plan.push({ id: "__open" + n, label: "", heads: 0, i, j, open: true });
  });

  // Two standing places per bay, so a room is as wide as its people need. The building visibly
  // bulges where the work is — which is the honest reading of a floor plan and the only way six
  // critics fit in one room without being drawn on top of each other.
  const baysOf = (heads: number): number => Math.max(MIN_BAYS, Math.ceil(heads / 2));
  const colBays: number[] = new Array(g).fill(MIN_BAYS);
  for (const c of plan) colBays[c.i] = Math.max(colBays[c.i], baysOf(c.heads));

  // Columns share a width so the corridors stay plumb from top to bottom; a column is as wide as
  // its busiest room. A corridor that jogged sideways between storeys would make every route a
  // dogleg and the plan unreadable.
  const colStart: number[] = [];
  let cx = 1;
  for (let i = 0; i < g; i++) {
    colStart.push(cx);
    cx += widthFor(colBays[i]) + GAP;
  }
  const rowY = (j: number): number => 1 + j * (RH + GAP);
  const facadeX = colStart[g - 1] + widthFor(colBays[g - 1]) + 1;
  const cols = facadeX + 1 + OUT;
  const rows = rowY(g - 1) + RH + 1;
  const gateY = rowY(mid) + 4;

  const rooms: Room[] = plan.map((c) =>
    furnish(c.id, c.label, colStart[c.i], rowY(c.j), colBays[c.i], {
      brain: c.brain,
      lobby: c.lobby,
      open: c.open,
      edge: { left: c.i === 0, top: c.j === 0 },
    }),
  );
  const brainRoom = rooms[0];
  const lobby = rooms[1];

  // Outdoors. Not a room — no walls: you get there by walking out of the gate, which is the only
  // reason the gate exists.
  // Out in the yard the spacing is the same as a room's: three tiles across, three ranks down.
  // Packed two apart, the researcher and the scraper were drawn on top of each other and their
  // names ran together into one word — the same mistake as a room sized to the sprite.
  const yardSeats: Seat[] = [];
  for (const dy of [0, 3, -3, 6, -6]) {
    for (let dx = 2; dx < OUT; dx += 3) {
      yardSeats.push({ x: facadeX + dx, y: gateY + dy, up: dx === 2 });
    }
  }
  const yard: Room = {
    id: "__web",
    label: "Out on the web",
    x: facadeX + 1,
    y: 0,
    w: OUT,
    h: rows,
    brain: false,
    lobby: false,
    open: true,
    outdoor: true,
    doors: [],
    props: [{ x: facadeX + 4, y: 2, tile: "mast" }],
    windows: [],
    seats: yardSeats,
    floor: "grass",
  };
  rooms.push(yard);

  const solid = new Array<boolean>(cols * rows).fill(false);
  const block = (x: number, y: number, on: boolean): void => {
    if (x < 0 || y < 0 || x >= cols || y >= rows) return;
    solid[y * cols + x] = on;
  };
  for (let x = 0; x < cols; x++) {
    block(x, 0, true);
    block(x, rows - 1, true);
  }
  for (let y = 0; y < rows; y++) {
    block(0, y, true);
    block(cols - 1, y, true);
    block(facadeX, y, true);
  }
  block(facadeX, gateY, false); /* the front gate */

  for (const r of rooms) {
    if (r.outdoor) continue;
    if (r.open) {
      for (const p of r.props) block(p.x, p.y, true);
      continue;
    }
    for (let x = r.x; x < r.x + r.w; x++) {
      block(x, r.y, true);
      block(x, r.y + r.h - 1, true);
    }
    for (let y = r.y; y < r.y + r.h; y++) {
      block(r.x, y, true);
      block(r.x + r.w - 1, y, true);
    }
    for (const d of r.doors) block(d.x, d.y, false);
    for (const p of r.props) block(p.x, p.y, true);
  }

  const byId = new Map(rooms.map((r) => [r.id, r]));
  return { cols, rows, grid: g, rooms, byId, solid, facadeX, gateY, brainRoom, lobby, yard };
}
