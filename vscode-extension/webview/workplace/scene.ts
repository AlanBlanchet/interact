/** The scene: a building drawn in cutaway, and the outdoors beside it.
 *
 *  The conventional answer to "show me my agents" is a node graph or a grid of status cards. Both
 *  were built and both were wrong for this: a graph answers "who launched whom" and never "what is
 *  my team DOING", and cards make nine boxes that look like every dashboard ever shipped. So the
 *  rooms share walls and a roof — no gaps, one continuous elevation — because that single decision
 *  is what makes eight regions read as a PLACE rather than as eight panels.
 *
 *  Everything else follows from it. A room nobody is in goes dark, so "where is everyone" is
 *  answered by the shape of the light before a label is read. A researcher genuinely leaves through
 *  the door and stands outside under the sky. And when two agents talk, a note is CARRIED between
 *  them — the one thing a wire between boxes could never be, which is why the wire was refused.
 */
import { ZONES } from "../../src/team";
import type { TeamState, Worker, ZoneId } from "../../src/team";
import { closeSheet, draw, drawFrames, openSheet } from "./pixels";
import {
  CLOUD,
  DISC,
  DOOR,
  GHOST_PAL,
  HORIZON,
  NOTE,
  POSE_MOVE,
  POSE_REST,
  POSE_RUN_A,
  POSE_RUN_B,
  POSE_WALK_A,
  POSE_WALK_B,
  PROPS,
  RUNNER_PAL,
  SKIN_PAL,
  SNOOZE,
  STAIRS,
} from "./art";
import { atMillis, faceOf, idleAmount, shortDuration } from "./palette";
import { STAMPS, WORDS, isHeld, markOf, stampFor, stampHtml } from "./status";
import {
  FLOORS,
  OUTDOOR,
  buildPods,
  planRooms,
  posts,
  splitPod,
  tally,
  traffic,
} from "./layout";
import type { Member, Pod, Post, RoomPlan } from "./layout";
import { clip, esc } from "./esc";

const LABELS = new Map<ZoneId, string>(ZONES.map((z) => [z.id, z.label]));
/** How big a person is drawn. Seniority as size means a chain of three reads at a glance and costs
 *  no indentation, no brackets and no lines between boxes. */
const SCALE = [4, 3, 2, 2];
/** More footprints than this in one pod is a list, not a picture. */
const AWAY_SHOWN = 3;

/** Everything the render needs that is not the worker in hand. Threaded rather than reached for,
 *  so the whole scene is one pure function of the snapshot. */
interface Ctx {
  pods: Pod[];
  mail: Map<string, { n: number; who: string[] }>;
}

function spriteOf(w: Worker, scale: number): string {
  const pal = w.status === "foreign" ? GHOST_PAL : SKIN_PAL;
  // Only a worker that can move gets two frames; a finished one is half the rectangles.
  return w.status === "running"
    ? drawFrames([POSE_REST, POSE_MOVE], pal, { scale, className: "wp-sprite" })
    : draw(POSE_REST, pal, { scale, className: "wp-sprite" });
}

/** One person. `data-run-id` is on this element and nowhere inside it, so a click anywhere on the
 *  sprite, the name or the speech bubble resolves to exactly one worker. */
