/** How the document is wired to the data. The simulation itself is `sim.ts`.
 *
 *  The host renders the shell once — the map is a pure function of the company's departments and
 *  never changes when a person moves — and then posts the CAST on every refresh. The engine swaps
 *  that one element, re-binds each body to its new element by `data-run-id`, and keeps every
 *  position, facing and in-flight walk across the swap. Reassigning the whole document still
 *  works; it just costs the walk that was in flight.
 */
import { SIM } from "./sim";

export const SCRIPT =
  String.raw`
(function () {
  var POST = "wp.post.v2";
  /* How recent an exchange has to be for a FIRST load to act it out. One minute: long enough that
     opening the panel mid-conversation shows the conversation, short enough that it is never
     performing something the reader has already missed. */
  var FRESH_SECONDS = 60;
  var api = null;
  try { api = typeof acquireVsCodeApi === "function" ? acquireVsCodeApi() : null; } catch (e) { api = null; }

  function load(key) {
    try { var s = api && api.getState ? api.getState() : null; if (s && s[key]) return s[key]; } catch (e) {}
    try { var raw = sessionStorage.getItem(key); if (raw) return JSON.parse(raw); } catch (e) {}
    return null;
  }
  function save(key, value) {
    try {
      if (api && api.setState) { var s = (api.getState && api.getState()) || {}; s[key] = value; api.setState(s); }
    } catch (e) {}
    try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (e) {}
  }

  var still = false;
  try { still = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}

  /* Handles kept so the motion can be MEASURED rather than eyeballed. A video only ever shows
     that motion is PERCEPTIBLE; the numbers are what say it is correct. */
  window.__wp = {
    walks: 0, notes: 0, walking: 0, mode: "cold", bodies: null, world: null,
    tick: null, step: null, send: null, note: null, clearNotes: null, cam: null, still: still
  };
` +
  SIM +
  String.raw`
  /* ── binding a fresh cast to the bodies that already exist ───────────────────────────────── */

  function bind() {
    readWorld();
    readDoors();
    readSigns();
    CAST = document.querySelector(".wp-cast");
    var seen = {};
    var list = document.querySelectorAll(".wp-actor[data-run-id]");
    for (var i = 0; i < list.length; i++) {
      var b = bodyFor(list[i]);
      seen[b.id] = 1;
      /* A body mid-walk keeps walking through the swap: its element changed, its journey did not.
         That one line is what separates a simulation from a slideshow. */
      place(b, TICK.t);
    }
    for (var id in BODIES) if (!seen[id]) delete BODIES[id];
    window.__wp.bodies = BODIES;
    window.__wp.world = W;
    window.__wp.cam = CAM;
    camFit();
    lighting();
    speechLayout(TICK.t + 9999);
  }

  /* ── what a new snapshot MEANS ───────────────────────────────────────────────────────────── */

  function noteSpeech() {
    /* A phrase that CHANGED is the most reliable evidence an agent is alive — it is the agent's
       own output, not a clock. It does not open a bubble by itself any more: the bubbles are laid
       out by the engine and are on at rest. What a change buys is PRIORITY, so when more lines
       want a place than there are places, the ones that just changed get them.

       The version this replaces tried to pop a bubble here and could not: a local variable named
       "say" shadowed the function of the same name, so the call threw on every change and the
       only way speech ever appeared was hovering the exact right character. */
    var list = document.querySelectorAll(".wp-actor[data-run-id]");
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      var b = BODIES[el.getAttribute("data-run-id")];
      if (!b) continue;
      var line = el.getAttribute("data-say") || "";
      if (b.said === undefined) { b.said = line; continue; }
      if (line === b.said) continue;
      b.said = line;
      b.saidAt = TICK.t;
    }
  }

  function postRound(cold) {
    if (!CAST) return;
    var links = [];
    try { links = JSON.parse(CAST.getAttribute("data-links") || "[]"); } catch (e) { links = []; }
    var seenPost = load(POST) || [];
    save(POST, links.map(function (l) { return l.k; }).slice(-200));
    if (still) return;
    var known = {};
    for (var i = 0; i < seenPost.length; i++) known[seenPost[i]] = 1;
    var fresh = links.filter(function (l) { return !known[l.k]; });
    if (cold) {
      /* A cold open acts out what genuinely JUST happened and nothing else. An exchange with no
         age is UNKNOWN, never new: replaying an hour-old conversation as though it were
         happening is exactly the lie this view must not tell. */
      fresh = fresh.filter(function (l) { return typeof l.g === "number" && l.g <= FRESH_SECONDS; });
      fresh.sort(function (a, b) { return b.g - a.g; });
    }
    fresh.slice(0, 8).forEach(function (l) { errand(l.f, l.t, l.x); });
  }

  /* ── steering ────────────────────────────────────────────────────────────────────────────
     The camera follows the work on its own. A reader who wants to look somewhere else drags the
     floor or points at the plan in the corner, and it goes back to following a few seconds later
     — a view that has to be handed back is a view you stop using. */

  function steer() {
    var view = document.querySelector(".wp-view");
    var mini = document.querySelector(".wp-mini");
    if (mini) {
      mini.addEventListener("pointerdown", function (e) {
        var r = mini.getBoundingClientRect();
        camLookAt(
          ((e.clientX - r.left - 2) / (r.width - 4)) * W.cols * W.tile,
          ((e.clientY - r.top - 2) / (r.height - 4)) * W.rows * W.tile
        );
        e.stopPropagation();
      });
    }
    if (!view) return;
    var drag = null;
    view.addEventListener("pointerdown", function (e) {
      if (e.target.closest && e.target.closest(".wp-actor")) return;
      drag = { x: e.clientX, y: e.clientY, cx: CAM.x, cy: CAM.y };
      view.classList.add("is-dragging");
      try { view.setPointerCapture(e.pointerId); } catch (err) {}
    });
    view.addEventListener("pointermove", function (e) {
      if (!drag) return;
      CAM.x = drag.cx - (e.clientX - drag.x) / CAM.zoom;
      CAM.y = drag.cy - (e.clientY - drag.y) / CAM.zoom;
      CAM.free = TICK.t + 6000;
      camClamp();
      camApply();
    });
    var release = function () {
      if (!drag) return;
      drag = null;
      view.classList.remove("is-dragging");
    };
    view.addEventListener("pointerup", release);
    view.addEventListener("pointercancel", release);
  }

  /* ── clicking a character aims the rest of the panel at them ─────────────────────────────── */

  function pick(target) {
    var el = target && target.closest ? target.closest("[data-run-id]") : null;
    if (!el || !api) return;
    api.postMessage({ type: "select", run_id: el.getAttribute("data-run-id") });
  }
  document.addEventListener("click", function (e) { pick(e.target); });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var el = e.target && e.target.closest ? e.target.closest(".wp-actor[data-run-id]") : null;
    if (!el) return;
    e.preventDefault();
    pick(el);
  });

  /* ── boot ────────────────────────────────────────────────────────────────────────────────── */

  var booted = false;
  function boot() {
    bind();
    noteSpeech();
    steer();
    if (!booted) {
      booted = true;
      /* The clock runs even with motion reduced: it is what places the speech and holds the
         camera. Every ANIMATION is off in that mode, and decide() never sends anybody anywhere
         because the stylesheet is what would show it. */
      TICK.on = true;
      requestAnimationFrame(function (ts) { TICK.t = ts; frame(ts); });
      window.__wp.run = function (on) { TICK.on = !!on; return TICK.on; };
    }
    window.__wp.mode = (load(POST) || []).length ? "reloaded" : "cold";
    postRound(!(load(POST) || []).length);
  }

  window.addEventListener("resize", camFit);

  window.addEventListener("message", function (ev) {
    var msg = ev && ev.data;
    if (!msg || msg.type !== "team") return;
    swap(msg.html);
    bind();
    noteSpeech();
    window.__wp.mode = "live";
    postRound(false);
  });

  /* Take the cast out of whatever the host sent. The refresh is meant to carry ONLY the people,
     but a host that posts the whole scene must not break the building, so the cast is picked out
     of it either way. */
  function swap(html) {
    var mount = document.querySelector(".wp-stagebox");
    if (!mount || typeof html !== "string") return;
    var wrap = document.createElement("div");
    wrap.innerHTML = html;
    var next = wrap.querySelector(".wp-cast");
    if (!next && wrap.firstElementChild && wrap.firstElementChild.className === "wp-cast") {
      next = wrap.firstElementChild;
    }
    if (!next) return;
    var old = mount.querySelector(".wp-cast");
    if (old) mount.replaceChild(next, old);
    else mount.appendChild(next);
  }

  /* Exposed so a harness can drive the engine without a host. */
  window.__wpApply = function (html) {
    window.dispatchEvent(new MessageEvent("message", { data: { type: "team", html: html } }));
  };
  window.__wp.tick = TICK;
  window.__wp.note = function (fromId, toId, text) { errand(fromId, toId, text || "note"); pumpErrands(TICK.t); return LIVE; };
  window.__wp.clearNotes = function () { QUEUE.length = 0; return QUEUE.length; };
  /* Sending somebody on demand, so a walk can be inspected without racing the engine's own
     schedule. */
  window.__wp.send = function (id, x, y) {
    var b = BODIES[id];
    if (!b) return null;
    return sendTo(b, x, y, "walk") ? { path: b.path.length } : null;
  };
  window.__wp.at = function (id) {
    var b = BODIES[id];
    return b ? { x: b.x, y: b.y, mode: b.mode, walking: !!b.path, face: b.face } : null;
  };
  window.__wp.look = function (x, y) { camLookAt(x * W.tile, y * W.tile); return { x: CAM.x, y: CAM.y, zoom: CAM.zoom }; };
  /* A handle for looking at the whole building at once, which the camera deliberately never does.
     For a build loop and a critic, never for the product. */
  window.__wp.zoom = function (z) {
    CAM.zoom = z; CAM.free = TICK.t + 600000; camClamp(); camApply();
    return { zoom: CAM.zoom, span: camSpan(), world: { w: W.cols * W.tile, h: W.rows * W.tile } };
  };
  window.__wp.step = function (ts) {
    TICK.t = ts;
    var dt = 16;
    for (var id in BODIES) {
      var b = BODIES[id];
      if (!b.el) continue;
      if (b.path) stepWalk(b, dt); else decide(b, ts);
      place(b, ts);
    }
    pumpErrands(ts);
    camStep(dt);
    lighting();
    doors();
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
`;
