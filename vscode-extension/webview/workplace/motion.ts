/** The only script in the document, and it exists for one reason: a worker changing rooms must
 *  WALK there.
 *
 *  The host rebuilds this whole document every time the registry changes, so every sprite is a
 *  brand new element with no memory of where it stood a second ago — which is exactly how a
 *  "workplace" turns into a slideshow of teleporting people. So the document remembers for
 *  itself: it persists each run's room, and on the next load anyone whose room changed starts
 *  displaced by the distance between the two rooms and walks the gap closed. The motion is real
 *  and it is EARNED — nobody moves unless the data says they moved.
 *
 *  The same trick carries the second live thing: `activity` changes about once a second while an
 *  agent works, and a line of text quietly swapping underneath you reads as nothing at all, so a
 *  changed phrase flashes its bubble.
 */

export const SCRIPT = String.raw`
(function () {
  var KEY = "wp.seen.v1";
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

  var people = Array.prototype.slice.call(document.querySelectorAll(".wp-worker[data-run-id]"));
  var now = {};
  people.forEach(function (el) {
    now[el.getAttribute("data-run-id")] = {
      z: el.getAttribute("data-zone"),
      a: (el.querySelector(".wp-bubble") || {}).textContent || ""
    };
  });

  var before = load(KEY);
  save(KEY, now);

  var still = false;
  try { still = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}

  /* ── clicking a worker aims the rest of the panel at them ───────────────────────────────── */
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

  /* Handles kept so the motion can be MEASURED rather than eyeballed: a caller can pause one
     and step its currentTime to read the velocity profile straight off the transform. */
  window.__wp = { travels: 0, flashes: 0, notes: 0, moved: [], anims: [] };

  var scene = document.querySelector(".wp-scene");
  var decks = {};
  Array.prototype.slice.call(document.querySelectorAll("[data-zone]")).forEach(function (room) {
    var deck = room.querySelector(".wp-deck");
    if (deck) decks[room.getAttribute("data-zone")] = deck;
  });

  function centre(el) {
    var r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.bottom - 14 };
  }

  var trail = null;
  function trailLayer() {
    if (trail || !scene) return trail;
    trail = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    trail.setAttribute("class", "wp-trail");
    scene.appendChild(trail);
    return trail;
  }

  /* A walker at a time, lightly staggered: fifteen people setting off on the same frame reads as
     a glitch, a fifth of a second apart reads as people. Capped, because a snapshot where the
     whole team moved at once must not turn into a fireworks display. */
  var movers = (!before || still) ? [] : people.filter(function (el) {
    var id = el.getAttribute("data-run-id");
    var was = before[id];
    return was && was.z && was.z !== el.getAttribute("data-zone") && decks[was.z];
  }).slice(0, 8);

  movers.forEach(function (el, i) {
    var id = el.getAttribute("data-run-id");
    var from = centre(decks[before[id].z]);
    var to = centre(el);
    var dx = Math.round(from.x - to.x);
    var dy = Math.round(from.y - to.y);
    if (!dx && !dy) return;

    var delay = i * 70;
    el.classList.add("is-walking");
    var walk = el.animate(
      [
        { transform: "translate(" + dx + "px," + dy + "px)" },
        { transform: "translate(" + Math.round(dx * 0.42) + "px," + (Math.round(dy * 0.42) - 5) + "px)", offset: 0.55 },
        { transform: "translate(0px, 0px)" }
      ],
      {
        duration: 820,
        delay: delay,
        easing: "cubic-bezier(.34,.02,.2,1)",
        fill: "backwards",
        id: "wp-travel-" + id
      }
    );
    window.__wp.travels++;
    window.__wp.moved.push(id);
    window.__wp.anims.push(walk);
    walk.finished.then(function () { el.classList.remove("is-walking"); }).catch(function () {
      el.classList.remove("is-walking");
    });

    var layer = trailLayer();
    if (!layer) return;
    var box = scene.getBoundingClientRect();
    var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    var x1 = from.x - box.left, y1 = from.y - box.top;
    var x2 = to.x - box.left, y2 = to.y - box.top;
    path.setAttribute("d", "M" + x1 + " " + y1 + " Q" + (x1 + x2) / 2 + " " + (Math.min(y1, y2) - 16) + " " + x2 + " " + y2);
    path.style.setProperty("--accent", getComputedStyle(el.parentElement || el).getPropertyValue("--accent") || "");
    layer.appendChild(path);
    path.animate(
      [{ opacity: 0 }, { opacity: 0.75, offset: 0.3 }, { opacity: 0 }],
      { duration: 1200, delay: delay, easing: "cubic-bezier(.22,1,.32,1)", id: "wp-trail-" + id }
    ).finished.then(function () { path.remove(); }).catch(function () { path.remove(); });
  });

  /* ── a changed phrase ───────────────────────────────────────────────────────────────────── */

  if (before && !still) people.forEach(function (el) {
    var id = el.getAttribute("data-run-id");
    var was = before[id];
    var bubble = el.querySelector(".wp-bubble");
    if (!was || !bubble || !was.a || was.a === bubble.textContent) return;
    window.__wp.flashes++;
    bubble.animate(
      [
        { transform: "translateY(2px)", filter: "brightness(1.6)" },
        { transform: "translateY(0)", filter: "brightness(1)" }
      ],
      { duration: 340, easing: "cubic-bezier(.22,1,.32,1)", id: "wp-said-" + id }
    );
  });
  /* ── the post ───────────────────────────────────────────────────────────────────────────────
     A message between two agents is CARRIED. A line between two boxes would be the node graph
     this whole view exists not to be, and worse, it would hang there forever describing something
     that happened once. A note that crosses the building and is gone says "they just spoke".
     Only exchanges that are NEW since the last draw are carried, so a refresh never re-announces
     a conversation that already happened. */

  var bag = document.querySelector(".wp-post");
  var art = bag && bag.querySelector(".wp-note-art svg");
  var links = [];
  try { links = JSON.parse((bag && bag.getAttribute("data-links")) || "[]"); } catch (e) { links = []; }

  var seenPost = load(POST) || [];
  var keys = links.map(function (l) { return l.k; });
  save(POST, keys.slice(-200));

  if (!scene || !art || still) return;
  var known = {};
  seenPost.forEach(function (k) { known[k] = 1; });
  /* No memory at all means a cold open: mark everything as known rather than firing a dozen
     couriers at a reader who has not looked away yet. */
  var cold = !seenPost.length;

  function personAt(id) { return document.querySelector('.wp-worker[data-run-id="' + id + '"]'); }

  var fresh = cold ? [] : links.filter(function (l) { return !known[l.k]; }).slice(0, 6);

  fresh.forEach(function (l, i) {
    var a = personAt(l.f), b = personAt(l.t);
    if (!a || !b) return;
    var box = scene.getBoundingClientRect();
    var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    var x1 = ra.left + ra.width / 2 - box.left, y1 = ra.top + 18 - box.top;
    var x2 = rb.left + rb.width / 2 - box.left, y2 = rb.top + 18 - box.top;

    var note = art.cloneNode(true);
    note.setAttribute("class", "wp-courier");
    note.style.left = "0px";
    note.style.top = "0px";
    scene.appendChild(note);
    window.__wp.notes++;

    var lift = Math.min(46, 18 + Math.abs(x2 - x1) * 0.16);
    var mx = (x1 + x2) / 2, my = Math.min(y1, y2) - lift;
    var anim = note.animate(
      [
        { transform: "translate(" + x1 + "px," + y1 + "px) scale(.6)", opacity: 0 },
        { transform: "translate(" + mx + "px," + my + "px) scale(1)", opacity: 1, offset: 0.5 },
        { transform: "translate(" + x2 + "px," + y2 + "px) scale(.7)", opacity: 0 }
      ],
      {
        duration: 1100,
        delay: 140 + i * 130,
        easing: "cubic-bezier(.4,0,.5,1)",
        id: "wp-post-" + i
      }
    );
    var landed = false;
    anim.finished.then(function () {
      note.remove();
      if (landed) return;
      landed = true;
      /* The recipient reacts. Without it the note is a decoration that flew past somebody. */
      b.animate(
        [{ transform: "translateY(0)" }, { transform: "translateY(-3px)", offset: 0.4 }, { transform: "translateY(0)" }],
        { duration: 300, easing: "cubic-bezier(.22,1,.32,1)", id: "wp-got-" + i }
      );
    }).catch(function () { note.remove(); });
  });
})();
`;