function worker(w: Worker, depth: number, ctx: Ctx, leadName?: string): string {
  const idle = idleAmount(w.idle_seconds);
  // Only work can stall. A completed run's idle clock is just how long ago it ended, and a session
  // interact did not start has no clock we own at all — the building used to snooze both of them,
  // which is a finished worker wearing z’s, and it is also the desk saying the opposite about
  // the same person. One rule now, in status.ts, for both surfaces.
  const stalled = isHeld(w) ? 1 : 0;
  const scale = SCALE[Math.min(depth, SCALE.length - 1)];
  const speaks = w.status === "running" || w.status === "error";
  const bubble =
    speaks && w.activity ? `<div class="wp-bubble">${esc(clip(w.activity, 64))}</div>` : "";
  const snooze = stalled
    ? `<span class="wp-snooze">${draw(SNOOZE.grid, SNOOZE.pal, { scale: 2, outline: false })}</span>`
    : "";
  // The word, said the way the desk says it. This replaced a small blinking wedge over the head:
  // the wedge was the building's whole answer to "this agent died", and it spelled nothing, so the
  // one state that most wants a person was also the one the desk shouted and the map whispered.
  // A placard, mounted like every other sign in this building — opaque, hard pixel shadow — and
  // carrying the identical stamp the work order carries.
  const st = stampFor(w);
  const stamp = st ? `<div class="wp-hang">${stampHtml(st)}</div>` : "";
  // Post already exchanged, marked quietly. The arrival is animated, but a cold load has no
  // arrival to show and the conversation still happened.
  const mail = ctx.mail.get(w.run_id);
  const note = mail
    ? `<span class="wp-mail" title="in conversation with ${esc(mail.who.join(", "))}">` +
      `${draw(NOTE.grid, NOTE.pal, { scale: 2 })}` +
      (mail.n > 1 ? `<b>${mail.n}</b>` : "") +
      `</span>`
    : "";
  const since =
    w.idle_seconds >= 30 ? `<span class="wp-since">${esc(shortDuration(w.idle_seconds))}</span>` : "";
  const under = leadName
    ? `<div class="wp-lead-of" title="reports to ${esc(leadName)}">&#8627; ${esc(clip(leadName, 18))}</div>`
    : "";
  const label =
    `${w.name} — ${w.status}, ${LABELS.get(w.zone) ?? w.zone}` +
    (w.activity ? `: ${w.activity}` : "");

  return (
    `<figure class="wp-worker" data-run-id="${esc(w.run_id)}" data-status="${esc(w.status)}" ` +
    `data-depth="${depth}" data-stalled="${stalled}" data-zone="${esc(w.zone)}" ` +
    `style="--idle:${idle};${faceOf(w.run_id)}" tabindex="0" role="button" title="${esc(label)}" ` +
    `aria-label="${esc(label)}">` +
    bubble +
    // Under the speech, directly over the head. Above the bubble it drifted to the top of the room
    // — on a stuck worker with a long activity line the ERROR ended up level with the room plaque,
    // and a reader had to trace down two elements to learn whose it was. The desk prints it AT the
    // name; the building has to put it AT the person.
    stamp +
    `<div class="wp-stage">${spriteOf(w, scale)}<span class="wp-shadow"></span>${note}${snooze}</div>` +
    `<figcaption class="wp-plate">${markOf(w.status)}` +
    `<span class="wp-name">${esc(w.name)}</span>${since}</figcaption>` +
    under +
    `</figure>`
  );
}

/** Where the rest of the pod went. One low strip of destinations rather than a footprint each:
 *  a lead with six people out was turning into a form to read. */
function awayStrip(away: Member[], accent: string): string {
  if (!away.length) return "";
  const shown = away.slice(0, AWAY_SHOWN);
  const rest = away.length - shown.length;
  const chip = (m: Member) =>
    `<span class="wp-away" title="${esc(m.worker.name)} is in ${esc(LABELS.get(m.worker.zone) ?? m.worker.zone)}">` +
    `<i>&rarr;</i>${esc(LABELS.get(m.worker.zone) ?? m.worker.zone)}</span>`;
  const more = rest
    ? `<span class="wp-away" title="${esc(away.slice(AWAY_SHOWN).map((m) => m.worker.name).join(", "))}">+${rest}</span>`
    : "";
  return `<div class="wp-out" style="--accent:${accent}">${shown.map(chip).join("")}${more}</div>`;
}

/** A lead standing on their own platform with whoever is with them. */
function podOf(pod: Pod, ctx: Ctx): string {
  const { here, away } = splitPod(pod);
  return (
    `<div class="wp-pod" data-pod="${esc(pod.lead.run_id)}" style="--accent:${pod.accent}">` +
    worker(pod.lead, 0, ctx) +
    here.map((m) => worker(m.worker, m.depth, ctx)).join("") +
    awayStrip(away, pod.accent) +
    `</div>`
  );
}

/** Somebody else's report, working in this room. Same platform, smaller, in their lead's colour —
 *  which is the whole mechanism: no wire is drawn between rooms, the colour carries it. */
