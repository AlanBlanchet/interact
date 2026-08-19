/** How the document is wired to the data. The simulation itself is `sim.ts`.
 *
 *  The host renders the shell once — the tilemap is a pure function of the company's departments
 *  and never changes when a person moves — and then posts the CAST on every refresh. The engine
 *  swaps that one element, re-binds each body to its new element by `data-run-id`, and keeps every
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
    tick: null, step: null, send: null, note: null, clearNotes: null, still: still
  };
` +
  SIM +
  String.raw`
  /* ── binding a fresh cast to the bodies that already exist ───────────────────────────────── */

  function bind() {
    readWorld();
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
    fit();
    lighting();
  }

  /* ── the building is drawn at a fixed tile size, then fitted to the panel ─────────────────
     A floor plan has a shape; letting it reflow would be the flexbox mistake again in another
     costume. So it is laid out once at its true size and scaled as ONE object, which keeps every
     tile, every sprite and every route in exact proportion at any panel width. */
  function fit() {
    var box = document.querySelector(".wp-view");
    var stage = document.querySelector(".wp-stagebox");
    if (!box || !stage) return;
    var w = stage.offsetWidth, h = stage.offsetHeight;
    if (!w || !h) return;
    /* The room left for the picture, measured against the WINDOW rather than against the box —
       the box's own height is set by this function, so reading it back is a loop that pins the
       scale at whatever it was first given and the building never grows to fill the panel. */
    var top = box.getBoundingClientRect().top;
    var legend = document.querySelector(".wp-legend");
    var below = legend ? legend.offsetHeight + 18 : 24;
    var room = Math.max(220, window.innerHeight - top - below);
    /* The WIDTH comes from the parent for the same reason the height comes from the window: this
       function sets the box's own width, so measuring the box measures the last answer. */
    var avail = (box.parentElement ? box.parentElement.clientWidth : window.innerWidth) - 4;
    var k = Math.min(avail / w, room / h);
    /* Snapped to quarters. A pixel tile drawn at an arbitrary fraction loses its edges, and the
       whole premise of the substrate is that the edges are hard. */
    /* Snapped to quarters: a pixel tile drawn at an arbitrary fraction loses its edges, and the
       whole premise of the substrate is that the edges are hard. Floored at a half, because below
       that a character is nine pixels wide and the panel stops being worth looking at — a narrow
       side bar PANS across the building instead of shrinking it into a postage stamp. */
    k = Math.max(0.5, Math.min(2, Math.floor(k * 4) / 4));
    stage.style.transform = "scale(" + k.toFixed(4) + ")";
    box.style.height = Math.ceil(h * k) + "px";
    box.style.width = Math.min(avail, Math.ceil(w * k)) + "px";
    window.__wp.scale = k;
  }

  /* ── what a new snapshot MEANS ───────────────────────────────────────────────────────────── */

  function speak() {
    /* A phrase that changed is the most reliable evidence an agent is alive — it is the agent's
       own output, not a clock. It pops the line above their head for a few seconds and lights the
       faculty it belongs to, then the character goes back to carrying its own state. */
    var list = document.querySelectorAll(".wp-actor[data-run-id]");
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      var b = BODIES[el.getAttribute("data-run-id")];
      if (!b) continue;
      var say = el.getAttribute("data-say") || "";
      if (b.said === undefined) { b.said = say; continue; }
      if (say === b.said) continue;
      b.said = say;
      if (still) continue;
      say(el);
    }
  }

  /* At most three lines of speech on screen at once, oldest dismissed first.
     A whole team changing phrase in the same refresh put a paper box over every head and the
     words out-massed the characters again — which was the original complaint about this view,
     rediscovered in a new costume. The faculty glyphs carry what is PERMANENTLY true about a
     character; speech is an event and behaves like one. */
  var SAYING = [];
  function say(el) {
    if (SAYING.indexOf(el) >= 0) return;
    SAYING.push(el);
    el.classList.add("is-saying");
    while (SAYING.length > 3) SAYING.shift().classList.remove("is-saying");
    setTimeout(function () {
      var i = SAYING.indexOf(el);
      if (i >= 0) SAYING.splice(i, 1);
      el.classList.remove("is-saying");
    }, 5200);
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
         happening is exactly the lie this view must not tell. Oldest first, so a burst of
         messages arrives in the order it was said. */
      fresh = fresh.filter(function (l) { return typeof l.g === "number" && l.g <= FRESH_SECONDS; });
      fresh.sort(function (a, b) { return b.g - a.g; });
    }
    fresh.slice(0, 8).forEach(function (l) { errand(l.f, l.t, l.x); });
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
    speak();
    if (!still && !booted) {
      booted = true;
      TICK.on = true;
      requestAnimationFrame(function (ts) { TICK.t = ts; frame(ts); });
    }
    window.__wp.mode = (load(POST) || []).length ? "reloaded" : "cold";
    postRound(!(load(POST) || []).length);
  }

  window.addEventListener("resize", fit);

  window.addEventListener("message", function (ev) {
    var msg = ev && ev.data;
    if (!msg || msg.type !== "team") return;
    swap(msg.html);
    bind();
    speak();
    window.__wp.mode = "live";
    postRound(false);
  });

  /* Take the cast out of whatever the host sent. The refresh is meant to carry ONLY the people —
     the tilemap is a function of the company's departments and does not change when somebody
     walks — but a host that posts the whole scene must not break the building, so the cast is
     picked out of it either way. */
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
     schedule — the reason the last round's traveller bug stayed invisible was that every check
     waited for a spontaneous trip. */
  window.__wp.send = function (id, x, y) {
    var b = BODIES[id];
    if (!b) return null;
    return sendTo(b, x, y, "walk") ? { path: b.path.length } : null;
  };
  window.__wp.at = function (id) {
    var b = BODIES[id];
    return b ? { x: b.x, y: b.y, mode: b.mode, walking: !!b.path, face: b.face } : null;
  };
  window.__wp.step = function (ts) { TICK.t = ts; frame.__manual = 1; var dt = 16; for (var id in BODIES) { var b = BODIES[id]; if (!b.el) continue; if (b.path) stepWalk(b, dt); else decide(b, ts); place(b, ts); } pumpErrands(ts); lighting(); };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
`;
