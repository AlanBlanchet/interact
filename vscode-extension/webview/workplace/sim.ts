/** The simulation. One clock, and bodies that obey it.
 *
 *  The view this replaced was a re-rendered SNAPSHOT: the host reassigned the whole document on
 *  every registry write, so every sprite was a brand new element with no memory, and the only
 *  motion possible was a one-shot replay of a difference between two loads — a person appearing
 *  already-arrived and sliding the last few hundred pixels into place. Between writes nothing
 *  happened at all. That is a slideshow of a workplace, and it is exactly what "no agent is moving
 *  to its destination" describes.
 *
 *  So this is a LOOP, not a diff. It holds a body per worker with a position, a facing and an
 *  INTENT, ticks them on `requestAnimationFrame`, and lets a snapshot change what a body WANTS
 *  rather than where it is. Nobody is ever placed; they are sent, and they walk.
 *
 *  Three rules keep it honest, because a simulation is the easiest place in a codebase to draw
 *  something the data never said:
 *
 *   - **Travel is caused.** A body walks because its zone CHANGED between two snapshots. Nobody
 *     wanders between rooms to look busy.
 *   - **The route is the building's.** A walk goes out of the room, along the storey's floor line,
 *     through the stairwell, along the other storey, and into the room — the same way a person
 *     would have to. No diagonal through a wall, no parabola over the roof.
 *   - **Ambient motion claims nothing.** Breathing, weight-shifting and a stroll inside your own
 *     room say "this building is inhabited". They never say a worker did something.
 */