function visitorOf(m: Member, ctx: Ctx): string {
  const pod = ctx.pods.find((p) => p.members.some((x) => x.worker.run_id === m.worker.run_id));
  const accent = pod ? pod.accent : "var(--wp-h1)";
  return (
    `<div class="wp-pod" data-visiting="1" data-pod="${esc(pod ? pod.lead.run_id : "")}" ` +
    `style="--accent:${accent}">` +
    worker(m.worker, Math.max(1, m.depth), ctx, pod?.lead.name) +
    `</div>`
  );
}

function roomOf(zone: ZoneId, plan: RoomPlan | undefined, ctx: Ctx, outdoor = false): string {
  const heads = plan?.headcount ?? 0;
  const busy =
    (plan?.anchored ?? []).some((p) => p.lead.status === "running") ||
    (plan?.visiting ?? []).some((m) => m.worker.status === "running");
  const inner =
    (plan?.anchored ?? []).map((p) => podOf(p, ctx)).join("") +
    (plan?.visiting ?? []).map((m) => visitorOf(m, ctx)).join("");
  const deck = inner || `<span class="wp-empty">empty</span>`;
  // Outdoors has to hold a whole storey of height beside the building, so it is furnished like a
  // place: a disc, weather at three depths, and the rest of the city too far away to make out.
  const sky = outdoor
    ? `<span class="wp-disc">${draw(DISC.grid, DISC.pal, { scale: 3, outline: false })}</span>` +
      `<span class="wp-cloud a">${draw(CLOUD.grid, CLOUD.pal, { scale: 3, outline: false })}</span>` +
      `<span class="wp-cloud b">${draw(CLOUD.grid, CLOUD.pal, { scale: 2, outline: false })}</span>` +
      `<span class="wp-cloud c">${draw(CLOUD.grid, CLOUD.pal, { scale: 4, outline: false })}</span>` +
      `${draw(HORIZON.grid, HORIZON.pal, { scale: 4, outline: false, fluid: true, className: "wp-skyline" })}`
    : "";
  return (
    `<${outdoor ? "div" : "section"} class="${outdoor ? "wp-outside" : "wp-room"}" data-zone="${zone}" ` +
    `data-lit="${heads ? 1 : 0}" data-busy="${busy ? 1 : 0}" style="--heads:${heads}">` +
    `<span class="wp-plaque">${esc(LABELS.get(zone) ?? zone)}${heads ? `<b>${heads}</b>` : ""}</span>` +
    `<div class="wp-wall${outdoor ? " wp-yard" : ""}">${sky}` +
    (zone === "entry"
      ? drawFrames(DOOR.frames, DOOR.pal, { scale: 4, className: "wp-prop wp-door" })
      : draw(PROPS[zone].grid, PROPS[zone].pal, {
          scale: outdoor ? 4 : 3,
          outline: !outdoor,
          className: "wp-prop",
        })) +
    `</div>` +
    `<div class="wp-deck">${deck}</div>` +
    (outdoor ? `<span class="wp-gangway"></span>` : "") +
    `</${outdoor ? "div" : "section"}>`
  );
}

function money(total: number): string {
  if (!total) return "—";
  return total >= 1 ? `~$${total.toFixed(2)}` : `~$${total.toFixed(3)}`;
}

function hud(state: TeamState, t: ReturnType<typeof tally>, mail: number): string {
  // The data layer stamps SECONDS; a Date wants milliseconds. Handed over raw this read
  // "as of 17:25:34" for a snapshot taken at lunchtime — a 1970 clock nobody noticed, because
  // every dev fixture happens to use Date.UTC and so was already in milliseconds.
  const when = new Date(atMillis(state.at)).toLocaleTimeString();
  const chip = (status: string, n: number, word: string, colour: string) =>
    n ? `<span class="wp-chip" style="--mark:${colour}">${markOf(status)}<b>${n}</b> ${word}</span>` : "";
  const projects = t.projects.length === 1 ? esc(t.projects[0]) : `${t.projects.length} projects`;
  return (
    `<header class="wp-hud">` +
    `<span class="wp-sign"><span class="wp-sign-name">The team</span>` +
    `<span class="wp-sign-sub">${projects}</span></span>` +
    `<span class="wp-tally">` +
    // The words come from the shared lexicon, not from this file. The board by the door used to
    // carry its own three — a different one for each of the states the desk already stamped — so
    // one set of facts had two vocabularies, which is the same defect as two colour allocators,
    // only in prose. statusVocabulary.test.ts fails if a literal ever reappears in this file.
    chip("running", t.running, WORDS.running, "var(--wp-ok)") +
    chip("error", t.error, WORDS.error, "var(--wp-bad)") +
    chip("done", t.done, WORDS.done, "var(--wp-dim)") +
    chip("foreign", t.foreign, WORDS.foreign, "var(--wp-dim)") +
    chip("held", t.idle, WORDS.held, "var(--wp-dim)") +
    (mail ? `<span class="wp-chip">${draw(NOTE.grid, NOTE.pal, { scale: 2 })}<b>${mail}</b> messages</span>` : "") +
    `<span class="wp-chip">spend <b>${money(t.cost)}</b></span>` +
    `</span>` +
    `<span class="wp-clock">as of ${esc(when)}</span>` +
    `</header>`
  );
}

