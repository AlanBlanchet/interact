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
import { draw, drawFrames } from "./pixels";
import {
  CLOUD,
  DISC,
  GHOST_PAL,
  HORIZON,
  MARKS,
  NOTE,
  POSE_MOVE,
  POSE_REST,
  PROPS,
  SKIN_PAL,
  SNOOZE,
  STAIRS,
} from "./art";
import { faceOf, idleAmount, shortDuration } from "./palette";
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
/** Past two minutes of nothing, a worker is not working — and stops moving. */
const STALL_SECONDS = 120;
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

function markOf(status: string): string {
  const piece = MARKS[status] ?? MARKS.foreign;
  return draw(piece.grid, piece.pal, { scale: 2, outline: false });
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
  const stalled = w.idle_seconds >= STALL_SECONDS ? 1 : 0;
  const scale = SCALE[Math.min(depth, SCALE.length - 1)];
  const speaks = w.status === "running" || w.status === "error";
  const bubble =
    speaks && w.activity ? `<div class="wp-bubble">${esc(clip(w.activity, 64))}</div>` : "";
  const snooze = stalled
    ? `<span class="wp-snooze">${draw(SNOOZE.grid, SNOOZE.pal, { scale: 2, outline: false })}</span>`
    : "";
  const beacon =
    w.status === "error"
      ? `<span class="wp-beacon">${draw(MARKS.error.grid, MARKS.error.pal, { scale: 3 })}</span>`
      : "";
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
    `<div class="wp-stage">${spriteOf(w, scale)}<span class="wp-shadow"></span>${note}${snooze}${beacon}</div>` +
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
    draw(PROPS[zone].grid, PROPS[zone].pal, { scale: outdoor ? 4 : 3, outline: !outdoor, className: "wp-prop" }) +
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
  const when = new Date(state.at).toLocaleTimeString();
  const chip = (status: string, n: number, word: string, colour: string) =>
    n ? `<span class="wp-chip" style="--mark:${colour}">${markOf(status)}<b>${n}</b> ${word}</span>` : "";
  const projects = t.projects.length === 1 ? esc(t.projects[0]) : `${t.projects.length} projects`;
  return (
    `<header class="wp-hud">` +
    `<span class="wp-sign"><span class="wp-sign-name">The team</span>` +
    `<span class="wp-sign-sub">${projects}</span></span>` +
    `<span class="wp-tally">` +
    chip("running", t.running, "working", "var(--wp-ok)") +
    chip("error", t.error, "stuck", "var(--wp-bad)") +
    chip("done", t.done, "finished", "var(--wp-dim)") +
    chip("foreign", t.foreign, "not ours", "var(--wp-dim)") +
    (t.idle ? `<span class="wp-chip"><b>${t.idle}</b> idle 2m+</span>` : "") +
    (mail ? `<span class="wp-chip">${draw(NOTE.grid, NOTE.pal, { scale: 2 })}<b>${mail}</b> messages</span>` : "") +
    `<span class="wp-chip">spend <b>${money(t.cost)}</b></span>` +
    `</span>` +
    `<span class="wp-clock">as of ${esc(when)}</span>` +
    `</header>`
  );
}

function legend(): string {
  const item = (status: string, word: string, colour: string) =>
    `<span style="--mark:${colour}">${markOf(status)} ${word}</span>`;
  return (
    `<footer class="wp-legend">` +
    item("running", "working", "var(--wp-ok)") +
    item("error", "stuck", "var(--wp-bad)") +
    item("done", "finished", "var(--wp-dim)") +
    item("foreign", "not ours", "var(--wp-dim)") +
    `<span>faded &amp; still = idle</span>` +
    `<span>${draw(NOTE.grid, NOTE.pal, { scale: 2 })} carried between two agents who spoke</span>` +
    `<span>one platform = one lead and their reports; the colour follows them across rooms</span>` +
    `</footer>`
  );
}

/** A storey's column template, worked out here rather than left to flexbox, because the rooms use
 *  `subgrid` to share their floor line and subgrid needs the columns to exist on the parent. A busy
 *  room simply gets more of the width — the building visibly bulges where the work is. */
function columns(cells: { zone: ZoneId | "lobby"; heads: number }[]): string {
  return cells
    .map((c) => (c.zone === "lobby" ? "54px" : `minmax(${c.heads ? 136 : 76}px, ${1 + c.heads * 2}fr)`))
    .join(" ");
}

/** The whole visible thing, as markup. Kept apart from the document shell so it can be dropped into
 *  a test page or a live webview without dragging the CSP with it. */
export function renderScene(state: TeamState): string {
  const pods = buildPods(state);
  const plans = planRooms(pods);
  const t = tally(state);
  const list: Post[] = posts(state);
  const ctx: Ctx = { pods, mail: traffic(list, state.workers) };

  const lobby =
    `<div class="wp-room wp-lobby" data-zone="lobby" data-lit="0" data-busy="0">` +
    `<div class="wp-wall">${draw(STAIRS.grid, STAIRS.pal, { scale: 3, className: "wp-prop" })}</div>` +
    `<div class="wp-deck"></div></div>`;

  const floors = FLOORS.map((zones, i) => {
    const ground = i === FLOORS.length - 1;
    const heads = (z: ZoneId) => plans.get(z)?.headcount ?? 0;
    // The ground floor reads left to right as break room, stairs, then the door — so the way out is
    // where the eye ends up, which is where a finished worker ends up too.
    const cells: { zone: ZoneId | "lobby"; heads: number }[] = ground
      ? [
          { zone: zones[0], heads: heads(zones[0]) },
          { zone: "lobby", heads: 0 },
          { zone: zones[1], heads: heads(zones[1]) },
        ]
      : zones.map((z) => ({ zone: z, heads: heads(z) }));
    const body = ground
      ? roomOf(zones[0], plans.get(zones[0]), ctx) + lobby + roomOf(zones[1], plans.get(zones[1]), ctx)
      : zones.map((z) => roomOf(z, plans.get(z), ctx)).join("");
    return (
      `<div class="wp-floor" data-floor="${FLOORS.length - 1 - i}" style="--cols:${columns(cells)}">` +
      `${body}</div>`
    );
  }).join("");

  // The post, handed to the script as data rather than as a second copy of the state: it only ever
  // needs to know which exchanges are NEW since the last draw, so that nothing is re-announced.
  const mailbag = list.map((p) => ({ f: p.from, t: p.to, k: p.key, x: clip(p.text, 80) }));
  const post =
    `<div class="wp-post" aria-hidden="true" data-links="${esc(JSON.stringify(mailbag))}">` +
    `<span class="wp-note-art">${draw(NOTE.grid, NOTE.pal, { scale: 2 })}</span></div>`;

  return (
    `<div class="wp">` +
    hud(state, t, list.length) +
    `<div class="wp-scene">` +
    `<div class="wp-building"><div class="wp-roof"></div>${floors}<div class="wp-base"></div></div>` +
    roomOf(OUTDOOR, plans.get(OUTDOOR), ctx, true) +
    post +
    `</div>` +
    legend() +
    `</div>`
  );
}
