/** How the document is wired to the data. The simulation itself is `sim.ts`.
 *
 *  There are two ways this view can be driven, and it supports both on purpose.
 *
 *  **Live.** The host renders the shell once and then posts `{type:"team", html, state}` on every
 *  refresh. The engine swaps the mount's markup, re-binds each body to its new element by
 *  `data-run-id`, and keeps every position, facing and in-flight walk across the swap. The clock
 *  never stops, so the building is continuously alive and a worker sent to another room is watched
 *  all the way there.
 *
 *  **Reloaded.** The host reassigns `webview.html` wholesale, as it did for the whole first arc.
 *  Every element is then brand new with no memory, so the engine recovers the previous snapshot
 *  from `vscode.setState()` and re-derives who moved. Motion is still real — the same route, the
 *  same walk cycle, the same pace — but the ambient loop restarts on every write, and a walk that
 *  was in flight is replayed rather than continued.
 *
 *  The difference matters and is stated here rather than hidden: live is a workplace, reloaded is
 *  a workplace being interrupted. The engine does not pretend the second is the first.
 */
import { SIM } from "./sim";

export const SCRIPT =
  String.raw`
(function () {
  var KEY = "wp.seen.v2";
  /* How recent an exchange has to be for a FIRST load to act it out. One minute: long enough that
     opening the panel while the team is mid-conversation shows the conversation, short enough
     that it is never narrating something the reader has missed. */
  var FRESH_SECONDS = 60;
  var POST = "wp.post.v1";
  var api = null;
  try { api = typeof acquireVsCodeApi === "function" ? acquireVsCodeApi() : null; } catch (e) { api = null; }

  function load(key) {
    try {
      var s = api && api.getState ? api.getState() : null;
      if (s && s[key]) return s[key];
    } catch (e) {}
    try {
      var raw = sessionStorage.getItem(key);
      if (raw) return JSON.parse(raw);
    } catch (e) {}
    return null;
  }

  function save(key, value) {
    try {
      if (api && api.setState) {
        var s = (api.getState && api.getState()) || {};
        s[key] = value;
        api.setState(s);
      }
    } catch (e) {}
    try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (e) {}
  }

  var still = false;
  try { still = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}

  /* Handles kept so the motion can be MEASURED rather than eyeballed: a caller can pause the loop
     and step it, or read a body's position straight off the engine. A video is only ever evidence
     that motion is PERCEPTIBLE; the numbers are what say it is correct. */
  window.__wp = {
    travels: 0, flashes: 0, notes: 0, moved: [], anims: [],
    mode: "cold", bodies: null, geo: null, tick: null, step: null, note: null,
    clearNotes: null,
    /* Sending someone on a journey ON DEMAND, so a traveller can be inspected without racing the
       sim's own schedule. The colour a walker wears is only wrong WHILE it walks, and waiting for
       a spontaneous trip is how that stayed invisible. */
    send: null
  };
` +
  SIM +
  String.raw`
  /* ── binding a fresh set of elements to the bodies that already exist ────────────────────── */

  function bind() {
    var mount = document.getElementById("wp-mount") || document;
    TRAFFIC = mount.querySelector(".wp-traffic");
    if (TRAFFIC) {
      PROTO = {};
      Array.prototype.forEach.call(TRAFFIC.querySelectorAll(".wp-proto"), function (holder) {
        var svg = holder.querySelector("svg");
        if (svg) PROTO[holder.getAttribute("data-proto")] = svg;
      });
    }
    measure();
    var seen = {};
    Array.prototype.forEach.call(mount.querySelectorAll(".wp-worker[data-run-id]"), function (el) {
      var b = bodyFor(el);
      seen[b.id] = 1;
      /* A body mid-walk keeps walking through the swap: its element changed, its journey did not.
         This is the single line that separates a simulation from a slideshow. */
      if (b.intent === "travelling") el.classList.add("is-away");
    });
    /* Somebody who is no longer in the room takes their walker with them. */
    for (var id in BODIES) {
      if (seen[id]) continue;
      var gone = BODIES[id];
      if (gone.travel && gone.travel.walker) gone.travel.walker.remove();
      delete BODIES[id];
    }
    window.__wp.bodies = BODIES;
    window.__wp.geo = GEO;
  }

  /* ── what a new snapshot MEANS ───────────────────────────────────────────────────────────── */

  function snapshot() {
    var now = {};
    var mount = document.getElementById("wp-mount") || document;
    Array.prototype.forEach.call(mount.querySelectorAll(".wp-worker[data-run-id]"), function (el) {
      now[el.getAttribute("data-run-id")] = {
        z: el.getAttribute("data-zone"),
        a: (el.querySelector(".wp-bubble") || {}).textContent || ""
      };
    });
    return now;
  }

  /** Apply a snapshot against the last one. Nobody is placed here — they are SENT, and the loop
   *  walks them. a null "before" means a cold open: there is no evidence anybody moved, so nobody
   *  does, and the room's life comes from the ambient loop instead of from an invented journey. */
  function apply(before) {
    var now = snapshot();
    save(KEY, now);

    var moved = 0;
    for (var id in now) {
      var b = BODIES[id];
      if (!b) continue;
      var was = before && before[id];
      var zone = now[id].z;
      var walking = b.intent === "travelling" && !!b.travel;
      var fromZone = walking ? b.travel.from : (was && was.z);
      /* A phrase that changed is the most reliable evidence a worker is alive — more reliable
         than any clock, because it is the agent's own output. Recorded whether or not it is
         flashed, so ambient life can lean on it. */
      if (was && was.a && was.a !== now[id].a) {
        b.livelyAt = TICK.t;
        flash(b.el);
      }
      b.zone = zone;
      if (still) continue;
      /* Already on their way to exactly there: leave them alone. The host re-renders every time
         the registry moves, which on a busy team is several times a second — restarting a walk on
         each of those is how a walk becomes a stutter. */
      if (walking && b.travel.dest === zone) continue;
      /* Superseded. Stop the journey WHERE IT IS and start the new one from that spot, so
         somebody re-aimed mid-corridor turns around rather than teleporting back to the room they
         left. Without this a snapshot arriving mid-walk left the body hidden and its walker
         heading for a destination nobody was going to any more. */
      var origin = null;
      if (walking) { origin = walkerAt(b); halt(b); }
      if (!fromZone) continue;
      if (moved >= 10) continue;   /* a whole team moving at once must read as people, not confetti */
      if (fromZone === zone) {
        /* They set out, and the next snapshot says they belong where they started — the errand
           was over before they got there. Walk them BACK from the corridor rather than snapping
           them into place, which is the teleport this whole engine exists to remove. */
        if (origin) send(b, zone, origin);
        continue;
      }
      if (send(b, fromZone, origin)) moved++;
    }
  }

  function flash(el) {
    var bubble = el && el.querySelector(".wp-bubble");
    if (!bubble || still) return;
    window.__wp.flashes++;
    bubble.animate(
      [
        { transform: "translateY(2px)", filter: "brightness(1.6)" },
        { transform: "translateY(0)", filter: "brightness(1)" }
      ],
      { duration: 340, easing: "cubic-bezier(.22,1,.32,1)" }
    );
  }

  /* ── the post: which exchanges are NEW ───────────────────────────────────────────────────── */

  function postRound(cold) {
    var mount = document.getElementById("wp-mount") || document;
    var bag = mount.querySelector(".wp-post");
    var links = [];
    try { links = JSON.parse((bag && bag.getAttribute("data-links")) || "[]"); } catch (e) { links = []; }
    var seenPost = load(POST) || [];
    save(POST, links.map(function (l) { return l.k; }).slice(-200));
    if (still) return;
    var known = {};
    seenPost.forEach(function (k) { known[k] = 1; });
    var fresh = links.filter(function (l) { return !known[l.k]; });
    if (cold) {
      /* A cold open now carries what genuinely JUST happened, and nothing else. An exchange with
         no age is UNKNOWN, never new — messages recorded before the stamp existed have no claim
         to be live, and replaying an hour-old conversation as if it were happening is exactly the
         lie this view must not tell. Oldest first, so a burst arrives in the order it was said. */
      fresh = fresh.filter(function (l) { return typeof l.g === "number" && l.g <= FRESH_SECONDS; });
      fresh.sort(function (a, b) { return b.g - a.g; });
    }
    fresh.slice(0, 8).forEach(function (l) { errand(l.f, l.t, l.x); });
  }

  /* ── clicking a worker aims the rest of the panel at them ────────────────────────────────── */

  function pick(target) {
    var el = target && target.closest ? target.closest("[data-run-id]") : null;
    if (!el || !api) return;
    api.postMessage({ type: "select", run_id: el.getAttribute("data-run-id") });
  }
  document.addEventListener("click", function (e) { pick(e.target); });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var el = e.target && e.target.closest ? e.target.closest(".wp-worker[data-run-id]") : null;
    if (!el) return;
    e.preventDefault();
    pick(el);
  });

  /* ── boot ────────────────────────────────────────────────────────────────────────────────── */

  var booted = false;
  function boot() {
    var before = load(KEY);
    bind();
    /* The clock starts before the first snapshot is applied, so a walk begins on a real frame
       time rather than at zero — which is what let a reloaded document replay a journey with a
       negative age and finish it instantly. */
    if (!still && !booted) {
      booted = true;
      TICK.on = true;
      requestAnimationFrame(function (ts) { TICK.t = ts; frame(ts); });
    }
    window.__wp.mode = before ? "reloaded" : "cold";
    apply(before);
    postRound(!(load(POST) || []).length);
  }

  window.addEventListener("resize", function () { measure(); });

  /* The live channel. The host renders the shell once and then sends the scene; the engine keeps
     running across every swap. */
  window.addEventListener("message", function (ev) {
    var msg = ev && ev.data;
    if (!msg || msg.type !== "team") return;
    var mount = document.getElementById("wp-mount");
    var before = snapshot();
    keepGeo();
    if (mount && typeof msg.html === "string") mount.innerHTML = msg.html;
    bind();
    window.__wp.mode = "live";
    apply(before);
    postRound(false);
  });

  /* Exposed so a harness can drive the engine without a host. */
  window.__wpApply = function (html) {
    var mount = document.getElementById("wp-mount");
    var before = snapshot();
    keepGeo();
    if (mount && typeof html === "string") mount.innerHTML = html;
    bind();
    window.__wp.mode = "live";
    apply(before);
    postRound(false);
  };
  window.__wp.tick = TICK;
  /* Sending a NOTE on demand, the courier twin of send() below. Couriers get the same lane and
     pace treatment as travellers, and "verified by reading the code" is how the traveller bug got
     shipped in the first place — this makes the courier path drivable too. */
  window.__wp.note = function (fromId, toId, text) {
    errand(fromId, toId, text || "note");
    stepErrands(TICK.t);
    return ERRANDS.length;
  };
  /* Clearing the road before a measurement. Without it the scene's OWN notes occupy both of the
     MAX_ERRANDS slots, so a test's couriers are silently never dispatched and it ends up measuring
     the fixture's traffic instead of its own — which is exactly how a courier test passed twice
     against a reverted fix. */
  window.__wp.clearNotes = function () {
    QUEUE.length = 0;
    for (var i = ERRANDS.length - 1; i >= 0; i--) { ERRANDS[i].el.remove(); ERRANDS.splice(i, 1); }
    return ERRANDS.length;
  };
  window.__wp.send = function (id, zone) {
    var b = BODIES[id];
    if (!b) return null;
    var from = b.zone;
    b.zone = zone;
    return send(b, from) ? b.travel : null;
  };
  window.__wp.step = function (ts) { TICK.t = ts; for (var id in BODIES) { var b = BODIES[id]; if (b.intent === "travelling" && b.travel) stepTravel(b, ts); else ambient(b, ts); } stepErrands(ts); stepDoor(ts); };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
`;