/** The key. It shows the STAMPS, not a private set of marks with words beside them: whatever is
 *  printed here is the identical element printed over a person's head and across a work order on
 *  the desk, so the legend is a key to ONE vocabulary rather than a translation table between two.
 */
function legend(): string {
  return (
    `<footer class="wp-legend">` +
    `<span class="wp-key" style="--mark:var(--wp-ok)">${markOf("running")} ${WORDS.running} — nothing stamped</span>` +
    `<span class="wp-key">${stampHtml(STAMPS.error)}</span>` +
    `<span class="wp-key">${stampHtml(STAMPS.held)}</span>` +
    `<span class="wp-key">${stampHtml(STAMPS.done)}</span>` +
    `<span class="wp-key">${stampHtml(STAMPS.foreign)}</span>` +
    `<span>${draw(NOTE.grid, NOTE.pal, { scale: 2 })} carried between two agents who spoke</span>` +
    `<span>one platform = one lead and their reports; the colour follows them across rooms</span>` +
    `</footer>`
  );
}

/** A storey's column template, worked out here rather than left to flexbox, because the rooms use
 *  `subgrid` to share their floor line and subgrid needs the columns to exist on the parent. A busy
 *  room simply gets more of the width — the building visibly bulges where the work is. */
/** How wide each room on a floor gets.
 *
 *  An empty room still has to be THERE — the building has to stay a building, and a room that
 *  vanishes when its last worker leaves makes the place unreadable. But it does not need a quarter
 *  of the floor to say so. At 1fr an empty LIBRARY and STUDIO took as much width between them as
 *  the LAB with people in it, and about a quarter of the canvas was blank.
 *
 *  A vacant room is a sliver that keeps its sign and its furniture; the work gets the rest. */
function columns(cells: { zone: ZoneId | "lobby"; heads: number }[]): string {
  const occupied = cells.some((c) => c.heads > 0);
  return cells
    .map((c) => {
      if (c.zone === "lobby") return "54px";
      if (c.heads) return `minmax(136px, ${1 + c.heads * 2}fr)`;
      // Only squeezed when there is somewhere for the space to GO. A floor nobody is on keeps
      // its rooms evenly divided rather than collapsing into an arbitrary one.
      return occupied ? "minmax(58px, .35fr)" : "minmax(76px, 1fr)";
    })
    .join(" ");
}

/** The whole visible thing, as markup. Kept apart from the document shell so it can be dropped into
 *  a test page or a live webview without dragging the CSP with it. */
