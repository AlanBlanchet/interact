/** The simulation: bodies that occupy tiles, a camera that watches them, and a floor that is
 *  never completely still.
 *
 *  Position belongs to the engine, not to the document. A body owns a tile coordinate; the DOM
 *  element is only where it happens to be drawn this frame. From that one inversion everything
 *  else follows:
 *
 *   - **Routes are computed, not guessed.** A breadth-first search over the walkability grid finds
 *     the way out of a room, along the hall and in through another room's door. It cannot cut
 *     through a wall or stand inside a desk, because those cells are simply not in the graph.
 *   - **Movement has a cause and it is usually INTERACTION.** One agent messaging another sends
 *     the sender across the building to say it and back again. Nobody teleports.
 *   - **Nothing is ever still.** Everyone has an errand loop of their own, staggered per person.
 *   - **Footfall is keyed to DISTANCE, not to a clock**, so a body that speeds up keeps its stride.
 *
 *  What is new here is the CAMERA and the two things it pays for.
 *
 *  The view this replaces scaled the whole building down until it fitted the panel, which in the
 *  side bar it actually ships in meant half scale: eighteen-pixel people and six-pixel capability
 *  marks. Fitting everything into frame is the one thing a game never does. So the frame is now
 *  bounded and the camera goes to the work — a weighted centroid of whoever is walking, talking or
 *  delivering, chased through a dead zone so it never jitters and never chases noise.
 *
 *  Because only eight or nine people are on screen at a time, two things become affordable that
 *  were not: the capability marks can be drawn at a size somebody can read, and everyone's line
 *  can be SHOWN rather than hidden behind a hover. The bubbles are placed here, on three levels,
 *  and any that would collide with another bubble or with somebody's nameplate is simply not
 *  shown — which is a guarantee, not a hope, because it is computed.
 */

