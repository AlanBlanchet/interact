/** The simulation: bodies that occupy tiles and walk between them.
 *
 *  The view before this one laid its people out with flexbox. That single fact was the whole
 *  defect: a character's position belonged to the document's layout engine, so it could never be
 *  anywhere else, so it could never WALK anywhere, and the only motion the surface could express
 *  was a few pixels of transform around a fixed slot. Ninety-nine percent of the time it was a
 *  still picture with a breathing animation on it.
 *
 *  So position moved into the engine. A body owns a tile coordinate; the DOM element is only where
 *  it happens to be drawn this frame. From that one inversion everything else follows:
 *
 *   - **Routes are computed, not guessed.** A breadth-first search over the walkability grid finds
 *     the way out of a room, along the corridor and in through another room's door. It cannot cut
 *     through a wall or stand inside a desk, because those cells are simply not in the graph.
 *   - **Movement has a cause and it is usually INTERACTION.** One agent messaging another sends
 *     the sender across the building to say it and back again. Nobody teleports and nobody is
 *     placed.
 *   - **Nothing is ever still.** On top of that, everyone has an errand loop of their own — get
 *     up, cross your room, look at something, come back — staggered per person, so at any instant
 *     several of the fifteen are mid-stride. That is the difference between a workplace and a
 *     photograph of one, and it does not depend on the data changing at all.
 *   - **Footfall is keyed to DISTANCE, not to a clock.** The frame flips every half tile walked,
 *     so a body that speeds up or slows down keeps its stride, which is what reads as weight.
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
   so there is nothing to read off a bounding box and nothing that can go stale when the panel is
   resized — which is exactly the class of bug the old measured routes kept producing. */
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
   Breadth-first over the four neighbours. The grid is about fifteen hundred cells, so an exact
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
   just left. Deterministic per body and per attempt, so nothing here needs a random source and a
   replay of the same tick draws the same building. */
function looseCell(room, id, n) {
  if (!room) return null;
  for (var tries = 0; tries < 12; tries++) {
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
  var around = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, 1]];
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
      phase: phaseOf(id)
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
   journey and settles out of it rather than snapping between still and moving. The stride is
   measured in DISTANCE walked, which is what keeps the feet under the person when the speed
   changes. */
function stepWalk(b, dt) {
  /* Anticipation and settle. Both are short: this is a person getting up, not a vehicle. */
  var want = PACE;
  if (b.walked < 0.35) want = PACE * (0.35 + (b.walked / 0.35) * 0.65);
  if (b.path.length - b.step <= 1) want = PACE * 0.55;
  b.speed += (want - b.speed) * Math.min(1, dt / 90);

  /* The frame's whole allowance, spent ACROSS waypoints rather than stopping at each one. A route
     through the doors is twenty-odd legs, and consuming only up to the next corner threw away a
     fraction of a frame at every one of them — measured as a dip from 3.6 to 1.3 tiles a second
     each time the walker turned. A body that hesitates at every corner is the difference between
     walking and being dragged along a path. */
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
      b.el.classList.add("is-saying");
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
   what is on the wall, and come back. It claims nothing — a wander inside your own room is not a
   statement that you did any work — and it is the reason the scene is never a photograph. */
function decide(b, t) {
  if (t < b.nextAt) return;
  if (b.mode === "delivering") {
    /* Said what they came to say. Go back to your own desk. */
    if (b.el) { b.el.classList.remove("is-talking"); b.el.classList.remove("is-saying"); }
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

/* ── rooms light up when somebody is in them ─────────────────────────────────────────────────
   Driven off where bodies ACTUALLY are rather than off the snapshot, so a room goes dark the
   moment its last person walks out of the door rather than when the next refresh lands. */
var LIT = {};
function lighting() {
  var now = {};
  for (var id in BODIES) {
    var b = BODIES[id];
    if (!b.el || !b.el.isConnected) continue;
    for (var i = 0; i < W.rooms.length; i++) {
      var r = W.rooms[i];
      if (b.x >= r.x && b.x < r.x + r.w && b.y >= r.y && b.y < r.y + r.h) { now[r.i] = 1; break; }
    }
  }
  for (var k in now) {
    if (LIT[k]) continue;
    var on = document.querySelector('.wp-rm[data-room="' + cssq(k) + '"]');
    if (on) on.setAttribute("data-lit", "1");
  }
  for (var k2 in LIT) {
    if (now[k2]) continue;
    var off = document.querySelector('.wp-rm[data-room="' + cssq(k2) + '"]');
    if (off) off.setAttribute("data-lit", "0");
  }
  LIT = now;
}
function cssq(s) { return String(s).replace(/["\\]/g, "\\$&"); }

/* ── the post: an interaction is a WALK ──────────────────────────────────────────────────────
   The one thing Alan asked for by name — make them move when interacting. A message is not a
   line drawn between two boxes and not a note flying over the roof: the sender gets up, walks the
   corridors to wherever the recipient is standing, says it, and walks back. Two people at the
   same desk simply turn to each other. */
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
  if (!TICK.on) return;
  if (document.hidden) { TICK.t = ts; requestAnimationFrame(frame); return; }
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
  lighting();
  window.__wp.walking = busy;
  requestAnimationFrame(frame);
}
`;