export const SIM = String.raw`
/* ── the clock ────────────────────────────────────────────────────────────────────────────────
   One rAF for the whole scene. Everything periodic is phrased as a ratio of BEAT so the building
   keeps one tempo — the same 2.4s the stylesheet names, restated here because the engine has to
   do arithmetic with it. */
var BEAT = 2400;
/* A walking pace, in scene pixels per second. Chosen against the building rather than picked: at
   this speed the widest trip in a 1200px scene takes a little over four seconds, which is long
   enough to be watched and short enough that a busy team is not a parade. */
var PACE = 118;
var STAIR_PACE = 74;   /* stairs are slower than a corridor, and it reads */
/* No journey may take longer than this. A walking pace is right for the trips people actually
   watch, but the building's longest route — from the street, in through the door, up two flights
   — is about 1500px, which at a walking pace is twelve seconds of a worker being nowhere. The
   pace is therefore a FLOOR, not a constant: short hops stay at a stroll and the marathon is
   compressed until it fits a span somebody will still be looking at. */
var MAX_TRIP = 4200;
var TICK = { t: 0, dt: 0, on: false };

function hash(s) {
  var h = 2166136261;
  for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = (h * 16777619) >>> 0; }
  return h >>> 0;
}
/* A per-body constant in [0,1). Two people standing in the same room must not breathe in unison —
   that is the single loudest tell that you are looking at CSS and not at a room. */
function phaseOf(id) { return (hash(id) % 997) / 997; }

/* ── geometry: the building, measured ────────────────────────────────────────────────────────
   Read from the DOM rather than declared, so the routes stay correct through every layout the
   stylesheet can produce — a squeezed empty room, a bulging busy one, a narrow panel. */
var GEO = { scene: null, floors: [], rooms: {}, shaftX: 0, ok: false };
/* The rooms as they stood before the last swap. A snapshot changes the column widths — an empty
   room shrinks to a sliver, a busy one bulges — so measuring AFTER the swap and setting off from
   the result made a leaver start from wherever the layout moved their old room to, which on a
   room that emptied is a hundred pixels out. Captured before, used as the origin. */
var WAS = {};
function keepGeo() { if (GEO.ok) WAS = GEO.rooms; }

function measure() {
  var scene = document.querySelector(".wp-scene");
  if (!scene) { GEO.ok = false; return; }
  var box = scene.getBoundingClientRect();
  GEO.scene = scene;
  GEO.rooms = {};
  GEO.floors = [];

  var shafts = [];
  Array.prototype.forEach.call(document.querySelectorAll(".wp-shaft"), function (el) {
    var r = el.getBoundingClientRect();
    var deck = el.querySelector(".wp-deck");
    var d = (deck || el).getBoundingClientRect();
    shafts.push({
      storey: Number(el.getAttribute("data-storey")),
      x: r.left + r.width / 2 - box.left,
      y: d.bottom - 13 - box.top
    });
  });
  shafts.sort(function (a, b) { return a.storey - b.storey; });
  GEO.floors = shafts;
  GEO.shaftX = shafts.length ? shafts[0].x : 0;

  Array.prototype.forEach.call(document.querySelectorAll("[data-zone]"), function (el) {
    var zone = el.getAttribute("data-zone");
    if (zone === "lobby") return;
    var deck = el.querySelector(".wp-deck");
    if (!deck) return;
    var r = el.getBoundingClientRect();
    var d = deck.getBoundingClientRect();
    var floor = el.closest ? el.closest(".wp-floor") : null;
    GEO.rooms[zone] = {
      /* The walking line: the floorboards, not the middle of the room. Feet on the floor is the
         one thing a building drawn in section cannot get wrong. */
      y: d.bottom - 13 - box.top,
      left: r.left + 10 - box.left,
      right: r.right - 10 - box.left,
      x: r.left + r.width / 2 - box.left,
      storey: floor ? Number(floor.getAttribute("data-floor")) : 0,
      outside: !!el.classList && el.classList.contains("wp-outside")
    };
  });
  GEO.ok = !!(GEO.floors.length && GEO.rooms.entry);
}

/** The way a person would actually have to go. Out of the room to the stairs, up or down, along
 *  the other storey, into the room. Same-storey trips skip the shaft entirely and just walk the
 *  floor, which is what makes a short hop read differently from a long one. */
function route(from, to, a, b) {
  var ra = WAS[from] || GEO.rooms[from], rb = GEO.rooms[to];
  if (!ra || !rb) return [a, b];
  var pts = [a];
  /* Outside is reached through the door, never through the wall: everyone leaving or arriving
     goes via the entry room on the ground storey. */
  var viaDoor = (ra.outside !== rb.outside) && GEO.rooms.entry;
  /* Via the door: the entry room first, then the destination — the same both ways, since the
     door is where outside meets inside whichever direction you are going. */
  var legs = viaDoor ? [GEO.rooms.entry, rb] : [rb];
  var cur = ra;
  for (var i = 0; i < legs.length; i++) {
    var next = legs[i];
    if (next.storey !== cur.storey && !cur.outside && !next.outside) {
      pts.push({ x: GEO.shaftX, y: cur.y });
      pts.push({ x: GEO.shaftX, y: next.y, stair: true });
    } else if (next.storey !== cur.storey) {
      pts.push({ x: GEO.shaftX, y: next.y });
    }
    cur = next;
  }
  pts.push(b);
  return pts;
}

/* How far a traveller walks from the exact centre of the corridor, in scene px. Small on purpose:
   enough that two people are two people, not so much that anyone walks through a ceiling. */
var LANE = 5;

/* A route is computed per from/to PAIR, so everyone making the same trip at the same moment got
   the identical polyline and rendered exactly on top of each other — five bodies in one corridor,
   one visible. That is a reachable scene rather than a corner case (a batch of agents finishing
   together all return to the entry), and it defeats the whole point of the colour and the wake:
   knowing WHOSE journey you are watching.

   So each traveller keeps its own lane, offset from the shared line by a hash of its id — stable
   across every trip that person makes, and free of any coordination between bodies. Applied to
   the path itself, so the wake separates too rather than N streaks stacking into one.

   The room ENDPOINTS are left alone: they are where somebody's feet actually are, and nudging
   those would have people arriving beside their own nameplate. */
function lane(pts, id) {
  if (pts.length < 3) return pts;
  var offset = (phaseOf(id) - 0.5) * 2 * LANE;
  var out = [pts[0]];
  for (var i = 1; i < pts.length - 1; i++) {
    out.push({ x: pts[i].x, y: pts[i].y + offset, stair: pts[i].stair });
  }
  out.push(pts[pts.length - 1]);
  return out;
}

function legLength(p, q) {
  var dx = q.x - p.x, dy = q.y - p.y;
  return Math.sqrt(dx * dx + dy * dy);
}

/** A polyline plus the time each leg takes, so a body can be asked "where am I at t?" without
 *  re-deriving the path every frame. Stairs cost more per pixel — climbing is slower than
 *  walking, and a courier taking the stairs at corridor speed looks weightless. */
function plan(pts, id) {
  /* Nobody walks at exactly the same speed. Without this a group leaving together stays in
     lockstep for the whole trip — the lane offset separates them by a few px across the corridor,
     but they still move as one block, which is the thing that reads as wrong. A deterministic
     +/-9% off the shared pace pulls a crowd apart along the corridor as it walks, which is what
     a real one does, and keeps every traveller's own speed stable across trips. */
  var pace = PACE * (0.91 + 0.18 * (id ? phaseOf(id + ":pace") : 0.5));
  var stair = STAIR_PACE * (pace / PACE);
  var legs = [], total = 0;
  for (var i = 1; i < pts.length; i++) {
    var len = legLength(pts[i - 1], pts[i]);
    var speed = pts[i].stair ? stair : pace;
    var ms = (len / speed) * 1000;
    if (ms < 1) continue;
    legs.push({ a: pts[i - 1], b: pts[i], ms: ms, stair: !!pts[i].stair });
    total += ms;
  }
  /* Compressed as ONE ratio across every leg, so the stairs stay proportionally slower than the
     corridor and a hurried walk still reads as the same person moving. */
  if (total > MAX_TRIP) {
    var k = MAX_TRIP / total;
    for (var j = 0; j < legs.length; j++) legs[j].ms *= k;
    total = MAX_TRIP;
  }
  return { legs: legs, ms: total || 1 };
}

/** The polyline actually WALKED so far — the wake's shape. Distinct from at(), which answers
 *  only "where am I now": this is the whole route behind you, which is the part a reader can
 *  still catch AFTER the walker has gone past. */
function traversed(path, ms) {
  var pts = [], acc = 0;
  for (var i = 0; i < path.legs.length; i++) {
    var leg = path.legs[i];
    if (i === 0) pts.push(leg.a);
    if (ms >= acc + leg.ms) { pts.push(leg.b); acc += leg.ms; continue; }
    var u = leg.ms ? (ms - acc) / leg.ms : 1;
    pts.push({ x: leg.a.x + (leg.b.x - leg.a.x) * u, y: leg.a.y + (leg.b.y - leg.a.y) * u });
    return pts;
  }
  return pts;
}

function pathData(pts) {
  var d = "";
  for (var i = 0; i < pts.length; i++) d += (i ? "L" : "M") + pts[i].x.toFixed(1) + " " + pts[i].y.toFixed(1);
  return d;
}

function at(path, ms) {
  var acc = 0;
  for (var i = 0; i < path.legs.length; i++) {
    var leg = path.legs[i];
    if (ms <= acc + leg.ms) {
      var u = leg.ms ? (ms - acc) / leg.ms : 1;
      return {
        x: leg.a.x + (leg.b.x - leg.a.x) * u,
        y: leg.a.y + (leg.b.y - leg.a.y) * u,
        dx: leg.b.x - leg.a.x,
        stair: leg.stair
      };
    }
    acc += leg.ms;
  }
  var last = path.legs[path.legs.length - 1];
  return last
    ? { x: last.b.x, y: last.b.y, dx: last.b.x - last.a.x, stair: last.stair }
    : { x: 0, y: 0, dx: 0, stair: false };
}

/* ── bodies ───────────────────────────────────────────────────────────────────────────────────
   One per worker on screen. A body owns a POSITION and an INTENT; the DOM element is only where
   it is currently drawn. That inversion is the whole fix: a snapshot changes what a body wants,
   never where it is, so a re-render can no longer teleport anybody. */
var BODIES = {};      /* run_id -> body */
var TRAFFIC = null;   /* the overlay walkers and couriers are drawn on */
var PROTO = {};

function protoFor(kind, scale) {
  var src = PROTO[kind];
  if (!src) return null;
  var svg = src.cloneNode(true);
  var vb = (svg.getAttribute("viewBox") || "0 0 10 16").split(/\s+/);
  var w = Number(vb[2]) || 10, h = Number(vb[3]) || 16;
  svg.setAttribute("width", String(w * scale));
  svg.setAttribute("height", String(h * scale));
  return svg;
}

/** The traveller: a walking body on the traffic layer, wearing the worker's own colours.
 *  Cloned from one hidden prototype, so a person crossing the building is the same twenty
 *  rectangles as the person standing in the room — not a lookalike, and not a second asset. */
/* Colours a traveller has to CARRY rather than inherit. Each is declared by a .wp-worker rule in
   terms of --accent, which the pod supplies — and the walker leaves the pod. Taking the RESOLVED
   value rather than re-deriving it from the pod's accent is what keeps a report's lighter tint
   (the :not([data-depth="0"]) rule) intact: rebuilding from the accent alone would repaint every
   report as its lead the moment it stepped out of the room. */
var CARRIED = ["--c-shirt", "--c-badge", "--c-eye", "--c-mouth", "--c-ghost", "--c-ghost-ink"];

function makeWalker(el, scale) {
  var svg = protoFor("walk", scale);
  if (!svg || !TRAFFIC) return null;
  var host = document.createElement("div");
  host.className = "wp-travelling";
  /* Half the palette is inline on the worker (skin, hair, trousers) and copying the style
     attribute carries it. The SHIRT is not: .wp-worker resolves it from --accent, which is
     INHERITED from the enclosing pod — and a traveller is reparented onto the traffic layer,
     outside every pod. So the attribute alone dressed the walker in whatever accent happened to
     be in scope there: not a missing colour, another TEAM's colour — a confidently wrong signal
     in a view whose whole job is telling you whose journey you are watching. Resolved and pinned
     here, the same way the wake below already takes its hue from the pod. */
  host.setAttribute("style", el.getAttribute("style") || "");
  var worn = getComputedStyle(el);
  for (var i = 0; i < CARRIED.length; i++) {
    var value = worn.getPropertyValue(CARRIED[i]).trim();
    if (value) host.style.setProperty(CARRIED[i], value);
  }
  host.appendChild(svg);
  var shade = document.createElement("span");
  shade.className = "wp-shadow wp-travel-shadow";
  host.appendChild(shade);
  TRAFFIC.appendChild(host);
  return host;
}

/* ── catching the eye ─────────────────────────────────────────────────────────────────────────
   A walk that HAPPENS is not the same as a walk that is SEEN. One 30px figure crossing a scene
   holding a hundred still ones is a needle: the transform is correct and the reader still misses
   it, which was the whole of "no agent is moving to its destination". So a journey leaves two
   marks bigger than the walker.

   The WAKE is the route drawn behind them in their own pod's colour — it grows as they walk and
   fades once they arrive, so its length is the distance travelled and a long trip is a long
   streak. It also survives being missed: glance up two seconds late and the line still says
   somebody went from the Lab, up the stairs, into the Code room.

   The STIR is the rooms at either end brightening for a moment. A room is thousands of pixels
   against a sprite's few hundred, so it is the part caught in peripheral vision — and it reuses
   the lamp the building already lights occupied rooms with, rather than inventing a new signal. */
var WAKE = null;
function wakeLayer() {
  if (WAKE || !TRAFFIC) return WAKE;
  WAKE = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  WAKE.setAttribute("class", "wp-wake");
  TRAFFIC.appendChild(WAKE);
  return WAKE;
}

function stir(zone) {
  var room = zone && document.querySelector('[data-zone="' + zone + '"]');
  if (!room) return;
  room.classList.remove("is-stirring");
  void room.offsetWidth;                 /* restart the pulse if the room stirs twice in a row */
  room.classList.add("is-stirring");
  setTimeout(function () { room.classList.remove("is-stirring"); }, 900);
}

function bodyFor(el) {
  var id = el.getAttribute("data-run-id");
  var b = BODIES[id];
  if (!b) {
    b = BODIES[id] = {
      id: id,
      phase: phaseOf(id),
      zone: el.getAttribute("data-zone"),
      intent: "settled",
      face: 1,
      /* When this body was last seen to do something NEW. Ambient life keys off it, so a worker
         whose phrase keeps changing stays visibly alive even where the registry's own idle clock
         is unreliable. Starts at minus-forever, not at zero: a fresh page's clock starts near
         zero too, so zero meant "seen moving just now" and every genuinely stalled worker got
         thirty seconds of life it had not earned. */
      livelyAt: -1e9,
      travel: null,
      pace: 0
    };
  }
  b.el = el;
  return b;
}

/* ── ambient: the building is inhabited ──────────────────────────────────────────────────────
   None of this claims anything. It is the difference between a photograph of a room and a room.
   Every offset is sub-pixel-to-a-few-pixels and every period is a ratio of BEAT, so fifteen people
   never fall into step — the surest way to look like a stylesheet rather than a workplace. */
function ambient(b, t) {
  var el = b.el;
  if (!el || b.intent !== "settled") return;
  var status = el.getAttribute("data-status");
  var stalled = el.getAttribute("data-stalled") === "1";
  /* A body seen SAYING something new in the last half minute is working, whatever a clock says.
     This is an observation, not an override: the phrase changed, so the agent moved. */
  var lively = t - b.livelyAt < 30000;
  if (stalled && !lively) { paint(b, 0, 0, b.face, 0); return; }

  var p = b.phase;
  var y = 0, x = 0, lean = 0;

  if (status === "running") {
    /* At the desk: a slow weight shift, and a faster small lean that reads as typing. Two
       periods that do not divide each other, so the pair never repeats visibly. */
    var sway = Math.sin((t / (BEAT * 2.5)) * Math.PI * 2 + p * 6.283);
    var work = Math.sin((t / (BEAT * 0.5)) * Math.PI * 2 + p * 6.283);
    x = sway * 1.6;
    y = work > 0.86 ? -1 : 0;
    lean = work * 0.6;

    /* Every so often, get up and stroll a few steps inside your own room, then come back. It is
       the one ambient thing with a shape, and it is what stops a busy room reading as a diorama.
       Bounded to the room and to a handful of pixels: this is pacing, never a change of place. */
    var period = BEAT * (9 + (hash(b.id) % 11));       /* 21.6s – 45.6s, per person */
    var u = ((t + p * period) % period) / period;
    if (u < 0.22) {
      var s = Math.sin((u / 0.22) * Math.PI);           /* out and back, one arc */
      var reach = 14 + (hash(b.id + "r") % 12);
      var dir = (hash(b.id + "d") % 2) ? 1 : -1;
      x += s * reach * dir;
      if (s > 0.08) { b.face = (u < 0.11 ? dir : -dir); b.pace = 1; }
      else b.pace = 0;
    } else b.pace = 0;
  } else if (status === "done") {
    /* Finished, not dead. One slow breath — the smallest motion in the building, and the reason
       a team that has stopped no longer reads as a shelf of figurines. */
    y = Math.sin((t / (BEAT * 3)) * Math.PI * 2 + p * 6.283) > 0.7 ? -1 : 0;
  } else if (status === "error") {
    /* Slumped, and it stays slumped. The halo does the shouting. */
    y = 1;
  } else if (status === "foreign") {
    y = Math.sin((t / (BEAT * 4)) * Math.PI * 2 + p * 6.283) > 0.8 ? -1 : 0;
  }
  paint(b, x, y, b.face, lean);
}

function paint(b, x, y, face, lean) {
  var el = b.el;
  if (!el) return;
  var stage = el.querySelector(".wp-stage");
  if (!stage) return;
  stage.style.transform =
    "translate(" + x.toFixed(2) + "px," + y.toFixed(2) + "px)" +
    (face < 0 ? " scaleX(-1)" : "") +
    (lean ? " rotate(" + (lean * 1.1).toFixed(2) + "deg)" : "");
  el.classList.toggle("is-pacing", !!b.pace);
}


/* ── travel: somebody was SENT somewhere, so they walk there ─────────────────────────────────
   The only motion in this file that means anything. It fires when a worker's zone differs between
   two snapshots and never otherwise, and it takes as long as the distance takes at a walking pace
   — which is the point: you are meant to catch them in the corridor. */
function feetOf(el) {
  var box = GEO.scene.getBoundingClientRect();
  /* The FIGURE's bottom is under the nameplate and the "reports to" line, which is 20-30px below
     where the boots actually are — aim there and a traveller arrives standing in the floor. The
     stage is the sprite and nothing else. */
  var r = (el.querySelector(".wp-stage") || el).getBoundingClientRect();
  return { x: r.left + r.width / 2 - box.left, y: r.bottom - box.top };
}

function scaleOf(el) {
  var svg = el.querySelector(".wp-sprite");
  if (!svg) return 3;
  var vb = (svg.getAttribute("viewBox") || "0 0 10 16").split(/\s+/);
  var w = Number(svg.getAttribute("width")) || 30;
  return Math.max(2, Math.round(w / (Number(vb[2]) || 10)));
}

/** Send a body to the room it now belongs in. an explicit origin overrides where it sets off from, which is
 *  what a re-aimed walker needs: somebody turned around mid-corridor starts from the corridor,
 *  not from the room they left two seconds ago. */
function send(b, fromZone, origin) {
  if (!GEO.ok || !b.el) return false;
  var ra = WAS[fromZone] || GEO.rooms[fromZone];
  if (!ra) return false;
  var end = feetOf(b.el);
  var start = origin || { x: ra.x, y: ra.y };
  var path = plan(lane(route(fromZone, b.zone, start, end), b.id), b.id);
  if (!path.legs.length) return false;

  var walker = makeWalker(b.el, scaleOf(b.el));
  if (!walker) return false;
  b.intent = "travelling";
  /* The door opens for the people who actually go through it — anyone entering or leaving the
     building — and it opens while they are AT it, not on a proximity guess against a room's
     floor line (which is somewhere else entirely the moment two people wrap onto two rows). */
  var door = fromZone === "web" || b.zone === "web" || fromZone === "entry" || b.zone === "entry";
  var layer = wakeLayer();
  var wake = null;
  if (layer) {
    wake = document.createElementNS("http://www.w3.org/2000/svg", "path");
    /* The pod's colour, taken from the platform the worker stands on — so the streak crossing the
       building is the same hue as the team it belongs to, and two simultaneous journeys are
       telling you WHOSE they are. */
    var pod = b.el.closest ? b.el.closest(".wp-pod") : null;
    wake.style.setProperty("--accent", (pod && getComputedStyle(pod).getPropertyValue("--accent")) || "");
    layer.appendChild(wake);
  }
  b.travel = {
    path: path, t0: TICK.t, walker: walker, from: fromZone, dest: b.zone, door: door, wake: wake
  };
  stir(fromZone);
  /* They are not in the destination room yet, so they are not drawn in it. The cell keeps its
     space, which is why the room does not jump when they arrive. */
  b.el.classList.add("is-away");
  window.__wp.travels++;
  window.__wp.moved.push(b.id);
  return true;
}

function stepTravel(b, t) {
  var tr = b.travel;
  var ms = t - tr.t0;
  var p = at(tr.path, ms);
  var face = p.dx > 0.5 ? 1 : p.dx < -0.5 ? -1 : b.face;
  b.face = face;
  tr.walker.style.transform = "translate(" + p.x.toFixed(1) + "px," + p.y.toFixed(1) + "px)";
  tr.walker.classList.toggle("face-left", face < 0);
  tr.walker.classList.toggle("on-stairs", !!p.stair);
  if (tr.wake) tr.wake.setAttribute("d", pathData(traversed(tr.path, ms)));
  var e = GEO.rooms.entry;
  if (tr.door && e && p.x >= e.left - 26 && p.x <= e.right + 26) openDoor(t);
  if (ms >= tr.path.ms) {
    tr.walker.remove();
    b.el.classList.remove("is-away");
    b.el.classList.add("just-arrived");
    var el = b.el;
    setTimeout(function () { el.classList.remove("just-arrived"); }, 520);
    /* The wake outlives the walker by a beat. Arriving is the moment a reader is most likely to
       look up, and the route is the only thing that can still tell them where this person came
       from. */
    fadeWake(tr.wake);
    stir(b.zone);
    b.travel = null;
    b.intent = "settled";
  }
}

var DOOR_UNTIL = 0;
function openDoor(t) { DOOR_UNTIL = Math.max(DOOR_UNTIL, t + 900); }
/** Where a walker is standing right now, in scene coordinates — the start point for a journey
 *  that supersedes one already in progress. */
function walkerAt(b) {
  if (!b.travel) return null;
  var p = at(b.travel.path, TICK.t - b.travel.t0);
  return { x: p.x, y: p.y };
}

/** Let a route linger, then go. Removed outright it would blink out at the exact instant the
 *  reader's eye arrives at the destination. */
function fadeWake(wake) {
  if (!wake) return;
  wake.classList.add("is-spent");
  setTimeout(function () { if (wake.parentNode) wake.remove(); }, 900);
}

/** Stop a journey where it stands and put the body back in its cell. */
function halt(b) {
  if (b.travel && b.travel.walker) b.travel.walker.remove();
  if (b.travel) fadeWake(b.travel.wake);
  b.travel = null;
  b.intent = "settled";
  if (b.el) b.el.classList.remove("is-away");
}

function stepDoor(t) {
  var door = document.querySelector(".wp-door");
  if (door) door.classList.toggle("is-open", t < DOOR_UNTIL);
}

/* ── the post: an errand you can watch ───────────────────────────────────────────────────────
   A message between two agents used to be a note flying over the roof in a parabola. It read as a
   decoration, it crossed walls, and it was gone in a second. A message is somebody TAKING
   something to somebody: a runner leaves the sender, walks the building the way anyone would have
   to, arrives at the recipient's desk, hands it over, and goes. The recipient reacts, because
   otherwise the note flew past a person rather than to one.

   The runner is deliberately not one of the team — smaller, faceless, one flat tone — so the
   traffic in the corridor can never be mistaken for a worker changing rooms. */
var ERRANDS = [];
var QUEUE = [];
var MAX_ERRANDS = 2;

function personAt(id) { return document.querySelector('.wp-worker[data-run-id="' + id + '"]'); }

/* Each note gets its own number. The lane and pace below key on it, and keying on the PAIR alone
   was a real collision rather than a theoretical one: a back-and-forth between two agents puts two
   A->B notes on the road at once (MAX_ERRANDS allows exactly two), and identical from/to gave them
   an identical route, an identical lane and an identical pace — perfectly stacked, which is the
   defect lanes exist to remove. */
var ERRAND_N = 0;
function errand(fromId, toId, text) {
  QUEUE.push({ f: fromId, t: toId, x: text, n: ERRAND_N++ });
  if (QUEUE.length > 24) QUEUE.shift();
}

function startErrand(job, t) {
  var a = personAt(job.f), b = personAt(job.t);
  if (!a || !b || !GEO.ok || !TRAFFIC) return false;
  var pa = feetOf(a), pb = feetOf(b);
  var za = a.getAttribute("data-zone"), zb = b.getAttribute("data-zone");
  /* A courier gets a lane and a pace too: several notes crossing the building at once is the
     normal case, not an edge one, and stacked runners hide exactly how much talking is going on. */
  var carrier = job.f + ">" + job.t + "#" + job.n;
  var path = plan(lane(route(za, zb, pa, pb), carrier), carrier);
  if (!path.legs.length) {
    /* Same desk, or near enough: no journey to make, so the note simply changes hands and the
       two of them acknowledge it. Still watchable, and honest — nobody walked. */
    path = plan([pa, { x: pb.x, y: pb.y }], carrier);
    if (!path.legs.length) { react(b, t); return true; }
  }
  var svg = protoFor("run", 2);
  if (!svg) return false;
  var host = document.createElement("div");
  host.className = "wp-errand";
  host.appendChild(svg);
  var tag = document.createElement("span");
  tag.className = "wp-errand-word";
  tag.textContent = (job.x || "").slice(0, 34);
  host.appendChild(tag);
  TRAFFIC.appendChild(host);
  ERRANDS.push({ path: path, t0: t, el: host, to: b, done: false });
  window.__wp.notes++;
  return true;
}

function react(el, t) {
  if (!el) return;
  el.classList.add("has-post");
  setTimeout(function () { el.classList.remove("has-post"); }, 900);
}

function stepErrands(t) {
  while (ERRANDS.length < MAX_ERRANDS && QUEUE.length) {
    var job = QUEUE.shift();
    if (!startErrand(job, t)) break;
  }
  for (var i = ERRANDS.length - 1; i >= 0; i--) {
    var e = ERRANDS[i];
    var ms = t - e.t0;
    var p = at(e.path, ms);
    var face = p.dx > 0.5 ? 1 : p.dx < -0.5 ? -1 : 1;
    e.el.style.transform = "translate(" + p.x.toFixed(1) + "px," + (p.y - 2).toFixed(1) + "px)";
    e.el.classList.toggle("face-left", face < 0);
    if (ms >= e.path.ms && !e.done) {
      e.done = true;
      react(e.to, t);
      e.el.classList.add("is-handing");
    }
    /* A short hand-over at the desk, then the runner is gone. Leaving them standing there would
       turn the corridor into a crowd of couriers within a minute. */
    if (ms >= e.path.ms + 620) { e.el.remove(); ERRANDS.splice(i, 1); }
  }
}

/* ── the loop ─────────────────────────────────────────────────────────────────────────────── */
function frame(ts) {
  if (!TICK.on) return;
  /* A panel left open on a second monitor is the intended way to use this, so the loop has to be
     cheap when nobody is looking at it. Hidden means the tab is not composited at all: keep the
     clock advancing (so a walk resumes where it should) and skip the work. */
  if (document.hidden) { TICK.t = ts; requestAnimationFrame(frame); return; }
  TICK.t = ts;
  for (var id in BODIES) {
    var b = BODIES[id];
    if (!b.el || !b.el.isConnected) continue;
    if (b.intent === "travelling" && b.travel) stepTravel(b, ts);
    else ambient(b, ts);
  }
  stepErrands(ts);
  stepDoor(ts);
  requestAnimationFrame(frame);
}

`;