export const SIM = String.raw`
/* ── the clock ─────────────────────────────────────────────────────────────────────────────── */
var BEAT = 2400;
var TICK = { t: 0, dt: 0, on: false };

/* Tiles per second. Slow enough to watch somebody cross a room, fast enough that a trip across
   the building is not a commute. */
var PACE = 3.6;
/* Half a tile per footfall: two frames per tile walked. */
var STRIDE = 0.5;
/* How long a body pauses once it gets where it was going. */
var DWELL = [900, 2600];

function hash(s) {
  var h = 2166136261;
  for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = (h * 16777619) >>> 0; }
  return h >>> 0;
}
function phaseOf(id) { return (hash(id) % 997) / 997; }
function rnd(id, n) { return (hash(id + ":" + n) % 10000) / 10000; }

/* ── the world, as data ──────────────────────────────────────────────────────────────────────
   Handed over by the renderer rather than measured out of the DOM. A tile grid IS the geometry,
   so there is nothing to read off a bounding box and nothing that can go stale on a resize. */
var W = { cols: 0, rows: 0, tile: 24, solid: null, rooms: [], byId: {}, gate: [0, 0], ok: false };

function readWorld() {
  var el = document.querySelector(".wp-world");
  if (!el) { W.ok = false; return; }
  W.cols = Number(el.getAttribute("data-cols")) || 0;
  W.rows = Number(el.getAttribute("data-rows")) || 0;
  W.tile = Number(el.getAttribute("data-tile")) || 24;
  var bits = el.getAttribute("data-solid") || "";
  W.solid = new Uint8Array(W.cols * W.rows);
  for (var i = 0; i < W.solid.length; i++) W.solid[i] = bits.charCodeAt(i) === 49 ? 1 : 0;
  try { W.rooms = JSON.parse(el.getAttribute("data-rooms") || "[]"); } catch (e) { W.rooms = []; }
  W.byId = {};
  for (var r = 0; r < W.rooms.length; r++) W.byId[W.rooms[r].i] = W.rooms[r];
  var g = (el.getAttribute("data-gate") || "0,0").split(",");
  W.gate = [Number(g[0]), Number(g[1])];
  W.ok = W.cols > 0 && W.rows > 0;
}

function walkable(x, y) {
  if (x < 0 || y < 0 || x >= W.cols || y >= W.rows) return false;
  return !W.solid[y * W.cols + x];
}

/* ── routing ─────────────────────────────────────────────────────────────────────────────────
   Breadth-first over the four neighbours. The grid is a couple of thousand cells, so an exact
   search costs less than the heuristic would, and it is exact: if there is a way through the
   doors it is found, and if there is not, the body simply does not set off. */
function route(ax, ay, bx, by) {
  if (ax === bx && ay === by) return [];
  var n = W.cols * W.rows;
  var prev = new Int32Array(n).fill(-1);
  var start = ay * W.cols + ax, goal = by * W.cols + bx;
  if (!walkable(bx, by)) return null;
  var q = [start];
  prev[start] = start;
  var head = 0;
  while (head < q.length) {
    var cur = q[head++];
    if (cur === goal) break;
    var cx = cur % W.cols, cy = (cur / W.cols) | 0;
    for (var d = 0; d < 4; d++) {
      var nx = cx + (d === 0 ? 1 : d === 1 ? -1 : 0);
      var ny = cy + (d === 2 ? 1 : d === 3 ? -1 : 0);
      if (!walkable(nx, ny)) continue;
      var ni = ny * W.cols + nx;
      if (prev[ni] !== -1) continue;
      prev[ni] = cur;
      q.push(ni);
    }
  }
  if (prev[goal] === -1) return null;
  var out = [], at = goal;
  while (at !== start) { out.push({ x: at % W.cols, y: (at / W.cols) | 0 }); at = prev[at]; }
  out.reverse();
  return out;
}

/* A free cell inside a room: somewhere to wander to that is not a wall, a desk or the seat you
   just left. Deterministic per body and per attempt. */
function looseCell(room, id, n) {
  if (!room) return null;
  for (var tries = 0; tries < 14; tries++) {
    var dx = 1 + Math.floor(rnd(id, n * 13 + tries) * (room.w - 2));
    var dy = 1 + Math.floor(rnd(id, n * 29 + tries + 7) * (room.h - 2));
    var x = room.x + dx, y = room.y + dy;
    if (room.o) { x = room.x + dx; y = 1 + Math.floor(rnd(id, n * 31 + tries) * (W.rows - 3)); }
    if (walkable(x, y)) return { x: x, y: y };
  }
  return null;
}

/* A cell beside somebody — where you stand when you have come over to say something. */
function besideOf(x, y) {
  var around = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, 1], [1, -1], [-1, -1],
                [2, 0], [-2, 0], [0, 2], [0, -2]];
  for (var i = 0; i < around.length; i++) {
    var nx = x + around[i][0], ny = y + around[i][1];
    if (walkable(nx, ny)) return { x: nx, y: ny };
  }
  return null;
}

/* ── bodies ──────────────────────────────────────────────────────────────────────────────────
   One per worker. Position is in TILES and is a float while walking; the element is placed from
   it every frame and never the other way round. */
var BODIES = {};
var CAST = null;

function bodyFor(el) {
  var id = el.getAttribute("data-run-id");
  var b = BODIES[id];
  var seat = (el.getAttribute("data-seat") || "0,0").split(",");
  var sx = Number(seat[0]), sy = Number(seat[1]);
  if (!b) {
    b = BODIES[id] = {
      id: id, x: sx, y: sy, seatX: sx, seatY: sy,
      face: 1, path: null, step: 0, walked: 0, speed: 0,
      mode: "settled", nextAt: 0, home: "", talkUntil: 0, errand: null,
      saidAt: 0, phase: phaseOf(id)
    };
    /* Staggered from the start. Fifteen bodies that all decide to move on the same frame is the
       single loudest tell that a scene is driven by a stylesheet rather than by people. */
    b.nextAt = 2000 + b.phase * 9000;
  }
  b.el = el;
  b.home = el.getAttribute("data-home") || "";
  /* A seat that moved means the roster moved them — a new department, or out to the web. They do
     not appear there; they get up and walk. */
  if (b.seatX !== sx || b.seatY !== sy) {
    b.seatX = sx; b.seatY = sy;
    if (b.mode !== "errand") sendTo(b, sx, sy, "commute");
  }
  return b;
}

function roomOf(b) { return W.byId[b.home] || null; }

/** Put a body on the road. Everything that moves anybody goes through here, so there is exactly
 *  one place where a journey can start and exactly one shape a journey has. */
function sendTo(b, x, y, mode) {
  if (!W.ok) return false;
  var from = { x: Math.round(b.x), y: Math.round(b.y) };
  var pts = route(from.x, from.y, x, y);
  if (!pts || !pts.length) return false;
  b.path = pts;
  b.step = 0;
  b.walked = 0;
  b.speed = 0;
  b.mode = mode || "walk";
  if (b.el) b.el.classList.add("is-walking");
  window.__wp.walks++;
  return true;
}

/* ── walking ─────────────────────────────────────────────────────────────────────────────────
   Constant pace with an acceleration at the start and a brake at the end, so a body leans into a
   journey and settles out of it. The stride is measured in DISTANCE walked, which is what keeps
   the feet under the person when the speed changes. */
function stepWalk(b, dt) {
  var want = PACE;
  if (b.walked < 0.35) want = PACE * (0.35 + (b.walked / 0.35) * 0.65);
  if (b.path.length - b.step <= 1) want = PACE * 0.55;
  b.speed += (want - b.speed) * Math.min(1, dt / 90);

  /* The frame's whole allowance, spent ACROSS waypoints rather than stopping at each one. A route
     through the doors is twenty-odd legs, and consuming only up to the next corner threw away a
     fraction of a frame at every one of them — a body that hesitates at every corner is being
     dragged along a path rather than walking. */
  var move = (b.speed * dt) / 1000;
  var guard = 0;
  while (move > 0 && b.path && guard++ < 64) {
    var target = b.path[b.step];
    var dx = target.x - b.x, dy = target.y - b.y;
    var dist = Math.sqrt(dx * dx + dy * dy);
    if (Math.abs(dx) > 0.02) b.face = dx > 0 ? 1 : -1;
    if (dist > move) {
      b.x += (dx / dist) * move;
      b.y += (dy / dist) * move;
      b.walked += move;
      return;
    }
    b.x = target.x;
    b.y = target.y;
    b.walked += dist;
    move -= dist;
    b.step++;
    if (b.step >= b.path.length) {
      b.path = null;
      if (b.el) b.el.classList.remove("is-walking");
      arrived(b);
      return;
    }
  }
}

function arrived(b) {
  if (b.mode === "errand" && b.errand) {
    /* Delivered. Both of them stop and turn to each other for a moment — a message that lands
       with nobody reacting is a note flying past a person rather than to one. */
    var them = BODIES[b.errand.to];
    b.talkUntil = TICK.t + 1500;
    if (b.el) b.el.classList.add("is-talking");
    if (them) {
      them.talkUntil = TICK.t + 1500;
      if (them.el) { them.el.classList.add("is-talking"); them.el.classList.add("has-post"); }
      them.face = them.x > b.x ? -1 : 1;
      b.face = b.x > them.x ? -1 : 1;
    }
    if (b.el && b.errand.text) {
      b.el.setAttribute("data-say", b.errand.text);
      var line = b.el.querySelector(".wp-say b");
      if (line) line.textContent = b.errand.text;
      b.saidAt = TICK.t;
    }
    b.mode = "delivering";
    b.nextAt = TICK.t + 1500;
    return;
  }
  b.mode = "settled";
  b.nextAt = TICK.t + DWELL[0] + rnd(b.id, Math.floor(TICK.t / 1000)) * (DWELL[1] - DWELL[0]);
}

/* ── what a body decides to do next ──────────────────────────────────────────────────────────
   The part that makes the building alive whether or not anything happened. Nobody is told to
   move by the data here: they get up because it has been a while, cross their own room, look at
   what is on the wall, and come back. */
function decide(b, t) {
  if (t < b.nextAt) return;
  if (b.mode === "delivering") {
    if (b.el) b.el.classList.remove("is-talking");
    var them = b.errand && BODIES[b.errand.to];
    if (them && them.el) { them.el.classList.remove("is-talking"); them.el.classList.remove("has-post"); }
    b.errand = null;
    b.mode = "settled";
    if (!sendTo(b, b.seatX, b.seatY, "return")) b.nextAt = t + 3000;
    return;
  }
  if (b.el && b.el.getAttribute("data-status") === "error") { b.nextAt = t + 6000; return; }
  /* A worker the registry says has stopped stops. Absence of motion is the loudest possible way
     to say it, and much cheaper to read than a timestamp. */
  if (b.el && b.el.getAttribute("data-stalled") === "1") { b.nextAt = t + 8000; return; }

  var away = Math.abs(b.x - b.seatX) > 0.5 || Math.abs(b.y - b.seatY) > 0.5;
  var n = Math.floor(t / 1000);
  if (away && rnd(b.id, n) < 0.6) { if (sendTo(b, b.seatX, b.seatY, "return")) return; }
  var cell = looseCell(roomOf(b), b.id, n);
  if (cell && sendTo(b, cell.x, cell.y, "roam")) return;
  b.nextAt = t + 1800;
}

/* ── drawing a body ──────────────────────────────────────────────────────────────────────────
   One transform per actor per frame, plus a z-index so somebody standing further down the room
   is in front of somebody standing further up it. Depth ordering is the cheapest thing that makes
   a flat grid read as a floor. */
function place(b, t) {
  var el = b.el;
  if (!el) return;
  var px = b.x * W.tile + W.tile / 2;
  var py = b.y * W.tile + W.tile;
  b.px = px;
  b.py = py;
  var bob = 0, lean = 0;
  if (b.path) {
    /* Footfall: a half tile per step, so the bounce belongs to the DISTANCE covered and stays
       right when the body accelerates or brakes. */
    var ph = (b.walked / STRIDE) % 1;
    bob = ph < 0.5 ? -1 : 0;
    lean = b.face * 1.5;
    el.classList.toggle("wp-fA", ph < 0.5);
  } else {
    var status = el.getAttribute("data-status");
    var p = b.phase;
    if (status === "running") {
      var work = Math.sin((t / (BEAT * 0.5)) * Math.PI * 2 + p * 6.283);
      bob = work > 0.86 ? -1 : 0;
      lean = Math.sin((t / (BEAT * 2.5)) * Math.PI * 2 + p * 6.283) * 0.8;
    } else if (status === "done" || status === "foreign") {
      bob = Math.sin((t / (BEAT * 3)) * Math.PI * 2 + p * 6.283) > 0.7 ? -1 : 0;
    } else if (status === "error") {
      bob = 1;
    }
  }
  el.style.transform = "translate3d(" + px.toFixed(1) + "px," + (py + bob).toFixed(1) + "px,0)";
  el.style.zIndex = String(100 + Math.round(b.y * 4));
  el.classList.toggle("face-left", b.face < 0);
  if (lean) el.style.setProperty("--lean", lean.toFixed(2) + "deg");
  else el.style.removeProperty("--lean");
}

/* ── the camera ──────────────────────────────────────────────────────────────────────────────
   The building is bigger than the panel on purpose. Left alone the camera holds a weighted
   centroid of whoever is doing something — delivering a message outranks walking, walking
   outranks standing — and chases it through a DEAD ZONE, so it moves when the work moves and
   holds perfectly still when it does not.

   What is new here is that a READER can take it. The version this replaces derived the scale
   from the panel width and offered no way to change it, which had two consequences nobody
   could work around: the smallest possible view was 943x794 of a 1272x888 building, so there
   was NO scale at which the company was visible at once; and any drag was snatched back after
   six seconds, so even the panning that did exist could not be trusted to stay put. Both are
   gone. The scale is a rung on a ladder the reader moves, and a reader who takes the camera
   KEEPS it until they hand it back.

   THE SCALE LADDER, which is the thing that makes pulling back possible at all. A tile is eight
   cells drawn three pixels each, so one source pixel is three device pixels at zoom one. Every
   rung here is a THIRD, which lands one source pixel on a whole number of device pixels at
   every rung — INCLUDING the rungs below one: 2/3 draws each source pixel two wide and 1/3
   draws it one wide, both exact. A ladder of whole numbers can only ever zoom in; a ladder of
   arbitrary fractions (0.75, 0.5) smears every hard edge this substrate is made of. Thirds are
   the only ladder that does both. */
var CAM = { x: 0, y: 0, step: 3, zoom: 1, vw: 0, vh: 0, follow: true, ready: false };
/* How many tiles to try to keep across the frame when the panel opens. Sixteen is a room and
   its corridor — unchanged, so the view still OPENS exactly where it used to. */
var ACROSS = 16;
var STEP_MIN = 1;
var STEP_MAX = 9;
/* What the reader is told the scale is. A rung is a third, so two thirds of them are fractions
   and "0.67x" in a pixel-art building would be the only decimal on screen. */
var SCALE_WORDS = ["⅓", "⅔", "1", "1⅓", "1⅔", "2", "2⅓", "2⅔", "3"];
/* What the panel is currently SHOWING, so the frame loop can skip a write it already made. */
var SHOWN = { far: "", follow: "", step: 0 };

function zoomOf(step) { return step / 3; }
function clampStep(s) { return Math.max(STEP_MIN, Math.min(STEP_MAX, Math.round(s) || STEP_MIN)); }
function worldPx() { return { w: W.cols * W.tile, h: W.rows * W.tile }; }

/** The BUILT extent, which is what "the whole company" actually means.
 *
 *  The world is deliberately bigger than the building — grounds on every side, so a tall narrow
 *  panel does not letterbox — and fitting the WORLD spends a whole rung of the ladder on
 *  grass. Measured against the rooms instead, the same 380px side bar frames 97% of the
 *  building where fitting the world framed 88% of a picture that is mostly lawn. Two tiles of
 *  verge, because a building drawn hard against the frame reads as cropped. */
var BUILT = null;
function builtPx() {
  if (BUILT) return BUILT;
  var rooms = W.rooms || [];
  if (!rooms.length) return (BUILT = worldPx());
  var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (var i = 0; i < rooms.length; i++) {
    var r = rooms[i];
    if (r.x < x0) x0 = r.x;
    if (r.y < y0) y0 = r.y;
    if (r.x + r.w > x1) x1 = r.x + r.w;
    if (r.y + r.h > y1) y1 = r.y + r.h;
  }
  x0 = Math.max(0, x0 - 2); y0 = Math.max(0, y0 - 2);
  x1 = Math.min(W.cols, x1 + 2); y1 = Math.min(W.rows, y1 + 2);
  BUILT = { x: x0 * W.tile, y: y0 * W.tile, w: (x1 - x0) * W.tile, h: (y1 - y0) * W.tile };
  return BUILT;
}

function camWeight(b) {
  if (!b.el || !b.el.isConnected) return 0;
  if (b.mode === "errand" || b.mode === "delivering") return 6;
  if (b.talkUntil > TICK.t) return 5;
  if (b.path) return 3;
  if (b.el.getAttribute("data-status") === "error") return 1.4;
  return 0.22;
}

/** The rung the panel opens on — the same framing as before this ladder existed, so nothing
 *  about the first sight of the view changed. It is a STARTING rung now, not the only one. */
function camOpenStep() {
  return clampStep(Math.round(CAM.vw / (ACROSS * W.tile)) * 3);
}

/** The rung at which the whole building is inside the frame. If the panel is too narrow to hold
 *  it at any pixel-exact scale — a 380px side bar cannot — this is the smallest rung, which
 *  there shows the full height and about seven eighths of the width. Trading the substrate for
 *  that last eighth is not worth it; every pixel in the scene would go soft. */
function camFitStep() {
  var built = builtPx();
  if (!CAM.vw || !CAM.vh) return STEP_MIN;
  return clampStep(Math.floor(3 * Math.min(CAM.vw / built.w, CAM.vh / built.h)));
}

function camFit() {
  var view = document.querySelector(".wp-view");
  if (!view) return;
  var box = view.getBoundingClientRect();
  if (!box.width || !box.height) return;
  CAM.vw = box.width;
  CAM.vh = box.height;
  if (!CAM.ready) {
    CAM.ready = true;
    CAM.step = camOpenStep();
    CAM.zoom = zoomOf(CAM.step);
    window.__wp.scale = CAM.zoom;
    camSnap();
  }
  camClamp();
  camApply();
}

function camSpan() {
  return { w: CAM.vw / CAM.zoom, h: CAM.vh / CAM.zoom };
}

function camClamp() {
  var world = worldPx();
  var span = camSpan();
  CAM.x = world.w <= span.w ? (world.w - span.w) / 2 : Math.max(0, Math.min(world.w - span.w, CAM.x));
  CAM.y = world.h <= span.h ? (world.h - span.h) / 2 : Math.max(0, Math.min(world.h - span.h, CAM.y));
}

/** Change scale while holding one point on the floor under the same pixel. Anchoring is what
 *  makes a wheel over the map read as a camera rather than as a jump: the desk you were looking
 *  at is still under the pointer afterwards. With no anchor the frame's own centre holds. */
function camSetStep(step, ax, ay) {
  var next = clampStep(step);
  if (next === CAM.step) return CAM.step;
  var view = document.querySelector(".wp-view");
  var box = view ? view.getBoundingClientRect() : null;
  var hx = box && typeof ax === "number" ? ax - box.left : CAM.vw / 2;
  var hy = box && typeof ay === "number" ? ay - box.top : CAM.vh / 2;
  var wx = CAM.x + hx / CAM.zoom;
  var wy = CAM.y + hy / CAM.zoom;
  CAM.step = next;
  CAM.zoom = zoomOf(next);
  window.__wp.scale = CAM.zoom;
  CAM.x = wx - hx / CAM.zoom;
  CAM.y = wy - hy / CAM.zoom;
  camClamp();
  camApply();
  return CAM.step;
}

/** Hand the camera to the reader, or give it back. Taking it is implicit — drag, wheel, a rung,
 *  an arrow key — because asking somebody to press a button before they may move the map is the
 *  kind of thing that makes a view unusable. Giving it back is explicit and one click. */
function camHold() {
  if (!CAM.follow) return;
  CAM.follow = false;
  camApply();
}

function camFollow(on) {
  CAM.follow = !!on;
  camApply();
  return CAM.follow;
}

/** The whole company at once. This is the thing the view could not do at any setting: it is
 *  the bottom rung of the ladder plus a centred frame, and it is on a key, a button and a
 *  double-click because it is the first thing anybody wants from a map they are lost in. */
function camWhole() {
  camHold();
  camSetStep(camFitStep());
  var built = builtPx();
  var span = camSpan();
  CAM.x = built.x + (built.w - span.w) / 2;
  CAM.y = built.y + (built.h - span.h) / 2;
  camClamp();
  camApply();
  return { step: CAM.step, zoom: CAM.zoom, span: span, built: built };
}

/** Move the frame by SCREEN pixels, so a key press and a drag of the same distance agree. */
function camPan(dx, dy) {
  camHold();
  CAM.x += dx / CAM.zoom;
  CAM.y += dy / CAM.zoom;
  camClamp();
  camApply();
}

function camAim() {
  var wx = 0, wy = 0, tw = 0;
  for (var id in BODIES) {
    var b = BODIES[id];
    var k = camWeight(b);
    if (!k) continue;
    wx += (b.px || b.x * W.tile) * k;
    wy += (b.py || b.y * W.tile) * k;
    tw += k;
  }
  if (!tw) return null;
  var span = camSpan();
  return { x: wx / tw - span.w / 2, y: wy / tw - span.h / 2 };
}

function camSnap() {
  var aim = camAim();
  if (!aim) return;
  CAM.x = aim.x;
  CAM.y = aim.y;
  camClamp();
}

function camStep(dt) {
  if (!CAM.ready || !CAM.follow) return;
  var aim = camAim();
  if (!aim) return;
  var span = camSpan();
  var dead = { x: span.w * 0.16, y: span.h * 0.16 };
  var k = Math.min(1, dt / 700);
  var gx = aim.x - CAM.x, gy = aim.y - CAM.y;
  if (Math.abs(gx) > dead.x) CAM.x += (gx - (gx > 0 ? dead.x : -dead.x)) * k;
  if (Math.abs(gy) > dead.y) CAM.y += (gy - (gy > 0 ? dead.y : -dead.y)) * k;
  camClamp();
  camApply();
}

function camApply() {
  var stage = document.querySelector(".wp-stagebox");
  if (!stage) return;
  var z = CAM.zoom;
  stage.style.setProperty("--inv", String(1 / z));
  stage.style.setProperty("--z", String(z));
  stage.style.transform =
    "translate3d(" + Math.round(-CAM.x * z) + "px," + Math.round(-CAM.y * z) + "px,0) scale(" + z + ")";
  /* WRITE ONLY ON CHANGE. This runs on every frame the camera is following, and an attribute
     written on .wp-view — the root every rule in the far-view block hangs off — invalidates
     the whole scene's style even when the value did not change. Measured against the same page
     without the guard: frame p95 33.3ms against 16.8ms, i.e. a dropped frame every twenty, for
     three writes that are almost always identical to what is already there. */
  var far = z < 1 ? "1" : "0";
  var fol = CAM.follow ? "1" : "0";
  if (far !== SHOWN.far || fol !== SHOWN.follow) {
    var view = document.querySelector(".wp-view");
    if (view) {
      /* Pulled back past one, a nameplate held at constant SCREEN size is wider than the room
         the person stands in, and the words out-mass the building — the complaint the
         constant-size trick exists to prevent, arriving from the other side. So below one the
         view sheds its words and becomes what it should be at that scale: a signed PLAN. */
      if (far !== SHOWN.far) view.setAttribute("data-far", far);
      if (fol !== SHOWN.follow) {
        view.setAttribute("data-follow", fol);
        /* The latch says two different words; the button carries one LABEL and a pressed state,
           so a reader who cannot see which word is showing is told the same thing. */
        var latch = document.querySelector(".wp-cam-follow");
        if (latch) latch.setAttribute("aria-pressed", CAM.follow ? "true" : "false");
      }
      SHOWN.far = far;
      SHOWN.follow = fol;
    }
  }
  if (CAM.step !== SHOWN.step) {
    var rule = document.querySelector(".wp-rule");
    var read = document.querySelector(".wp-read");
    if (rule) rule.setAttribute("data-step", String(CAM.step));
    if (read) read.textContent = SCALE_WORDS[CAM.step - 1] + "×";
    if (rule || read) SHOWN.step = CAM.step;
  }
  var eye = document.querySelector(".wp-eye");
  var mini = document.querySelector(".wp-mini");
  if (eye && mini) {
    var span = camSpan();
    var world = worldPx();
    var mw = mini.clientWidth - 4, mh = mini.clientHeight - 4;
    var sx = mw / world.w, sy = mh / world.h;
    /* Clamped INTO the plan. Pulled back far enough that the frame is larger than the world,
       the camera sits at a negative offset and the unclamped box was drawn floating above the
       panel as a bare rectangle over the floor — the tell that the plan and the frame had
       stopped agreeing. Clamped, it simply fills the plan, which is the truth. */
    var ex = Math.max(0, Math.min(mw, CAM.x * sx));
    var ey = Math.max(0, Math.min(mh, CAM.y * sy));
    eye.style.left = (2 + ex) + "px";
    eye.style.top = (2 + ey) + "px";
    eye.style.width = Math.max(4, Math.min(mw - ex, span.w * sx)) + "px";
    eye.style.height = Math.max(4, Math.min(mh - ey, span.h * sy)) + "px";
  }
}

/** Steer by pointing at the plan in the corner. The camera stays where it is put. */
function camLookAt(px, py) {
  camHold();
  var span = camSpan();
  CAM.x = px - span.w / 2;
  CAM.y = py - span.h / 2;
  camClamp();
  camApply();
}

/* ── speech, placed rather than hidden ───────────────────────────────────────────────────────
   Every line is on at rest. What makes that possible is that only a few people are on screen at
   once, so the bubbles can be laid out: candidates in priority order, three heights to choose
   from, and any bubble that would land on another bubble or on somebody's nameplate is dropped
   rather than drawn over them. The boxes are computed in world pixels, which is the same
   comparison the eye makes because everything scales together. */
var SAY_MAX = 7;
var SAY_AT = 0;
var SAID = [];

function boxesOf(b, kind) {
  /* The furniture a character carries, as rectangles in world pixels around its feet.
     MEASURED off the rendered elements, not guessed: the boxes here had drifted from what the
     stylesheet actually draws — the stamp's reserve sat nine pixels below the stamp and missed its
     top edge entirely, and the tools' reserve still described the column at the shoulder they were
     moved off. A reserve that does not match the element it stands for refuses bubbles over empty
     air and allows them over a word. Generous on purpose, in the direction that costs a bubble
     rather than the one that draws words on top of a name. */
  var up = b.el && b.el.getAttribute("data-label") === "up";
  var x = b.px, y = b.py;
  if (kind === "tag") return up ? [x - 34, y - 70, x + 34, y - 56] : [x - 34, y + 1, x + 34, y + 15];
  if (kind === "can") return up ? [x - 28, y, x + 28, y + 20] : [x - 28, y + 15, x + 28, y + 35];
  return up ? [x - 24, y - 95, x + 24, y - 82] : [x - 24, y - 65, x + 24, y - 52];
}

function sayBox(b, level) {
  var up = b.el && b.el.getAttribute("data-label") === "up";
  /* Clear of the stamp rather than three pixels off it: measured, the placard's top edge is
     sixty-three world pixels above the boots and the lowest bubble's floor was sixty-six. */
  var base = (up ? 100 : 72) + level * 26;
  /* The bubble holds a constant SCREEN size, so in world pixels it shrinks as the camera moves
     in. Reserving the unscaled box would refuse most of the lines at zoom two for a collision
     that is not there. */
  var hw = 70 / CAM.zoom, hh = 22 / CAM.zoom;
  return [b.px - hw, b.py - base - hh, b.px + hw, b.py - base + 2];
}

function hits(a, b) {
  return a[0] < b[2] - 1 && b[0] < a[2] - 1 && a[1] < b[3] - 1 && b[1] < a[3] - 1;
}

function sayRank(b, t) {
  if (b.talkUntil > t) return 100;
  if (b.mode === "errand" || b.mode === "delivering") return 90;
  if (t - b.saidAt < 7000) return 80;
  if (b.path) return 40;
  if (b.el && b.el.getAttribute("data-status") === "error") return 30;
  return 10 + b.phase;
}

function speechLayout(t) {
  if (t - SAY_AT < 420) return;
  SAY_AT = t;
  var span = camSpan();
  var pad = W.tile * 2;
  var live = [];
  var taken = SIGNS.slice();
  for (var id in BODIES) {
    var b = BODIES[id];
    if (!b.el || !b.el.isConnected || b.px === undefined) continue;
    var seen =
      b.px > CAM.x - pad && b.px < CAM.x + span.w + pad &&
      b.py > CAM.y - pad && b.py < CAM.y + span.h + pad;
    if (!seen) continue;
    /* Everything a character already wears is an obstacle, whether or not it gets a bubble. */
    taken.push(boxesOf(b, "tag"));
    taken.push(boxesOf(b, "can"));
    if (b.el.querySelector(".wp-mark")) taken.push(boxesOf(b, "mark"));
    if (b.el.getAttribute("data-say")) live.push(b);
  }
  live.sort(function (p, q) { return sayRank(q, t) - sayRank(p, t); });
  var next = [];
  for (var i = 0; i < live.length && next.length < SAY_MAX; i++) {
    for (var lv = 0; lv < 3; lv++) {
      var box = sayBox(live[i], lv);
      var clash = false;
      for (var j = 0; j < taken.length; j++) if (hits(box, taken[j])) { clash = true; break; }
      if (clash) continue;
      taken.push(box);
      live[i].el.style.bottom = "";
      live[i].el.querySelector(".wp-say").style.bottom =
        ((live[i].el.getAttribute("data-label") === "up" ? 96 : 66) + lv * 26) + "px";
      next.push(live[i].el);
      break;
    }
  }
  /* Clear the class off EVERY actor that did not win a place, not merely off the ones this
     function last set it on: a swapped-in element that arrives already carrying it would
     otherwise keep a bubble open forever, outside the layout that is supposed to guarantee no two
     of them collide. */
  var all = document.querySelectorAll(".wp-actor.is-saying");
  for (var k = 0; k < all.length; k++) if (next.indexOf(all[k]) < 0) all[k].classList.remove("is-saying");
  for (var m = 0; m < next.length; m++) next[m].classList.add("is-saying");
  SAID = next;
}

/* ── rooms light up, doors open ──────────────────────────────────────────────────────────────
   Both driven off where bodies ACTUALLY are rather than off the snapshot, so a room goes dark and
   a door swings shut the moment the last person walks out of it. */
var LIT = {};
var LEAVES = [];

/* The room signs are world text too, and the speech layout was blind to them: it reserved every
   nameplate and every capability rail and then put a line straight through "Quality & Critics".
   Read once per bind, in untransformed layout pixels, which is the same space the bubbles use. */
var SIGNS = [];

function readSigns() {
  SIGNS = [];
  var list = document.querySelectorAll(".wp-plaque");
  for (var i = 0; i < list.length; i++) {
    var el = list[i];
    if (!el.offsetWidth) continue;
    SIGNS.push([el.offsetLeft - 2, el.offsetTop - 2, el.offsetLeft + el.offsetWidth + 2, el.offsetTop + el.offsetHeight + 2]);
  }
}

function readDoors() {
  LEAVES = [];
  var list = document.querySelectorAll(".wp-leaf");
  for (var i = 0; i < list.length; i++) {
    var el = list[i];
    LEAVES.push({
      el: el,
      x: Number(el.getAttribute("x") || 0) / 8,
      y: Number(el.getAttribute("y") || 0) / 8,
      on: false
    });
  }
}

function doors() {
  for (var i = 0; i < LEAVES.length; i++) {
    var d = LEAVES[i];
    var near = false;
    for (var id in BODIES) {
      var b = BODIES[id];
      if (!b.el || !b.el.isConnected) continue;
      if (Math.abs(b.x - d.x) <= 1.1 && Math.abs(b.y - d.y) <= 1.4) { near = true; break; }
    }
    if (near === d.on) continue;
    d.on = near;
    d.el.classList.toggle("is-open", near);
  }
}

/* Worst first. A room holding one crashed agent and five happy ones is a room with a problem in
   it, so the light takes the loudest state in the room rather than an average or the last body
   the loop happened to see. Same order the rail sorts its own rows by. */
var VOICES = ["error", "asked", "held", "finished", "working", "not-ours"];

function lighting() {
  var now = {};
  for (var id in BODIES) {
    var b = BODIES[id];
    if (!b.el || !b.el.isConnected) continue;
    for (var i = 0; i < W.rooms.length; i++) {
      var r = W.rooms[i];
      if (b.x >= r.x && b.x < r.x + r.w && b.y >= r.y && b.y < r.y + r.h) {
        var v = b.el.getAttribute("data-attention") || "working";
        var rank = VOICES.indexOf(v);
        if (rank < 0) rank = VOICES.length - 1;
        if (!now[r.i] || rank < now[r.i].rank) now[r.i] = { rank: rank, voice: v };
        break;
      }
    }
  }
  for (var k in now) {
    if (LIT[k] && LIT[k].voice === now[k].voice) continue;
    setLit(k, "1", now[k].voice);
  }
  for (var k2 in LIT) {
    if (now[k2]) continue;
    setLit(k2, "0", "");
  }
  LIT = now;
}
function setLit(id, on, voice) {
  var q = '[data-room="' + cssq(id) + '"]';
  /* ALL of them: the building is drawn in layers now — grounds, light, structure — so one room is
     several groups carrying the same id, and a querySelector lit whichever came first. */
  var rooms = document.querySelectorAll(".wp-rm" + q);
  for (var i = 0; i < rooms.length; i++) {
    rooms[i].setAttribute("data-lit", on);
    if (voice) rooms[i].setAttribute("data-voice", voice);
    else rooms[i].removeAttribute("data-voice");
  }
  var dot = document.querySelector(".wp-mini " + q);
  if (dot) {
    dot.setAttribute("data-lit", on);
    if (voice) dot.setAttribute("data-voice", voice);
    else dot.removeAttribute("data-voice");
  }
}
function cssq(s) { return String(s).replace(/["\\]/g, "\\$&"); }

/* ── the plan in the corner ──────────────────────────────────────────────────────────────────
   One dot per person in their pod's colour. The camera takes the overview away and this is what
   gives it back, so it is updated often enough to be true and rarely enough to be free. */
var DOTS = {};
var DOT_AT = 0;

function minimap(t) {
  if (t - DOT_AT < 160) return;
  DOT_AT = t;
  var host = document.querySelector(".wp-dots");
  var mini = document.querySelector(".wp-mini");
  if (!host || !mini) return;
  var sx = (mini.clientWidth - 4) / (W.cols * W.tile);
  var sy = (mini.clientHeight - 4) / (W.rows * W.tile);
  var seen = {};
  for (var id in BODIES) {
    var b = BODIES[id];
    if (!b.el || !b.el.isConnected || b.px === undefined) continue;
    seen[id] = 1;
    var dot = DOTS[id];
    if (!dot) {
      dot = DOTS[id] = document.createElement("i");
      host.appendChild(dot);
    }
    dot.style.setProperty("--accent", b.el.style.getPropertyValue("--accent"));
    dot.style.left = (b.px * sx) + "px";
    dot.style.top = (b.py * sy) + "px";
  }
  for (var k in DOTS) {
    if (seen[k]) continue;
    if (DOTS[k].parentNode) DOTS[k].parentNode.removeChild(DOTS[k]);
    delete DOTS[k];
  }
}

/* ── the post: an interaction is a WALK ──────────────────────────────────────────────────────
   A message is not a line drawn between two boxes and not a note flying over the roof: the sender
   gets up, walks the corridors to wherever the recipient is standing, says it, and walks back. */
var QUEUE = [];
var LIVE = 0;
var MAX_ERRANDS = 3;

function errand(fromId, toId, text) {
  QUEUE.push({ f: fromId, t: toId, x: text });
  if (QUEUE.length > 24) QUEUE.shift();
}

function pumpErrands(t) {
  while (LIVE < MAX_ERRANDS && QUEUE.length) {
    var job = QUEUE.shift();
    var a = BODIES[job.f], b = BODIES[job.t];
    if (!a || !b || !a.el || !b.el) continue;
    if (a.mode === "errand" || a.mode === "delivering") { QUEUE.push(job); break; }
    var spot = besideOf(Math.round(b.x), Math.round(b.y));
    if (!spot) continue;
    a.errand = { to: job.t, text: job.x };
    if (sendTo(a, spot.x, spot.y, "errand")) { LIVE++; window.__wp.notes++; }
    else { a.errand = null; }
  }
}

/* ── the loop ────────────────────────────────────────────────────────────────────────────────
   One rAF for the whole building. Cheap when nobody is looking: a panel left open on a second
   monitor is the intended way to use this, so a hidden document keeps its clock and skips the
   work. */
function frame(ts) {
  requestAnimationFrame(frame);
  /* Cheap when nobody is looking, and cheap when somebody has paused it — but the chain itself
     never stops, so TICK.on is a switch rather than a one-way door. */
  if (!TICK.on || document.hidden) { TICK.t = ts; return; }
  var dt = Math.min(64, ts - TICK.t || 16);
  TICK.t = ts;
  TICK.dt = dt;
  var busy = 0;
  for (var id in BODIES) {
    var b = BODIES[id];
    if (!b.el || !b.el.isConnected) continue;
    if (b.path) { stepWalk(b, dt); busy++; }
    else decide(b, ts);
    place(b, ts);
  }
  LIVE = 0;
  for (var id2 in BODIES) {
    var b2 = BODIES[id2];
    if (b2.mode === "errand" || b2.mode === "delivering") LIVE++;
  }
  pumpErrands(ts);
  camStep(dt);
  lighting();
  doors();
  speechLayout(ts);
  minimap(ts);
  window.__wp.walking = busy;
}
`;