export function renderScene(state: TeamState): string {
  // Everything below is collected into one <defs> block: a workplace is the same few drawings
  // repeated once per person and once per room, and writing each one out at every call site is
  // most of what the document weighs. Opened here and closed once the whole scene is built, so
  // nothing can be drawn outside it and left dangling.
  openSheet();
  const pods = buildPods(state);
  const plans = planRooms(pods);
  const t = tally(state);
  const list: Post[] = posts(state);
  const ctx: Ctx = { pods, mail: traffic(list, state.workers) };

  // The stairwell, on EVERY storey and always the first column, so it is a genuine vertical core
  // rather than a picture of stairs on the ground floor. Everything about the motion depends on
  // it: a worker sent from the Lab to the Code room has to GET there, and the only honest route
  // through a building drawn in section is out of the room, along the storey, and up the stairs.
  // First column and a fixed width means the shaft is plumb by construction — no fr unit can
  // knock the flights out of line with each other.
  const shaft = (storey: number) =>
    `<div class="wp-room wp-lobby wp-shaft" data-zone="lobby" data-storey="${storey}" ` +
    `data-lit="0" data-busy="0">` +
    `<div class="wp-wall">${draw(STAIRS.grid, STAIRS.pal, { scale: 4, className: "wp-prop" })}</div>` +
    `<div class="wp-deck"></div></div>`;

  const floors = FLOORS.map((zones, i) => {
    const heads = (z: ZoneId) => plans.get(z)?.headcount ?? 0;
    // The ground floor reads left to right as break room, stairs, then the door — so the way out is
    // where the eye ends up, which is where a finished worker ends up too.
    const storey = FLOORS.length - 1 - i;
    const cells: { zone: ZoneId | "lobby"; heads: number }[] = [
      { zone: "lobby", heads: 0 },
      ...zones.map((z) => ({ zone: z, heads: heads(z) })),
    ];
    const body = shaft(storey) + zones.map((z) => roomOf(z, plans.get(z), ctx)).join("");
    // A storey nobody is on keeps its rooms — the building has to stay a building — but stops
    // paying full height for them. With a small team the empty floors were most of the canvas,
    // and the people were crammed into a corner of it.
    const vacant = cells.every((c) => c.zone === "lobby" || c.heads === 0)
      ? " data-vacant=\"1\""
      : "";
    return (
      `<div class="wp-floor" data-floor="${storey}"${vacant} ` +
      `style="--cols:${columns(cells)}">${body}</div>`
    );
  }).join("");

  // The post, handed to the script as data rather than as a second copy of the state: it only ever
  // needs to know which exchanges are NEW since the last draw, so that nothing is re-announced.
  // `g` is how many seconds ago it was said, or null where the exchange predates the stamp. It
  // is the whole difference between a cold open that can show the team talking and one that can
  // only stay silent to avoid replaying an hour-old conversation as if it were live.
  const mailbag = list.map((p) => ({
    f: p.from,
    t: p.to,
    k: p.key,
    x: clip(p.text, 80),
    g: p.age === null ? null : Math.round(p.age),
  }));
  const post =
    `<div class="wp-post" aria-hidden="true" data-links="${esc(JSON.stringify(mailbag))}">` +
    `<span class="wp-note-art">${draw(NOTE.grid, NOTE.pal, { scale: 2 })}</span></div>`;

  // The bodies that MOVE, drawn once and cloned by the engine.
  //
  // A traveller cannot be the worker's own sprite: that sprite is two frames of someone standing
  // at a desk, and it lives inside a grid cell that is the wrong place to be while you are in the
  // corridor. So the walk cycle is emitted ONCE, hidden, and the engine clones it onto the traffic
  // layer, copies the worker's own `--c-*` properties onto the clone, and walks it. Same person,
  // same twenty rectangles, now on a floor instead of in a cell — and the document pays for the
  // walk cycle once rather than once per worker.
  const trafficLayer =
    `<div class="wp-traffic" aria-hidden="true">` +
    `<div class="wp-proto" data-proto="walk">` +
    drawFrames([POSE_WALK_A, POSE_WALK_B], SKIN_PAL, { scale: 1, className: "wp-sprite" }) +
    `</div>` +
    `<div class="wp-proto" data-proto="run">` +
    drawFrames([POSE_RUN_A, POSE_RUN_B], RUNNER_PAL, { scale: 1, className: "wp-sprite" }) +
    `</div>` +
    `</div>`;

  const inner =
    hud(state, t, list.length) +
    // The outdoors is sized like a room, for the same reason: it has to stay THERE — the web is
    // a place people go and the building has to have an outside — but with nobody out there it
    // does not need a quarter of the canvas to say so.
    `<div class="wp-scene" data-outside="${plans.get(OUTDOOR)?.headcount ? 1 : 0}">` +
    `<div class="wp-building"><div class="wp-roof"></div>${floors}<div class="wp-base"></div></div>` +
    roomOf(OUTDOOR, plans.get(OUTDOOR), ctx, true) +
    post +
    trafficLayer +
    `</div>` +
    legend();

  // Closed only now: every draw in the scene has happened, so this is the complete set.
  return `<div class="wp">${closeSheet()}${inner}</div>`;
}
